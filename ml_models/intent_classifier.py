"""
ML intent classifier for the question solver.

Replaces the hand-written regex intent rules in QuestionSolver._classify_intent
with a real scikit-learn model:

  TF-IDF (word 1-2 grams + char 3-5 grams)
    ->  LogisticRegression (multinomial, balanced class weights)

Why character n-grams?
  Catches misspellings ("minimze", "mininze", "minimise") and English/typo
  variants without us hand-listing them.

Output
------
  classify(text)              -> (intent_label, confidence)
  classify_with_probs(text)   -> (intent_label, confidence, all_probs_dict)

Falls back to the regex classifier (passed in by QuestionSolver) if the model
isn't loaded yet or returns very low confidence.

No LLM, no API. Pure scikit-learn + numpy.
"""
from __future__ import annotations
import os
import joblib
import numpy as np

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

from .intent_data import all_samples


SAVED_DIR  = os.path.join(os.path.dirname(__file__), 'saved')
MODEL_PATH = os.path.join(SAVED_DIR, 'intent_classifier.pkl')


def _build_pipeline() -> Pipeline:
    """TF-IDF (word + char) -> LogisticRegression."""
    word_v = TfidfVectorizer(analyzer='word',     ngram_range=(1, 2),
                             min_df=1, sublinear_tf=True)
    char_v = TfidfVectorizer(analyzer='char_wb',  ngram_range=(3, 5),
                             min_df=1, sublinear_tf=True)
    features = FeatureUnion([('w', word_v), ('c', char_v)])
    clf = LogisticRegression(max_iter=2000, class_weight='balanced',
                             solver='lbfgs', C=4.0)
    return Pipeline([('feat', features), ('clf', clf)])


class IntentClassifier:
    """Loads a trained intent model, or trains one from intent_data."""

    LOW_CONF = 0.30  # below this the caller should fall back to rule-based

    def __init__(self):
        os.makedirs(SAVED_DIR, exist_ok=True)
        self.pipe = None
        self._load_or_train()

    # -- lifecycle ------------------------------------------------------------

    def _load_or_train(self):
        if os.path.exists(MODEL_PATH):
            try:
                self.pipe = joblib.load(MODEL_PATH)
                print('[IntentClassifier] Loaded saved model.')
                return
            except Exception as e:
                print(f'[IntentClassifier] Load failed ({e}); retraining.')
        self.train()

    def train(self, verbose: bool = False) -> float:
        data = all_samples()
        X = [t for t, _ in data]
        y = [lbl for _, lbl in data]

        # Stratified split so each intent shows up in both halves.
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=0.15, random_state=42, stratify=y)

        self.pipe = _build_pipeline()
        self.pipe.fit(X_tr, y_tr)

        acc = accuracy_score(y_te, self.pipe.predict(X_te))
        print(f'[IntentClassifier] Trained on {len(X_tr)} samples, '
              f'test acc {acc:.3f} on {len(X_te)} held-out questions.')
        if verbose:
            print(classification_report(y_te, self.pipe.predict(X_te)))

        joblib.dump(self.pipe, MODEL_PATH)
        return acc

    # -- inference ------------------------------------------------------------

    def classify(self, text: str):
        intent, conf, _ = self.classify_with_probs(text)
        return intent, conf

    def classify_with_probs(self, text: str):
        if self.pipe is None or not text:
            return 'general', 0.0, {}
        probs = self.pipe.predict_proba([text])[0]
        labels = self.pipe.classes_
        i = int(np.argmax(probs))
        return labels[i], float(probs[i]), dict(zip(labels, map(float, probs)))


if __name__ == '__main__':
    ic = IntentClassifier()
    ic.train(verbose=True)
    for q in ['build a half adder',
              'half adder using nor',
              'how many gates does this have',
              'what does this circuit do',
              'any faults',
              'minimize please',
              'what if I change AND to NAND',
              'output for A=1 B=0',
              'flip B from 0 to 1',
              'Y is 1 when A=1 and B=0',
              'output 1 for inputs 011, 110',
              # adversarial misspellings
              'minimze ths', 'how mny gtes', 'wut does ths do',
              'biuld a hlf addr']:
        i, c, _ = ic.classify_with_probs(q)
        print(f'  {q!r:50s}  -> {i:14s}  ({c:.2f})')
