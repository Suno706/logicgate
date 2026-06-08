# Architecture & Design Decisions

This document explains *how* and *why* the system is built the way it is.
Use this as your interview-prep reference — every design decision below
is something an interviewer might ask.

## 1. The big picture

```
   ┌────────────┐       HTTP/JSON       ┌────────────────────┐
   │  Browser   │  ◄────────────────►   │  Flask backend     │
   │  (HTML +   │                       │  (app.py)          │
   │   Canvas)  │                       │                    │
   └────────────┘                       │  + ML routes       │
                                        │  + simulator       │
                                        └─────────┬──────────┘
                                                  │
                                                  ▼
                            ┌─────────────────────────────────────┐
                            │       ml_models/                    │
                            │  ┌───────────────────────────────┐  │
                            │  │  question_solver.py           │  │
                            │  │  (NL → circuit JSON router)   │  │
                            │  └─────┬─────────────────────────┘  │
                            │        │                            │
                            │        ▼                            │
                            │  ┌──────────────┬──────────────┐    │
                            │  │ intent_      │ boolean_     │    │
                            │  │ classifier   │ synth        │    │
                            │  │ (TF-IDF+LR)  │ (algorithm)  │    │
                            │  └──────────────┴──────────────┘    │
                            │  ┌──────────────┬──────────────┐    │
                            │  │ fault_       │ circuit_     │    │
                            │  │ detector(RF) │ optimizer(MLP│    │
                            │  └──────────────┴──────────────┘    │
                            │  ┌──────────────┬──────────────┐    │
                            │  │ gate_        │ connection_  │    │
                            │  │ minimizer(RF)│ suggester(GBM│    │
                            │  └──────────────┴──────────────┘    │
                            └─────────────────────────────────────┘
```

## 2. Request lifecycle: a natural-language question

User types **"build a full adder using only NAND"** in the SMART tab.

1. **Frontend** (`templates/index.html`):
   - Captures input, packages as `{"question": "...", "circuit": {...}}`.
   - POSTs to `/api/ask`.

2. **Flask route** (`app.py: ask_question`):
   - Delegates to `question_solver.solve(question, circuit)`.

3. **Intent classification** (`ml_models/intent_classifier.py`):
   - TF-IDF vectorizer (word + char n-grams) extracts text features.
   - Logistic Regression predicts the intent class
     (`build`, `explain`, `output_query`, `fault_check`, `minimize`, …).
   - For "build a full adder using only NAND" → intent = `build`.

4. **Build path** (`question_solver.build_from_text`):
   - **Alias normalization** — fix typos (`adwer` → `adder`), expand
     synonyms (`fulladder` → `full adder`), strip polite openers
     (`could you please…`).
   - **Restriction parser** — pulls out `using only NAND` →
     `target_gates = ["NAND"]`.
   - **Pattern matching** in order:
     1. Parametric N-bit ("4 bit ripple carry adder")
     2. Sequential templates (SR/D/JK flip-flops)
     3. Multi-output known circuits ("full adder", "half adder")
     4. Single-output known circuits ("xor gate")
     5. Bare gate names ("XOR")
     6. Direct boolean expression ("A & B | ~C")
     7. Conditional / mux-style ("A when SEL=0 else NOT B")
     8. Truth-table row spec ("Y=1 for A=0 B=0")
     9. Value-set spec ("ABC reads as 5 or 6")
    10. Free-form natural language ("output is high when both inputs are 1")

5. **Boolean synthesis** (`ml_models/boolean_synth.py`):
   - Parse expression → AST.
   - Apply Quine-McCluskey-style simplification.
   - Translate to target gate set (e.g. `~(A & B)` → NAND tree).
   - Build gate list + wire list with sub-expression sharing.

6. **Response** flows back to frontend, which renders gates on the canvas
   and runs the simulator client-side for live truth-table display.

## 3. Why each ML model is used

> *"Why did you use ML here instead of `if/else`?"* — most common interview
> question. Below is the honest answer for each model.

### intent_classifier (TF-IDF + Logistic Regression)
**Real ML.** User input is open-ended natural language. Rule-based routing
breaks on variations. LR with TF-IDF n-grams generalizes across phrasings.

### fault_detector (Random Forest)
**Partly ML.** Some faults (floating inputs, dangling wires) are
deterministic checks. The ML adds:
- Severity ranking trained on labeled examples.
- Detecting non-obvious patterns (always-0/always-1 outputs from constant
  propagation, unused redundant branches).

### gate_minimizer (Random Forest)
**Mostly heuristic, ML for ranking.** The minimization algorithm is
deterministic. The RF predicts efficiency scores to rank multiple
simplification strategies.

