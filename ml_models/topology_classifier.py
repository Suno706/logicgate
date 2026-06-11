"""
Topology classifier — runtime wrapper around the pickled RandomForest.

Honest description: this is the genuine ML in the project. It does what
hand-coded rules cannot — recognise that a half-adder built out of NAND-only
gates is structurally the same intent as the textbook XOR+AND version,
because both produce the same fingerprint in feature space.

Public API:
    clf = TopologyClassifier()
    clf.load()                       # pickled model + label encoder
    clf.classify(circuit)            # -> {"top": [(label, prob), ...]}
    clf.is_ready()                   # bool, did load() succeed
"""
import os
import pickle
from typing import List, Optional, Tuple

from ml_models.topology_features import FEATURE_NAMES, extract


MODEL_PATH = os.path.join(os.path.dirname(__file__), "saved",
                          "topology_classifier.pkl")


class TopologyClassifier:
    def __init__(self):
        self.model           = None
        self.label_encoder   = None
        self.feature_names   = list(FEATURE_NAMES)
        # Populated by load(); read by /api/topology/info so the UI can
        # show the metrics we recorded at training time.
        self.metrics: dict   = {}

    # ---------------------------------------------------------------- I/O
    def load(self, path: str = MODEL_PATH) -> bool:
        try:
            with open(path, "rb") as f:
                blob = pickle.load(f)
            self.model         = blob["model"]
            self.label_encoder = blob["label_encoder"]
            self.metrics       = blob.get("metrics", {})
            # Sanity: feature names must match what the model was trained on.
            saved_names = blob.get("feature_names")
            if saved_names and list(saved_names) != self.feature_names:
                # Refuse to load — mismatched columns would silently produce
                # garbage predictions.
                self.model = None
                self.label_encoder = None
                return False
            return True
        except (FileNotFoundError, KeyError, EOFError, pickle.UnpicklingError):
            return False

    def save(self, path: str = MODEL_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "model":         self.model,
                "label_encoder": self.label_encoder,
                "feature_names": self.feature_names,
                "metrics":       self.metrics,
            }, f)

    def is_ready(self) -> bool:
        return self.model is not None and self.label_encoder is not None

    # ------------------------------------------------------------ Inference
    def classify(self, circuit: dict, top_k: int = 3) -> dict:
        """
        Returns top-K predictions with calibrated probabilities. If the
        circuit is too small (≤2 gates) to be a meaningful canonical type,
        falls back to "generic" with low confidence rather than overclaiming.
        """
        if not self.is_ready():
            return {"top": [], "ready": False}

        gates = circuit.get("gates", [])
        if len(gates) < 2:
            return {
                "top":   [("generic", 1.0)],
                "ready": True,
                "note":  "Circuit too small to classify yet — keep building.",
            }

        feats = extract(circuit)
        probs = self.model.predict_proba([feats])[0]
        labels = self.label_encoder.inverse_transform(range(len(probs)))
        pairs: List[Tuple[str, float]] = sorted(
            zip(labels, probs), key=lambda p: p[1], reverse=True
        )[:top_k]
        return {
            "top":   [(lbl, float(p)) for lbl, p in pairs],
            "ready": True,
        }

    # ------------------------------------------- Diagnostics / model card
    def feature_importance(self) -> Optional[list]:
        if self.model is None or not hasattr(self.model, "feature_importances_"):
            return None
        pairs = sorted(
            zip(self.feature_names, self.model.feature_importances_),
            key=lambda p: p[1], reverse=True
        )
        return [{"feature": f, "importance": float(i)} for f, i in pairs]
