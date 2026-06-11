"""
Tests for the Topology Classifier.

These tests cover three concerns:
  1. Feature extraction is deterministic and stable in dimensionality.
  2. The trained model loads cleanly from the pickled artifact.
  3. End-to-end classification on hand-crafted circuits hits the
     expected label with high confidence — not because we trained on
     the same example, but because the structural fingerprint is
     dominant enough to dominate over generator-id noise.

If the model file is missing (CI without training), the e2e tests are
skipped so the suite stays green; the unit tests on features alone
still run.
"""
import os
import pytest

from ml_models.topology_features import FEATURE_NAMES, extract
from ml_models.topology_classifier import TopologyClassifier, MODEL_PATH
from ml_models.topology_dataset import (
    _half_adder_textbook, _half_adder_nand_only,
    _full_adder_textbook, _two_to_one_mux, _sr_latch,
    _d_flip_flop, _n_bit_register, _generic_random,
)


# -- Feature extractor ------------------------------------------------------

def test_extract_returns_fixed_length_vector():
    """Feature length must always equal FEATURE_NAMES — otherwise the
    pickled model would receive a misaligned column vector and produce
    silent garbage. Stable vector length is the load-bearing contract."""
    ha = _half_adder_textbook()
    feats = extract(ha)
    assert len(feats) == len(FEATURE_NAMES)
    assert all(isinstance(v, (int, float)) for v in feats)


def test_extract_empty_circuit():
    """Empty input must not raise — the classifier is called on every
    keystroke, including before the user has placed anything."""
    feats = extract({"gates": [], "wires": []})
    assert len(feats) == len(FEATURE_NAMES)


def test_extract_is_permutation_invariant_in_ids():
    """Re-naming gates must not change the feature vector. Without this
    property the augmentation in training data is wasted: each rename
    would look like a different example."""
    ha_a = _half_adder_textbook()
    ha_b = _half_adder_textbook()
    # Both come from the same generator with different randomised ids.
    assert extract(ha_a) == extract(ha_b)


def test_sr_latch_is_detected_as_cyclic():
    """The SR latch has cross-coupled NANDs — feature 'has_cycle' must
    fire so the model knows this is sequential."""
    feats = extract(_sr_latch())
    has_cycle_idx = FEATURE_NAMES.index("has_cycle")
    assert feats[has_cycle_idx] == 1.0


def test_combinational_flag_negates_for_clocked_circuits():
    feats = extract(_d_flip_flop())
    is_combo_idx = FEATURE_NAMES.index("is_combinational")
    assert feats[is_combo_idx] == 0.0


# -- Trained classifier (e2e) ----------------------------------------------

# Skip the e2e tests if the model isn't pickled in this environment (e.g.
# CI without a training step). The contract: anyone can run
# `python train_topology.py` to regenerate.
_HAS_MODEL = os.path.exists(MODEL_PATH)
skip_if_no_model = pytest.mark.skipif(
    not _HAS_MODEL,
    reason="topology_classifier.pkl not present; run train_topology.py",
)


@pytest.fixture(scope="module")
def clf():
    c = TopologyClassifier()
    assert c.load(), "topology_classifier.pkl failed to load"
    return c


@skip_if_no_model
def test_loads_with_expected_metadata(clf):
    assert clf.is_ready()
    # Metrics from the training run must be persisted so the UI can show
    # them honestly. If this drops, the model card is stale.
    assert clf.metrics, "model card metrics missing from pickle"
    assert "test_accuracy" in clf.metrics
    assert "labels" in clf.metrics


@skip_if_no_model
def test_classifies_textbook_half_adder(clf):
    out = clf.classify(_half_adder_textbook())
    assert out["ready"] is True
    assert out["top"][0][0] == "half_adder"
    assert out["top"][0][1] > 0.5


@skip_if_no_model
def test_classifies_nand_only_half_adder_as_half_adder(clf):
    """This is the headline ML capability: hand rules can't generalise
    across wirings, but the classifier learns the structural fingerprint
    so the NAND-only variant is still recognised."""
    out = clf.classify(_half_adder_nand_only())
    top_labels = [lbl for lbl, _ in out["top"]]
    assert "half_adder" in top_labels, (
        f"NAND-only half adder mis-classified; top picks were: {out['top']}"
    )


@skip_if_no_model
def test_classifies_full_adder(clf):
    out = clf.classify(_full_adder_textbook())
    assert out["top"][0][0] == "full_adder"


@skip_if_no_model
def test_classifies_two_to_one_mux(clf):
    out = clf.classify(_two_to_one_mux())
    assert out["top"][0][0] == "two_to_one_mux"


@skip_if_no_model
def test_classifies_sr_latch(clf):
    out = clf.classify(_sr_latch())
    assert out["top"][0][0] == "sr_latch"


@skip_if_no_model
def test_classifies_n_bit_register(clf):
    out = clf.classify(_n_bit_register(4))
    assert out["top"][0][0] == "n_bit_register"


@skip_if_no_model
def test_classifies_generic_noise_as_generic_or_low_confidence(clf):
    """Random small circuits shouldn't be confidently labelled as any
    canonical type. Either the top pick is 'generic', or no class has
    overwhelming confidence."""
    import random
    random.seed(7)
    for _ in range(5):
        out = clf.classify(_generic_random(min_g=2, max_g=4))
        top_label, top_conf = out["top"][0]
        assert top_label == "generic" or top_conf < 0.8, (
            f"Overconfident on noise circuit: {out['top']}"
        )


@skip_if_no_model
def test_tiny_circuit_returns_generic_low_confidence(clf):
    out = clf.classify({"gates": [{"id": "x", "type": "INPUT"}], "wires": []})
    assert out["top"][0][0] == "generic"


@skip_if_no_model
def test_feature_importance_present(clf):
    imps = clf.feature_importance()
    assert imps and len(imps) == len(FEATURE_NAMES)
    # Most-important features should be sane structural ones.
    top5 = [d["feature"] for d in imps[:5]]
    # At least one of these structural counts should be a top feature.
    assert any(
        f in top5
        for f in ("n_logic", "n_input", "n_output", "depth",
                  "io_balance", "input_to_output_ratio")
    )


# -- Accuracy threshold ----------------------------------------------------

@skip_if_no_model
def test_pinned_test_accuracy_threshold(clf):
    """If a future change degrades classification quality, fail CI early.
    Threshold is intentionally lower than the trained metric so we have
    headroom for noise augmentation later."""
    assert clf.metrics["test_accuracy"] >= 0.85, (
        f"Topology classifier test accuracy dropped to "
        f"{clf.metrics['test_accuracy']} — below the pinned 0.85 floor."
    )
