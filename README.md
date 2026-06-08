# LogicGate — Natural-Language Digital Circuit Designer

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-1.x-orange.svg)](https://scikit-learn.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Suno706/logicgate)

> Browser-based digital logic designer with built-in scikit-learn ML, real-time
> multiplayer collaboration, user accounts, and natural-language circuit synthesis.

### Features

- **Real accounts** — username + password (SQLite), or "Sign in with Google" (optional OAuth)
- **Real-time multiplayer** — WebSocket-based, share a 6-character room code, anyone joining sees your canvas live
- **Cloud-saved circuits** — log in from any device, all your work follows you
- **Natural-language synthesis** — "build a 4-bit adder" / "Y=1 when at least 2 of 4 inputs are 1"
- **5 trained scikit-learn models** — fault detection, gate minimization, intent classification, NL→truth-table, connection suggestion
- **Online learning** — thumbs-up/down on Smart panel answers retrains the intent classifier with user feedback at ×5 weight
- **K-Map (2–6 vars), Boolean SOP/POS with Quine-McCluskey, truth table, signal monitor, LED gallery**
- **14 example circuits** in the gallery (half adder → BCD-to-7-segment)

```
"build a full adder using only NAND"     →   14-gate NAND-only adder
"output is 1 when ABC reads as 5 or 6"   →   minterm-enumerated SOP circuit
"4 bit ripple carry adder"               →   parametric N-bit synthesis
"BCD to 7 segment using NOR only"        →   universal-gate translation
```

## Make it a real public website (free, ~5 minutes)

The deploy button at the top of this README provisions everything on
[Render's free tier](https://render.com). You get a real URL like
`https://logicgate-xyz.onrender.com` that works from any phone or laptop.

**Or run it locally** for development only:

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
python app.py        # http://localhost:5000 — your computer only
```

See [DEPLOY_PUBLIC.md](DEPLOY_PUBLIC.md) for step-by-step Render / Fly.io / Railway guides.

---

## Table of Contents

- [Highlights](#highlights)
- [Quick Demo](#quick-demo)
- [How It Works](#how-it-works)
- [Getting Started](#getting-started)
- [Tech Stack & Architecture](#tech-stack--architecture)
- [API Reference](#api-reference)
- [Tests](#tests)
- [Deployment](#deployment)
- [Roadmap](#roadmap)
- [License](#license)

---

## Highlights

- **Natural-language synthesis** — 50+ recognised circuit names, plus minterm
  enumeration (`"exactly two of four are 1"`), value-set parsing
  (`"ABCD is prime"`), conditional logic (`"A when SEL=0 else NOT B"`), and
  N-bit parametric circuits (`"8-bit ripple carry adder"`).
- **Universal-gate translation** — Re-synthesize any boolean function into a
  restricted gate set (`NAND-only`, `NOR-only`, `AOI`).
- **Live simulation** — Click-drag canvas, real-time wire propagation,
  multi-output circuits, sequential templates (SR/D/JK/T flip-flops).
- **5 trained scikit-learn models** — Fault detection, gate minimization,
  optimization scoring, intent classification (TF-IDF + Logistic Regression),
  next-wire suggestion.
- **Structural boolean simplification** — Quine-McCluskey-style minimization
  with sub-expression sharing for multi-output circuits.
- **Robust NL parser** — Stress-tested against 29 messy human queries
  (typos, contractions, slang, engineering notation `A+B+C`, math notation
  `A.B'`) with **97% accuracy**.
- **Pure local** — No external API calls. No LLMs. Everything runs offline.
- **Production-ready packaging** — Docker, Procfile, gunicorn-compatible.

## Quick Demo

```bash
git clone https://github.com/Suno706/logicgate.git
cd logicgate
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

Then type any of these into the **SMART** tab:

| Query | Result |
|-------|--------|
| `half adder` | 2-gate XOR+AND circuit |
| `full adder using only NAND` | 14-NAND-gate adder |
| `output is 1 when input is prime, treat ABCD as 4 bit` | 24-gate primality detector |
| `Y = A when SEL=0 else NOT B when SEL=1` | 5-gate mux-style circuit |
| `4 bit ripple carry adder` | 36-gate parametric adder |
| `BCD to 7 segment` | 7-output decoder with shared sub-expressions |

## How It Works

```
        User types a question
                 │
                 ▼
   ┌─────────────────────────────┐
   │  Intent Classifier          │  TF-IDF + Logistic Regression
   │  (build / explain / ask /   │  Decides routing
   │   minimize / fault-check)   │
   └──────────────┬──────────────┘
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
  ┌─────────────┐     ┌──────────────┐
  │ NL Parser   │     │ Circuit      │
  │ - typos     │     │ Analyzers    │
  │ - aliases   │     │ - fault det. │
  │ - templates │     │ - optimizer  │
  │ - minterms  │     │ - minimizer  │
  └──────┬──────┘     └──────┬───────┘
         ▼                    ▼
  ┌─────────────────────────────────┐
  │  Boolean Synthesizer            │
  │  - Quine-McCluskey simplification│
  │  - Sub-expression sharing       │
  │  - Universal-gate translation   │
  └──────────────┬──────────────────┘
                 ▼
        Gate/Wire JSON
                 │
                 ▼
        HTML5 Canvas renders
        live simulation
```

## Getting Started

### Prerequisites

- Python 3.10+
- pip

### Install & Run

```bash
git clone https://github.com/Suno706/logicgate.git
cd logicgate
pip install -r requirements.txt
python app.py
```

First run trains the ML models from `data/` (one-time, ~30s). Subsequent
runs load cached models in 2-3 seconds.

### Docker

```bash
docker build -t logicgate .
docker run -p 5000:5000 logicgate
```

## Tech Stack & Architecture

| Layer | Tech |
|-------|------|
| Backend | Flask 3.x, gunicorn |
| ML | scikit-learn (RandomForest, GradientBoosting, MLPClassifier, LogisticRegression, TF-IDF) |
| Frontend | Vanilla JS, HTML5 Canvas, CSS Grid |
| Persistence | JSON files (pluggable for DB) |
| Deployment | Docker, Procfile, Heroku/Render/Fly.io compatible |
| Testing | pytest |
| CI | GitHub Actions |

### Project layout

```
logicgate/
├── app.py                      Flask app and API routes
├── simulator.py                Topological circuit evaluation
├── templates/index.html        Single-page UI (HTML5 Canvas)
├── data/                       Training CSVs
├── circuits/                   User-saved circuits (.json)
├── ml_models/
│   ├── boolean_synth.py        Boolean expression → gate JSON
│   ├── intent_classifier.py    TF-IDF + LR text router
│   ├── question_solver.py      NL question → circuit (rule-based + ML)
│   ├── fault_detector.py       RandomForest fault prediction
│   ├── circuit_optimizer.py    MLP optimization scoring
│   ├── gate_minimizer.py       Gate-count efficiency model
│   ├── connection_suggester.py GBM next-wire ranker
│   ├── nl_tt_model.py          NL→truth-table heuristic ML
│   └── saved/                  Pickled trained models
├── tests/                      pytest test suite
├── Dockerfile
├── Procfile                    For Heroku/Render
├── requirements.txt
└── README.md
```

## API Reference

### Frontend-facing (plain paths)

| Method | Path             | Purpose                         |
|--------|------------------|---------------------------------|
| GET    | `/`              | Serves the UI                   |
| POST   | `/simulate`      | Runs simulator on a circuit     |
| POST   | `/save`          | Saves a named circuit           |
| GET    | `/load/<name>`   | Loads a saved circuit           |
| GET    | `/list-circuits` | Lists saved circuits            |

### ML-backed (under `/api/`)

| Method | Path                       | Purpose                              |
|--------|----------------------------|--------------------------------------|
| GET    | `/api/health`              | Service + model status               |
| POST   | `/api/ask`                 | Free-form NL question router         |
| POST   | `/api/build/boolean`       | Boolean expression → circuit         |
| POST   | `/api/build/question`      | NL question → circuit                |
| POST   | `/api/synthesize`          | Re-synthesize with restricted gates  |
| POST   | `/api/suggest/connection`  | Ranks next wire to add               |
| POST   | `/api/analyze/faults`      | Fault detection                      |
| POST   | `/api/analyze/optimize`    | Structural improvement suggestions   |
| POST   | `/api/analyze/minimize`    | Gate minimization                    |
| POST   | `/api/analyze/full`        | All analyses in one response         |
| POST   | `/api/predict`             | ML output prediction                 |

### Example: build a full adder using NAND

```bash
curl -X POST http://localhost:5000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "full adder using only NAND"}'
```

```json
{
  "answer": "Built **full adder** using only NAND — 14 logic gates, 30 wires, 2 outputs.",
  "circuit": { "gates": [...], "wires": [...] },
  "info": { "gate_count": 14, "wire_count": 30, "target_gates": ["NAND"] }
}
```

## Tests

```bash
pip install pytest
pytest -v
```

The test suite covers:
- **Boolean synthesizer** — correct gate counts for AND/OR/NOT, NAND-only,
  NOR-only, complex multi-output circuits.
- **NL parser** — 30+ messy-input queries (typos, contractions, slang,
  engineering notation).
- **Simulator** — truth-table verification for half/full adder, BCD-7-seg,
  multiplexers.
- **API endpoints** — Flask test-client round-trips.

## Deployment

The repo is deploy-ready for:

- **Render**: free tier, just connect the GitHub repo. `gunicorn app:app` via Procfile.
- **Railway / Fly.io**: same Procfile.
- **Heroku**: free dyno gone but paid works out of the box.
- **Self-hosted**: `docker run -p 5000:5000 logicgate`.

## Roadmap

- [ ] Sequential simulation with clock stepping (currently static)
- [ ] Export to Verilog/VHDL
- [ ] User accounts + cloud-saved circuits (Postgres)
- [ ] React frontend (current vanilla JS works but is monolithic)
- [ ] Karnaugh map visualization
- [ ] Real Kaggle-dataset-trained intent classifier (currently synthetic data)

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

- scikit-learn for the ML stack
- Flask for the lean web framework
- The classic "Digital Design" textbooks for the boolean simplification algorithms
