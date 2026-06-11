"""
Train the Topology Classifier.

What this script does:
  1. Generates a labeled dataset of circuits (per-label generators in
     ml_models/topology_dataset.py).
  2. Extracts structural features (ml_models/topology_features.py).
  3. Splits into train / val / test (60/20/20, stratified).
  4. Trains a RandomForest with 5-fold cross-validation on the train set.
  5. Reports per-class precision/recall/F1 + confusion matrix + feature
     importances. Saves the model + metrics to
     ml_models/saved/topology_classifier.pkl.
  6. Writes a copy of the metrics to ml_models/saved/topology_metrics.json
     so the /api/topology/info endpoint can surface them in the UI.

Reproducibility: pass --seed to fix randomness. Default seed=0 gives a
deterministic dataset.

Run:
    python train_topology.py
    python train_topology.py --per-label 400 --seed 42
"""
import argparse
import json
import os
import sys
from collections import Counter

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (
    classification_report, confusion_matrix, f1_score
)

# Ensure we can import the package layout
sys.path.insert(0, os.path.dirname(__file__))

from ml_models.topology_classifier import TopologyClassifier
from ml_models.topology_dataset import build as build_dataset, LABELS
from ml_models.topology_features import FEATURE_NAMES, extract


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-label", type=int, default=200,
                    help="Examples generated per label (default 200).")
    ap.add_argument("--seed", type=int, default=0,
                    help="Random seed for dataset + model.")
    ap.add_argument("--n-estimators", type=int, default=200,
                    help="RandomForest trees (default 200).")
    args = ap.parse_args()

    print(f"-> Generating dataset: {args.per_label} examples per label "
          f"({len(LABELS)} labels)")
    samples = build_dataset(per_label=args.per_label, seed=args.seed)

    X = np.array([extract(s["circuit"]) for s in samples], dtype=float)
    y_raw = [s["label"] for s in samples]
    print(f"  - dataset size: {len(samples)} samples, "
          f"{X.shape[1]} features")
    print(f"  - label distribution: {dict(Counter(y_raw))}")

    le = LabelEncoder()
    y = le.fit_transform(y_raw)

    # Stratified 60/20/20 train/val/test.
    X_tr, X_tmp, y_tr, y_tmp = train_test_split(
        X, y, test_size=0.4, random_state=args.seed, stratify=y
    )
    X_val, X_te, y_val, y_te = train_test_split(
        X_tmp, y_tmp, test_size=0.5, random_state=args.seed, stratify=y_tmp
    )
    print(f"  - split: train={len(X_tr)}  val={len(X_val)}  test={len(X_te)}")

    print(f"-> Training RandomForestClassifier "
          f"(n_estimators={args.n_estimators}, class_weight='balanced')")
    clf = RandomForestClassifier(
        n_estimators=args.n_estimators,
        class_weight="balanced",
        n_jobs=-1,
        random_state=args.seed,
    )

    # 5-fold CV on the train set — honest, low-variance estimate.
    cv_scores = cross_val_score(clf, X_tr, y_tr, cv=5,
                                scoring="f1_weighted", n_jobs=-1)
    cv_mean = float(np.mean(cv_scores))
    cv_std  = float(np.std(cv_scores))
    print(f"  - 5-fold CV weighted-F1 (train): "
          f"{cv_mean:.3f} +/- {cv_std:.3f}")

    clf.fit(X_tr, y_tr)

    val_acc = float(clf.score(X_val, y_val))
    test_acc = float(clf.score(X_te,  y_te))
    val_f1   = float(f1_score(y_val, clf.predict(X_val), average="weighted"))
    test_f1  = float(f1_score(y_te,  clf.predict(X_te),  average="weighted"))
    print(f"  - validation accuracy: {val_acc:.3f}   F1: {val_f1:.3f}")
    print(f"  - test       accuracy: {test_acc:.3f}   F1: {test_f1:.3f}")

    print("\n-> Per-class metrics on held-out test set:")
    report = classification_report(
        y_te, clf.predict(X_te),
        target_names=le.classes_,
        output_dict=True, zero_division=0,
    )
    cm = confusion_matrix(y_te, clf.predict(X_te)).tolist()

    # Print the human-readable report alongside the JSON dump.
    print(classification_report(
        y_te, clf.predict(X_te),
        target_names=le.classes_, zero_division=0,
    ))

    metrics = {
        "model":          "RandomForestClassifier",
        "library":        "scikit-learn",
        "n_estimators":   args.n_estimators,
        "seed":           args.seed,
        "n_train":        int(len(X_tr)),
        "n_val":          int(len(X_val)),
        "n_test":         int(len(X_te)),
        "cv_f1_weighted": {"mean": cv_mean, "std": cv_std, "folds": 5},
        "val_accuracy":   val_acc,
        "test_accuracy":  test_acc,
        "val_f1":         val_f1,
        "test_f1":        test_f1,
        "labels":         list(le.classes_),
        "per_class":      report,
        "confusion_matrix": cm,
    }

    # Persist the model + metrics together.
    out = TopologyClassifier()
    out.model         = clf
    out.label_encoder = le
    out.metrics       = metrics
    out.save()
    print(f"\n-> Saved model to: ml_models/saved/topology_classifier.pkl")

    json_path = os.path.join("ml_models", "saved", "topology_metrics.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"-> Saved metrics  to: {json_path}")

    print("\n-> Top 8 feature importances:")
    for f, imp in sorted(
        zip(FEATURE_NAMES, clf.feature_importances_),
        key=lambda p: p[1], reverse=True
    )[:8]:
        print(f"    {f:30s}  {imp:.4f}")


if __name__ == "__main__":
    main()
