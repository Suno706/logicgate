---
title: LogicGate
emoji: 🔌
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# LogicGate — Browser-based Digital Logic Designer

**[▶ Try the live demo](https://huggingface.co/spaces/sunooooooo/logicgate)** · [Source](https://github.com/Suno706/logicgate) · [Architecture](ARCHITECTURE.md) · [Model card](docs/model_cards/topology_classifier.md)

[![CI](https://github.com/Suno706/logicgate/actions/workflows/ci.yml/badge.svg)](https://github.com/Suno706/logicgate/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![React 18](https://img.shields.io/badge/react-18-blue.svg)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<!-- TODO: drop a ~15s screen-capture of the canvas → truth-table → Verilog flow here. -->
<!-- ![demo](docs/demo.gif) -->

> A web circuit editor with **Quine-McCluskey boolean synthesis**, real-time
> multiplayer rooms, a natural-language builder, fault analysis, and a small
> logic-puzzle arcade. The headline engineering work is the synthesiser —
> it produces provably-minimal SOP circuits from truth tables or boolean
> expressions for up to 12 variables.

### What it actually does

- **Live circuit topology classifier (ML)** — a `RandomForestClassifier`
  trained on 34 structural features watches your canvas in real time and
  predicts which canonical circuit you're building (half adder, full
  adder, 4:1 mux, decoder, latch, D-/JK-flip-flop, N-bit register, or
  generic). Trained with stratified 60/20/20 split + 5-fold CV; metrics,
  feature importances and confusion matrix are persisted in
  [`ml_models/saved/topology_metrics.json`](ml_models/saved/topology_metrics.json).
  Full [model card](docs/model_cards/topology_classifier.md) included.
- **Quine-McCluskey synthesiser** — give it a truth table or a boolean
  expression and it returns a minimal-SOP circuit, optionally restricted
  to a target gate set (e.g. NAND-only, NOR-only) or composed from
  macro blocks (HA, FA, D-FF, MUX2)
- **Drag-and-drop editor with live simulation** — gates, wires, snap grid,
  truth table, K-Map (2–6 vars), boolean expression view, signal monitor,
  LED gallery
- **Real-time collaboration** — WebSocket rooms, presence, host can kick
  with IP-based ban list per room
- **Natural-language builder** — short phrases like "4 bit ripple carry adder"
  or "Y=1 when at least 2 of 4 inputs are 1" are parsed into circuits.
  An intent router (TF-IDF + LogisticRegression) picks the handler; the
  actual circuit comes from Quine-McCluskey or a curated knowledge base
- **Rule-based fault analysis** — floating inputs, dangling outputs,
  feedback loops, missing OUTPUT gates
- **Logic Arcade** — four procedural games that share the simulator:
  Signal Maze, Build the Table, Override the Mainframe, and a Canvas
  Challenge that uses the real editor as the playfield
- **Accounts** — optional SQLite-backed username/password (Google OAuth
  too if you wire credentials), or guest mode with browser-local storage

```
"build a full adder using only NAND"     →   14-gate NAND-only adder
"output is 1 when ABC reads as 5 or 6"   →   minterm-enumerated SOP circuit
"4 bit ripple carry adder"               →   parametric N-bit synthesis
"BCD to 7 segment using NOR only"        →   universal-gate translation
```

## Make it a real public website (free, ~5 minutes)

The repo ships with `render.yaml`, `fly.toml`, `Procfile`, and a `Dockerfile`
— pick whichever host you prefer. The production deploy at
[huggingface.co/spaces/sunooooooo/logicgate](https://huggingface.co/spaces/sunooooooo/logicgate)
uses the Docker SDK (see [DEPLOY.md](DEPLOY.md)).

**Or run it locally** for development only:

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
python app.py        # http://localhost:5000 — your computer only
```

Production runs on [HuggingFace Spaces](https://huggingface.co/spaces/sunooooooo/logicgate). See [DEPLOY.md](DEPLOY.md) for the Docker SDK setup.

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
| Backend | Flask 3.x, gunicorn, Flask-SocketIO |
| ML | scikit-learn (RandomForest, GradientBoosting, MLPClassifier, LogisticRegression, TF-IDF) |
| Frontend | React 18 + TypeScript, Vite, Tailwind, HTML5 Canvas, Zustand |
| Persistence | SQLite (auth + saved circuits + room state) |
| Realtime | WebSocket rooms with presence, host kick, IP-ban list |
| Deployment | Docker, Procfile, HuggingFace Spaces / Render / Fly.io / Railway |
| Testing | pytest (91 tests, coverage gate ≥55%) |
| CI | GitHub Actions: pytest+coverage, ruff, tsc, eslint, vite build, docker |

### Project layout

```
logicgate/
├── app.py                      Flask app + API routes (CORS, rate limits)
├── rate_limit.py               In-memory per-IP/per-user token bucket
├── auth.py                     Username/password + Google OAuth (Authlib)
├── realtime.py                 Flask-SocketIO rooms (presence, kick, ban)
├── db.py                       SQLite schema + DAO (accounts, circuits, rooms)
├── simulator.py                Topological circuit evaluator (Kahn's algorithm)
├── data/                       Training CSVs
├── circuits/                   Per-session saved circuits (.json)
├── docs/model_cards/           Honest model cards (topology classifier etc.)
├── ml_models/
│   ├── boolean_synth.py        Quine-McCluskey boolean → gate JSON
│   ├── verilog_export.py       Gate JSON → synthesizable Verilog-2001 module
│   ├── intent_classifier.py    TF-IDF + LR text router
│   ├── question_solver.py      NL question → circuit (rule-based + ML)
│   ├── topology_classifier.py  RandomForest, 34 structural features
│   ├── fault_detector.py       Rule-based + auxiliary MLP
│   ├── circuit_optimizer.py    Structural analysis + MLP difficulty bucket
│   ├── gate_minimizer.py       SOP minimization
│   ├── connection_suggester.py Empirical P(src|dst,pin) table
│   └── saved/                  Pickled trained models + metrics JSON
├── frontend/                   React + TypeScript + Vite SPA
│   ├── src/components/         Canvas, Header, Sidebar, RightPanel, …
│   ├── src/panels/             PROPS, TRUTH, K-MAP, BOOL, SIG, LEDs, SMART
│   ├── src/game/               Logic Arcade (Maze, Override, Canvas Challenge)
│   └── src/store.ts            Zustand circuit state + undo/redo
├── tests/                      pytest suite (boolean synth, NL stress,
│                               simulator, API, topology, Verilog, rate limit)
├── Dockerfile · Procfile · fly.toml · render.yaml
├── pyproject.toml              ruff config (CI lint gate)
├── requirements.txt
└── README.md
```

### Performance — Quine-McCluskey synthesizer

| Inputs (n) | Truth-table rows | Wall time (synth, ms) | Output gates |
|-----------:|-----------------:|----------------------:|-------------:|
|          4 |               16 |                    <1 |           ~8 |
|          6 |               64 |                     2 |          ~22 |
|          8 |              256 |                    14 |          ~55 |
|         10 |             1024 |                   180 |         ~140 |
|         12 |             4096 |                  2300 |         ~360 |

Numbers from random truth tables on a Ryzen 5 5600U, single thread.
QM is exponential in the worst case (≥13 vars hits memory ceilings on
free-tier dynos), which is why the SMART panel caps interactive synthesis
at 12 inputs. See [docs/model_cards/topology_classifier.md](docs/model_cards/topology_classifier.md)
for a deeper writeup of the ML side.

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
| POST   | `/api/export/verilog`      | Circuit → synthesizable Verilog-2001 |
| POST   | `/api/topology/classify`   | RandomForest topology label + probs  |

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

- [x] React + TypeScript frontend (Vite + Tailwind + Zustand)
- [x] K-Map visualization (panel with Quine-McCluskey grouping)
- [x] User accounts + cloud-saved circuits (SQLite + Google OAuth)
- [x] Verilog-2001 export (`/api/export/verilog`, Header → **Verilog** button)
- [x] Real-time multiplayer rooms (WebSocket presence, host kick, IP ban)
- [x] Rate limiting + session gating on all mutating endpoints
- [ ] **Sequential simulation with clock stepping** — engine + timing-diagram
      panel. The Verilog export already emits `always @(posedge CLK)` blocks
      for D-/JK-/T-FFs + REG4, but the in-browser simulator is still one-shot.
- [ ] VHDL export (Verilog ships first; VHDL maps the same gate graph)
- [ ] Postgres backend behind the same DAO (`db.py`) for multi-worker deploys
- [ ] Real Kaggle-dataset-trained intent classifier (currently synthetic data)

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

- scikit-learn for the ML stack
- Flask for the lean web framework
- The classic "Digital Design" textbooks for the boolean simplification algorithms
