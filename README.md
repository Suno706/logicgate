# LogicGate

A browser-based digital logic circuit designer with a small set of
trained models for things like fault detection, gate minimization,
and turning plain-English questions into circuits.

Everything runs locally - Flask backend, scikit-learn models, no
external API calls.

## What you can do

- Drag-and-drop logic gates (AND, OR, NOT, NAND, NOR, XOR, XNOR) on a canvas
- Wire them up and simulate the circuit with the built-in simulator
- Save and load circuits as JSON
- Type a boolean expression (e.g. `A and (B or not C)`) and get a circuit back
- Ask a question in plain English ("circuit that's on when exactly two of three switches are up") and get a circuit
- Run analysis on a circuit: fault detection, gate-count optimization,
  minimization, and a full report

## Project layout

```
app.py                    Flask app and API routes
simulator.py              Circuit evaluation
templates/index.html      The UI (single page)
data/                     Training CSVs
ml_models/
  boolean_synth.py        Boolean expression -> gate JSON
  intent_classifier.py    Classifies what the user is asking for
  question_solver.py      Natural-language question -> circuit
  fault_detector.py       Finds bad wiring / unused outputs
  circuit_optimizer.py    Suggests structural improvements
  gate_minimizer.py       Reduces gate count using K-map style logic
  connection_suggester.py Ranks likely next wires
```

## Running it

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000

The first run trains the models from the CSVs in `data/` and caches them
under `ml_models/saved/`. Re-runs load the cached models and start in a
couple of seconds.

## API

The frontend uses these directly:

| Method | Path             | What it does                    |
|--------|------------------|---------------------------------|
| GET    | `/`              | Serves the UI                   |
| POST   | `/simulate`      | Runs the simulator on a circuit |
| POST   | `/save`          | Saves a named circuit           |
| GET    | `/load/<name>`   | Loads a saved circuit           |
| GET    | `/list-circuits` | Lists saved circuits            |

The ML-backed routes live under `/api/`:

| Method | Path                       | What it does                         |
|--------|----------------------------|--------------------------------------|
| POST   | `/api/build/boolean`       | Boolean expression -> circuit JSON   |
| POST   | `/api/build/question`      | NL question -> circuit JSON          |
| POST   | `/api/synthesize`          | Re-synthesise with a gate-set limit  |
| POST   | `/api/suggest/connection`  | Ranks the next wire to add           |
| POST   | `/api/analyze/faults`      | Fault detection                      |
| POST   | `/api/analyze/optimize`    | Suggests optimizations               |
| POST   | `/api/analyze/minimize`    | Gate minimization                    |
| POST   | `/api/analyze/full`        | All of the above in one response     |
| POST   | `/api/ask`                 | Free-form question solver            |
| POST   | `/api/predict`             | Predict circuit output for inputs    |
| GET    | `/api/health`              | Model status                         |

## Notes

- Models are scikit-learn (RandomForest / logistic regression / gradient
  boost depending on the task). Nothing trained on GPUs; all of this fits
  in a few hundred KB of pickled state.
- The boolean synthesizer uses a structural cache so multi-output circuits
  share sub-expressions correctly.
- The intent classifier was added to route free-form `/api/ask` calls to
  the right downstream model.
