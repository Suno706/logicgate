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

# LogicGate

A browser-based digital logic playground where you can drag gates onto a
canvas, watch signals propagate, see the truth table and K-map update in
real time, and — if you don't want to wire things by hand — type
something like *"4-bit ripple carry adder using only NAND"* and let it
build the circuit for you.

**[▶ Try it live](https://huggingface.co/spaces/sunooooooo/logicgate)** · [GitHub](https://github.com/Suno706/logicgate) · [Architecture notes](ARCHITECTURE.md) · [Model card](docs/model_cards/topology_classifier.md)

[![CI](https://github.com/Suno706/logicgate/actions/workflows/ci.yml/badge.svg)](https://github.com/Suno706/logicgate/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![React 19](https://img.shields.io/badge/react-19-blue.svg)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<!-- TODO: drop a ~15s screen-capture of the canvas → truth-table → Verilog flow here. -->
<!-- ![demo](docs/demo.gif) -->

## Why this exists

Most digital-logic teaching tools fall into one of two camps: either
they're click-heavy schematic editors with no real "understanding" of
the circuit, or they're command-line solvers that hand you a boolean
expression and call it a day. LogicGate tries to sit in the middle —
you can draw, and the tool can read what you drew (and explain it back,
minimize it, or rebuild it from a sentence).

Everything runs **locally** in your browser + a small Python server.
No LLM calls, no API keys, no telemetry. The "smart" parts are
classical scikit-learn models and a Quine–McCluskey synthesiser, not a
language model dressed up as engineering.

## What's actually in it

- **A drag-and-drop circuit editor** with live simulation, wire routing,
  a snap grid, undo/redo, and macro blocks (half-adder, full-adder,
  D-/JK-/T-flip-flop, registers) you can place as a single box or
  expand into primitive gates.
- **Seven side-panel views** that update as you build: properties,
  truth table, K-map (2–6 vars), boolean expression, signal monitor,
  LED gallery, and a SMART panel that takes plain-English questions.
- **A boolean synthesiser** (Quine–McCluskey, with shared sub-expression
  detection for multi-output circuits) that turns a truth table or
  expression into a minimal SOP circuit, optionally restricted to
  NAND-only, NOR-only, or AOI gate sets.
- **A natural-language builder** — phrases like *"half adder"*,
  *"output is 1 when ABCD reads as a prime"*, or *"8-bit ripple carry
  adder using only NAND"* get parsed, classified, and synthesised. The
  intent router is TF-IDF + logistic regression; the actual circuit
  comes from the synthesiser or a curated knowledge base.
- **A topology classifier** — a small RandomForest watches your canvas
  and guesses what canonical circuit you're building (half adder, full
  adder, mux, decoder, latch, flip-flops, N-bit register, or "generic").
  Trained with a 60/20/20 split + 5-fold CV; honest metrics in
  [`ml_models/saved/topology_metrics.json`](ml_models/saved/topology_metrics.json),
  with a full [model card](docs/model_cards/topology_classifier.md).
- **Multiplayer rooms** — WebSocket-based, with presence, host kick,
  and a per-room IP ban list. Useful for classroom demos.
- **Fault analysis** — floating inputs, dangling outputs, feedback
  loops, missing OUTPUT gates, all flagged in the editor.
- **Verilog-2001 export** — turns your gate graph into a synthesisable
  module (with `always @(posedge CLK)` blocks for sequential blocks).
- **A small "Logic Arcade"** — four puzzle games (Signal Maze, Build the
  Table, Override the Mainframe, Canvas Challenge) that share the same
  simulator, mostly because building them was fun.
- **Accounts (optional)** — SQLite-backed username/password, plus
  Google OAuth if you wire credentials. Guest mode otherwise.

```
"build a full adder using only NAND"     →   14-gate NAND-only adder
"output is 1 when ABC reads as 5 or 6"   →   minterm-enumerated SOP circuit
"4 bit ripple carry adder"               →   parametric N-bit synthesis
"BCD to 7 segment using NOR only"        →   universal-gate translation
```

## Running it

The hosted version on [Hugging Face Spaces](https://huggingface.co/spaces/sunooooooo/logicgate)
is the easiest way to try it. If you want to run it on your machine:

```bash
git clone https://github.com/Suno706/logicgate.git
cd logicgate

# backend
pip install -r requirements.txt

# frontend
cd frontend && npm install && npm run build && cd ..

# go
python app.py
# then open http://localhost:5000
```

First start trains the ML models from `data/` (about 30 seconds on a
modern laptop). After that they're cached and boot takes 2–3 seconds.

Or, if you'd rather not deal with Python on your machine:

```bash
docker build -t logicgate .
docker run -p 5000:5000 logicgate
```

## How the SMART panel works under the hood

```
        User types a question
                 │
                 ▼
   ┌─────────────────────────────┐
   │  Intent classifier          │   TF-IDF + Logistic Regression
   │  (build / explain / ask /   │   decides where to route the query
   │   minimize / fault-check)   │
   └──────────────┬──────────────┘
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
  ┌─────────────┐     ┌──────────────┐
  │ NL parser   │     │ Circuit      │
  │ - typos     │     │ analysers    │
  │ - aliases   │     │ - fault det. │
  │ - templates │     │ - optimizer  │
  │ - minterms  │     │ - minimizer  │
  └──────┬──────┘     └──────┬───────┘
         ▼                    ▼
  ┌─────────────────────────────────┐
  │  Boolean synthesiser            │
  │  - Quine–McCluskey              │
  │  - Sub-expression sharing       │
  │  - Universal-gate translation   │
  └──────────────┬──────────────────┘
                 ▼
        Gate / wire JSON
                 │
                 ▼
        Canvas renders + simulates
```

## What's under the hood

| Layer | Tech |
|-------|------|
| Backend | Flask 3, gunicorn, Flask-SocketIO |
| ML | scikit-learn (RandomForest, GradientBoosting, MLP, Logistic Regression, TF-IDF) |
| Frontend | React 19 + TypeScript, Vite, Tailwind, HTML5 Canvas |
| Storage | SQLite (accounts, saved circuits, room state) |
| Realtime | WebSocket rooms with presence, host kick, IP-ban list |
| Deployment | Docker / Procfile / Hugging Face Spaces / Render / Fly.io |
| Testing | pytest (91 tests, ≥55% coverage gate) |
| CI | GitHub Actions: pytest+coverage, ruff, tsc, eslint, vite build, docker |

### Where things live

```
logicgate/
├── app.py                      Flask app + API routes (CORS, rate limits)
├── rate_limit.py               In-memory per-IP / per-user token bucket
├── auth.py                     Username/password + Google OAuth (Authlib)
├── realtime.py                 Flask-SocketIO rooms (presence, kick, ban)
├── db.py                       SQLite schema + DAO (accounts, circuits, rooms)
├── simulator.py                Topological circuit evaluator (Kahn's algorithm)
├── data/                       Training CSVs
├── circuits/                   Per-session saved circuits (.json)
├── docs/model_cards/           Honest model cards
├── ml_models/
│   ├── boolean_synth.py        Quine–McCluskey boolean → gate JSON
│   ├── verilog_export.py       Gate JSON → Verilog-2001 module
│   ├── intent_classifier.py    TF-IDF + LR text router
│   ├── question_solver.py      NL question → circuit (rules + ML)
│   ├── topology_classifier.py  RandomForest, 34 structural features
│   ├── fault_detector.py       Rule-based + auxiliary MLP
│   ├── circuit_optimizer.py    Structural analysis + MLP difficulty bucket
│   ├── gate_minimizer.py       SOP minimisation
│   ├── connection_suggester.py Empirical P(src | dst, pin) table
│   └── saved/                  Pickled trained models + metrics JSON
├── frontend/                   React + TypeScript + Vite SPA
│   ├── src/components/         Canvas, Header, Sidebar, RightPanel, …
│   ├── src/panels/             PROPS, TRUTH, K-MAP, BOOL, SIG, LEDs, SMART
│   ├── src/game/               Logic Arcade (Maze, Override, Canvas Challenge)
│   └── src/store.ts            Circuit state + undo/redo
├── tests/                      pytest suite
├── Dockerfile · Procfile · fly.toml · render.yaml
├── pyproject.toml              ruff config (CI lint gate)
├── requirements.txt
└── README.md
```

### How fast is the synthesiser?

Numbers from random truth tables on a Ryzen 5 5600U, single thread:

| Inputs | Truth-table rows | Synth time | Output gates |
|-------:|-----------------:|-----------:|-------------:|
|      4 |               16 |       <1 ms |           ~8 |
|      6 |               64 |        2 ms |          ~22 |
|      8 |              256 |       14 ms |          ~55 |
|     10 |             1024 |      180 ms |         ~140 |
|     12 |             4096 |     2300 ms |         ~360 |

Quine–McCluskey is exponential in the worst case, which is why the SMART
panel caps interactive synthesis at 12 inputs — past that, free-tier
dynos start hitting memory ceilings. See the
[model card](docs/model_cards/topology_classifier.md) for the ML side.

## API quick reference

### Plain routes (used by the UI directly)

| Method | Path             | Purpose                         |
|--------|------------------|---------------------------------|
| GET    | `/`              | Serves the UI                   |
| POST   | `/simulate`      | Runs the simulator              |
| POST   | `/save`          | Saves a named circuit           |
| GET    | `/load/<name>`   | Loads a saved circuit           |
| GET    | `/list-circuits` | Lists saved circuits            |

### Smart routes (under `/api/`)

| Method | Path                       | Purpose                              |
|--------|----------------------------|--------------------------------------|
| GET    | `/api/health`              | Service + model status               |
| POST   | `/api/ask`                 | Free-form NL question router         |
| POST   | `/api/build/boolean`       | Boolean expression → circuit         |
| POST   | `/api/build/question`      | NL question → circuit                |
| POST   | `/api/synthesize`          | Re-synthesise with restricted gates  |
| POST   | `/api/suggest/connection`  | Ranks next wire to add               |
| POST   | `/api/analyze/faults`      | Fault detection                      |
| POST   | `/api/analyze/optimize`    | Structural improvement suggestions   |
| POST   | `/api/analyze/minimize`    | Gate minimisation                    |
| POST   | `/api/analyze/full`        | All analyses in one response         |
| POST   | `/api/predict`             | ML output prediction                 |
| POST   | `/api/export/verilog`      | Circuit → Verilog-2001               |
| POST   | `/api/topology/classify`   | RandomForest topology label + probs  |

#### Example — full adder using only NAND

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

The suite covers the boolean synthesiser (correctness across AND/OR/NOT,
NAND-only, NOR-only, multi-output), the NL parser (~30 messy queries
with typos, contractions, engineering notation), the simulator
(truth-table verification for half/full adder, BCD-7-seg, MUXes), and
the Flask API endpoints.

## Deployment

The repo ships ready for Render, Railway, Fly.io, Hugging Face Spaces,
or anything that runs Docker. The production deploy lives at
[huggingface.co/spaces/sunooooooo/logicgate](https://huggingface.co/spaces/sunooooooo/logicgate)
and uses the Docker SDK. See [DEPLOY.md](DEPLOY.md) for the step-by-step.

## Roadmap

- [x] React + TypeScript frontend (Vite + Tailwind)
- [x] K-map panel with Quine–McCluskey grouping
- [x] Accounts + cloud-saved circuits (SQLite + Google OAuth)
- [x] Verilog-2001 export
- [x] Multiplayer rooms (presence, host kick, IP ban)
- [x] Rate limiting + session gating on all mutating endpoints
- [ ] **Sequential simulation with clock stepping** — the Verilog export
      already emits clocked blocks for D-/JK-/T-FFs and REG4, but the
      in-browser simulator is still one-shot. This is the next big rock.
- [ ] VHDL export (the gate graph is the same; mostly a translation layer)
- [ ] Postgres backend behind the same DAO, for multi-worker deploys
- [ ] Replace the synthetic intent dataset with real student queries

## License

MIT — see [LICENSE](LICENSE).

## Thanks

To scikit-learn for the ML stack, to Flask for being un-opinionated when
it needed to be, and to the classic *Digital Design* textbooks for the
boolean simplification algorithms that this project leans on heavily.
