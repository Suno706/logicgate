"""
NL -> truth-table model.

This is the actual ML piece. Given an English description of a desired
circuit ("output is high when A is on and B is off"), it predicts:

    n_inputs   ∈ {1, 2, 3, 4}
    tt_bits     -  0/1 string of length 2**n_inputs giving the predicted
                  output for each input row in standard order.

The model is intentionally lightweight (TF-IDF + per-cell logistic
regression) so it trains in seconds, has zero runtime dependencies beyond
scikit-learn, and the resulting `.pkl` is small. Architecture choice was
driven by:
    • the labels are noise-free (we synthesise them, so we can afford a
      simple discriminative model);
    • the user already has scikit-learn  -  no PyTorch / torch CUDA mess;
    • predictions need to feed Quine-McCluskey, so we predict the full
      16-bit truth table directly.

For higher-capacity experiments, swap the per-cell classifier for an MLP
or a small transformer  -  the dataset / scoring API stay the same.
"""
from __future__ import annotations
import csv
import os
import joblib
import numpy as np
from typing import List, Optional, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline


MODEL_DIR  = os.path.join(os.path.dirname(__file__), 'saved')
MODEL_PATH = os.path.join(MODEL_DIR, 'nl_tt_model.pkl')

MAX_INPUTS = 4
MAX_ROWS   = 1 << MAX_INPUTS   # 16


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_csv(csv_path: str) -> Tuple[List[str], np.ndarray, np.ndarray]:
    """Returns (texts, n_inputs[N], tt_bits[N, MAX_ROWS])."""
    texts, n_inputs_l, tt_l = [], [], []
    with open(csv_path, encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            n = int(row['n_inputs'])
            if n < 1 or n > MAX_INPUTS:
                continue
            bits = row['tt_bits']
            # Pad / truncate to MAX_ROWS columns (unused rows = 0).
            padded = bits.ljust(MAX_ROWS, '0')[:MAX_ROWS]
            texts.append(row['text'])
            n_inputs_l.append(n)
            tt_l.append([int(c) for c in padded])
    return texts, np.array(n_inputs_l, dtype=np.int8), np.array(tt_l, dtype=np.int8)


# ---------------------------------------------------------------------------
# Model  -  bundle of small classifiers
# ---------------------------------------------------------------------------

class NLTruthTableModel:
    """
    Bundle:
      • shared TF-IDF vectoriser
      • n_inputs classifier (LogisticRegression, 4 classes)
      • per-cell binary classifiers (one LogisticRegression per output bit,
        for cells 0..MAX_ROWS-1). Cells beyond the predicted n_inputs are
        ignored at inference time.
    """

    def __init__(self):
        self.vec: Optional[TfidfVectorizer] = None
        self.n_clf: Optional[LogisticRegression] = None
        self.cell_clfs: List[LogisticRegression] = []

    # -- training --------------------------------------------------------
    def fit(self, texts: List[str], n_inputs: np.ndarray, tt: np.ndarray,
            *, verbose: bool = True) -> dict:
        # Two vectorisers combined: char n-grams catch spelling/typos and
        # word n-grams catch phrases like "more than one", "at least two".
        self.vec = FeatureUnion([
            ('char', TfidfVectorizer(
                analyzer='char_wb', ngram_range=(2, 5),
                min_df=2, max_features=30000, sublinear_tf=True)),
            ('word', TfidfVectorizer(
                analyzer='word', ngram_range=(1, 3),
                min_df=2, max_features=20000, sublinear_tf=True,
                token_pattern=r'\b\w[\w=]*\b')),
        ])
        X = self.vec.fit_transform(texts)
        if verbose:
            print(f"  Combined feature matrix: {X.shape}")

        self.n_clf = LogisticRegression(max_iter=500, C=4.0)
        self.n_clf.fit(X, n_inputs)
        if verbose:
            print(f"  n_inputs train acc: {self.n_clf.score(X, n_inputs):.3f}")

        self.cell_clfs = []
        for col in range(MAX_ROWS):
            y = tt[:, col]
            if y.min() == y.max():
                const = int(y[0])
                self.cell_clfs.append(_Const(const))
                continue
            # Stronger regularisation (lower C -> more reg) for cells with
            # high variance; balanced weights to fight predict-0 bias.
            clf = LogisticRegression(max_iter=500, C=3.0,
                                     class_weight='balanced')
            clf.fit(X, y)
            self.cell_clfs.append(clf)
            if verbose and col < 4:
                print(f"  cell[{col}] train acc: {clf.score(X, y):.3f}")
        return {'features': X.shape[1]}

    # -- inference -------------------------------------------------------
    def predict(self, text: str) -> dict:
        if self.vec is None or self.n_clf is None:
            raise RuntimeError("Model is not trained or loaded.")
        X = self.vec.transform([text])
        n_in = int(self.n_clf.predict(X)[0])
        n_in = max(1, min(MAX_INPUTS, n_in))
        n_rows = 1 << n_in
        bits = []
        for col in range(n_rows):
            clf = self.cell_clfs[col]
            bits.append(int(clf.predict(X)[0]))
        # Per-class confidence: max of (1 - row-flip-prob) across the rows.
        proba_n = self.n_clf.predict_proba(X)[0]
        conf_n  = float(proba_n[list(self.n_clf.classes_).index(n_in)])
        bit_confs = []
        for col in range(n_rows):
            clf = self.cell_clfs[col]
            if isinstance(clf, _Const):
                bit_confs.append(1.0)
            else:
                p = clf.predict_proba(X)[0]
                bit_confs.append(float(max(p)))
        minterms = [i for i, b in enumerate(bits) if b == 1]
        return {
            'n_inputs':       n_in,
            'tt_bits':        ''.join(str(b) for b in bits),
            'minterms':       minterms,
            'n_inputs_conf':  conf_n,
            'mean_cell_conf': float(np.mean(bit_confs)) if bit_confs else 0.0,
        }

    # -- persistence ----------------------------------------------------
    def save(self, path: str = MODEL_PATH) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump({
            'vec':       self.vec,
            'n_clf':     self.n_clf,
            'cell_clfs': self.cell_clfs,
        }, path, compress=3)

    @classmethod
    def load(cls, path: str = MODEL_PATH) -> 'NLTruthTableModel':
        bundle = joblib.load(path)
        m = cls()
        m.vec       = bundle['vec']
        m.n_clf     = bundle['n_clf']
        m.cell_clfs = bundle['cell_clfs']
        return m


class _Const:
    """Tiny stand-in for a LogisticRegression that always predicts one class."""
    def __init__(self, value: int):
        self.value = value
    def predict(self, X):
        return np.full(X.shape[0], self.value, dtype=np.int8)
    def predict_proba(self, X):
        p = np.zeros((X.shape[0], 2))
        p[:, self.value] = 1.0
        return p


# ---------------------------------------------------------------------------
# Training entry-point
# ---------------------------------------------------------------------------

def train(csv_path: Optional[str] = None,
          model_path: str = MODEL_PATH,
          *, verbose: bool = True) -> dict:
    """Train the model and save it. Returns a small metrics dict."""
    if csv_path is None:
        csv_path = os.path.join(os.path.dirname(__file__), '..',
                                'data', 'nl_training.csv')
    if verbose:
        print(f"[NLTTModel] loading {csv_path}")
    texts, n_inputs, tt = _load_csv(csv_path)
    if verbose:
        print(f"[NLTTModel] loaded {len(texts)} rows")

    # Hold-out split for an honest accuracy number.
    rng = np.random.default_rng(42)
    idx = rng.permutation(len(texts))
    cut = int(0.9 * len(idx))
    tr, te = idx[:cut], idx[cut:]
    tr_texts = [texts[i] for i in tr]
    te_texts = [texts[i] for i in te]

    model = NLTruthTableModel()
    model.fit(tr_texts, n_inputs[tr], tt[tr], verbose=verbose)

    # Score on the held-out split: exact-match across the active truth-table
    # rows (using the model's own predicted n_inputs, like at inference time).
    exact_match = 0
    n_input_correct = 0
    for text, n_true, tt_true in zip(te_texts, n_inputs[te], tt[te]):
        pred = model.predict(text)
        if pred['n_inputs'] == n_true:
            n_input_correct += 1
        rows = 1 << int(n_true)
        if (pred['n_inputs'] == n_true
                and pred['tt_bits'][:rows] == ''.join(str(b) for b in tt_true[:rows])):
            exact_match += 1
    metrics = {
        'rows_total':       len(texts),
        'rows_train':       len(tr),
        'rows_test':        len(te),
        'n_inputs_acc':     n_input_correct / len(te),
        'exact_match_acc':  exact_match / len(te),
    }
    if verbose:
        print(f"[NLTTModel] held-out n_inputs accuracy: {metrics['n_inputs_acc']:.3f}")
        print(f"[NLTTModel] held-out exact truth-table match: {metrics['exact_match_acc']:.3f}")
    model.save(model_path)
    if verbose:
        print(f"[NLTTModel] saved to {model_path}")
    return metrics


if __name__ == '__main__':
    train()
