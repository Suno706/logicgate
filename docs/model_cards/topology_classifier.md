# Model Card — Circuit Topology Classifier

> **What it does:** Given a digital circuit graph, predicts which canonical
> topology the user is building (half adder, full adder, multiplexer,
> decoder, latch, flip-flop, register, or generic).

## Intended use

Live feedback inside the LogicGate editor. As the user drags gates and
draws wires on the canvas, the front-end calls `/api/topology/classify`
on every change (debounced ~350 ms). The result powers the *"Looks like
Half Adder · 87%"* chip at the bottom of the canvas.

The model is intended as a confidence-building affordance for learners
("you're on the right track to a full adder"), **not** as an authoritative
grader. It will be wrong sometimes, especially on unusual wirings or
partial circuits.

## Out-of-scope use

- **Not** a substitute for formal correctness checks. A circuit can be
  classified as a "full_adder" by topology and still simulate to the
  wrong truth table. Always verify with the simulator (which is
  algorithmic, not ML).
- **Not** for security / authentication decisions.
- **Not** for grading student submissions where partial credit matters
  — use a truth-table equivalence check instead.

## Architecture

- **Model:** `sklearn.ensemble.RandomForestClassifier`
- **Trees:** 200 (`n_estimators=200`)
- **Class weights:** `"balanced"` so rare circuit types don't get crushed
  by `generic`.
- **Feature vector length:** 34 (see [`topology_features.py`](../../ml_models/topology_features.py))

## Feature set

The feature extractor reduces a circuit graph to a fixed-length numeric
vector covering:

- **Size / shape:** gate count, wire count, logic-gate count, input
  count, output count, wire-to-gate ratio, I/O balance.
- **Per-gate-type fractions:** what fraction of logic gates are AND, OR,
  NOT, NAND, NOR, XOR, XNOR, BUF.
- **Macro indicators (0/1):** presence of HA, FA, MUX2, MUX4, DFF, TFF,
  JKFF, SR-latch primitives.
- **Connectivity stats:** max/avg fan-in, max/avg fan-out,
  number of unconnected logic gates.
- **Depth & cycles:** longest topological path length, has-cycle flag.
- **Derived flags:** XOR/XNOR present, NAND/NOR present, fully
  combinational, input-to-output ratio.

Crucially, **features are permutation-invariant in gate IDs**: renaming
gates does not change the feature vector. This is what allows a NAND-only
half adder and a textbook XOR+AND half adder — same intent, different
ids and wirings — to land in the same region of feature space.

## Labels

```
half_adder, full_adder,
two_to_one_mux, four_to_one_mux,
two_to_four_decoder,
d_flip_flop, jk_flip_flop, sr_latch,
n_bit_register,
generic
```

`generic` is a deliberate negative class for random small circuits that
don't fit any canonical type. Without it, the model would be biased to
always pick *some* canonical label on arbitrary input.

## Training data

**Synthetic, programmatically generated.** Each label has 1–2 generator
functions in [`topology_dataset.py`](../../ml_models/topology_dataset.py)
that emit a canonical version of that circuit, with randomised gate IDs
for variation. Default dataset: 200 samples per label × 10 labels = 2,000.

Sample generators include both textbook and alternate-wiring variants
(e.g. a half adder with XOR+AND and another built only from NAND gates)
so the model learns the structural fingerprint, not a single recipe.

**Reproducibility:** `python train_topology.py --seed 0 --per-label 200`
deterministically reproduces the dataset and metrics.

## Training procedure

- Stratified 60 / 20 / 20 split (train / validation / test).
- 5-fold cross-validation on the training set (weighted F1).
- Final fit on the full training set, evaluated on validation, then
  reported on the held-out test set.
- Model + metrics persisted together in
  `ml_models/saved/topology_classifier.pkl`.

## Metrics (default seed=0, per-label=200)

| Metric                       | Value |
| ---------------------------- | ----- |
| Training set size            | 1,200 |
| Validation set size          | 400   |
| Held-out test set size       | 400   |
| 5-fold CV weighted F1 (train)| 1.000 |
| Validation accuracy          | 1.000 |
| **Held-out test accuracy**   | **1.000** |
| Held-out test weighted F1    | 1.000 |

> **Honest caveat:** these scores are on **synthetic data generated from
> the same generators we trained on**. The synthetic dataset is internally
> diverse enough to test ID-permutation invariance and the NAND-only-vs-XOR
> generalisation (see [`tests/test_topology_classifier.py`](../../tests/test_topology_classifier.py)),
> but real user circuits will be noisier, partially built, and sometimes
> intentionally wrong. Expect lower accuracy in the wild — probably in the
> 0.70–0.85 band depending on partial-build noise.

## Per-class metrics (test set)

All ten classes report precision = recall = F1 = 1.00 on the synthetic
test set. The pinned CI threshold in
[`tests/test_topology_classifier.py`](../../tests/test_topology_classifier.py)
is `test_accuracy >= 0.85` to leave headroom for future noise
augmentation without breaking the build.

## Top feature importances (default seed)

| Feature | Importance |
| --- | ---: |
| `io_balance` | 0.102 |
| `input_to_output_ratio` | 0.089 |
| `n_output` | 0.083 |
| `depth` | 0.055 |
| `n_input` | 0.053 |
| `n_logic` | 0.053 |
| `n_gates` | 0.052 |
| `is_combinational` | 0.051 |

I/O ratios dominate, which matches intuition: a half adder has 2 inputs
and 2 outputs; a 4:1 mux has 6 and 1; a register has many of each. The
classifier could be made more robust by adding adjacency-pattern features
(e.g. how often XOR feeds AND), at the cost of slower extraction.

## Ethical considerations

- Synthetic data only — no user-generated content was used in training,
  so no consent / PII concerns.
- The model is local — no data leaves the user's browser unless they
  explicitly use a collaborative room.
- Misclassification on student work could be discouraging. The chip is
  presented as *"looks like"* with explicit confidence, not as a grade.

## How to retrain

```bash
python train_topology.py --per-label 200 --seed 0
# Optional knobs:
python train_topology.py --per-label 400 --n-estimators 500 --seed 42
```

Adding a new label:

1. Add a generator function in `ml_models/topology_dataset.py`.
2. Append the label name to `LABELS`.
3. Map the generator(s) under that key in `_GENERATORS`.
4. Add a friendly display name in `frontend/src/components/TopologyChip.tsx`.
5. Re-run `python train_topology.py`.

## Versioning

| Version | Date       | Notes |
| ------- | ---------- | ----- |
| 1.0     | 2026-06-11 | Initial release — 10 labels, 34 features, RandomForest n=200. |