### circuit_optimizer (MLP / multi-layer perceptron)
**ML for scoring.** Given a circuit, predict whether structural changes
(e.g. merging duplicate sub-circuits) would reduce gate count.

### connection_suggester (Gradient Boosting)
**ML for ranking.** Given a partial circuit, rank candidate next wires by
likelihood they're what the user intends. Trained on full-circuit datasets
by masking out the last wire.

### boolean_synth (algorithm, no ML)
**Pure algorithm.** Boolean simplification via Quine-McCluskey, NAND/NOR
synthesis via standard equivalences. ML can't beat the optimal solution
here.

## 4. Key design decisions

### 4.1 Why a hybrid (rule-based + ML) NL parser?

The question_solver uses **regex/pattern rules first**, ML as fallback.

**Pros:**
- Common patterns (`half adder`, `A & B`) are matched in microseconds.
- Predictable behavior — easy to test and debug.
- Adding a new pattern = adding a regex, not retraining.

**Cons:**
- Long file (~2700 lines of patterns).
- Brittle for very unusual phrasings.

**Alternative considered:** Pure LLM (GPT-4 etc.) for NL.
**Why rejected:** Cost, latency, no offline support, harder to test, and
the problem space is bounded (50-ish circuit types) — overkill.

### 4.2 Why Flask, not FastAPI?

Flask was chosen for simplicity. The API is synchronous; we don't need
async. FastAPI would be a strict upgrade for a v2, but Flask:
- Has 10x more tutorials/examples.
- Smaller learning curve.
- Production-stable.

### 4.3 Why sklearn, not PyTorch/TensorFlow?

The problems are small (circuit features fit in <100 dims, datasets
< 10k rows). Random Forests / MLPs in sklearn:
- Train in seconds on CPU.
- Serialize to small pickle files.
- No GPU needed for deployment.

PyTorch/TF would be over-engineering.

### 4.4 Why JSON files, not a database?

Circuits are small (~1KB each), single-user during dev, and we want zero
deployment friction. **For v2 with user accounts, swap to Postgres.**

### 4.5 Why single-page HTML with vanilla JS?

Speed of initial development. The trade-offs:
- ✅ No build step, easy to deploy.
- ✅ One file = easy to share.
- ❌ Hard to maintain at 2700 lines.
- ❌ No type safety.

**Plan: port to React + TypeScript** (tracked in [Roadmap](README.md#roadmap)).

## 5. What I'd do differently (honest)

In interviews, when asked "what would you improve?":

1. **Train on real data instead of synthetic.** The intent classifier
   especially would benefit from real user logs.
2. **Add a feature store / training pipeline.** Currently models are
   retrained from CSV on every fresh install — no versioning.
3. **Split question_solver.py.** 2700 lines in one file is hard to
   maintain. Should be split by pattern category.
4. **Real frontend framework.** Vanilla JS works but doesn't scale.
5. **Persistent storage.** JSON files break with concurrent users.
6. **Observability.** No logging/metrics for which patterns are matched,
   how often models are hit, error rates.

## 6. Performance numbers

On a 2020-era laptop, no GPU:

| Operation | Time |
|-----------|------|
| Load all models on startup | ~2.5s (cached) / ~30s (first train) |
| `boolean_synth.build("A & B \| ~C")` | <1ms |
| `boolean_synth.build("4-bit adder using NAND")` | ~50ms |
| `question_solver.solve("half adder")` | ~10ms |
| `fault_detector.predict(circuit)` | ~5ms |
| `/api/ask` end-to-end | ~30ms |

## 7. Testing strategy

`pytest` covers:
- **Unit:** boolean synth correctness (16 input combos verified against
  Python eval).
- **Unit:** simulator truth tables for all 6 two-input gates.
- **Integration:** question_solver pattern coverage (30+ phrasing tests).
- **Integration:** Flask API endpoints (test client).

`63 tests, all green, run in ~1.5s.`

## 8. Files you should be able to explain

When walking through this project in an interview, focus on these:

| File | What to say about it |
|------|---------------------|
| `app.py` | "Flask routes that wire frontend to ML models." |
| `simulator.py` | "Topological-sort based combinational simulator." |
| `ml_models/boolean_synth.py` | "Boolean expression parser + Quine-McCluskey simplifier + universal-gate translator." |
| `ml_models/question_solver.py` | "Hybrid rule-based + ML natural-language parser." |
| `ml_models/intent_classifier.py` | "TF-IDF + Logistic Regression text classifier." |
| `ml_models/fault_detector.py` | "Random Forest trained to predict circuit defects." |
| `tests/` | "63 tests covering unit and integration paths." |

If you can talk through these 7 files in 5 minutes, you'll pass any
"explain your project" interview round.
