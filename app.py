"""
Logic Gate Designer  -  backend API.

Pure Python + scikit-learn ML. No LLM, no external API calls.

Routes are split in two groups:

  Plain routes (called directly by the frontend in templates/index.html):
    GET  /                         -> serves the UI
    POST /simulate                 -> runs the circuit simulator
    POST /save                     -> saves a named circuit
    GET  /load/<name>              -> loads a named circuit
    GET  /list-circuits            -> lists all saved circuits

  ML routes (called when the user wants intelligent help):
    GET  /api/health
    POST /api/analyze/faults
    POST /api/analyze/optimize
    POST /api/analyze/minimize
    POST /api/analyze/full
    POST /api/ask
    POST /api/predict
    POST /api/build/boolean        -> boolean expression -> gate JSON
    POST /api/build/question       -> natural-language question -> gate JSON
    POST /api/synthesize           -> re-synthesise using a restricted gate set
    POST /api/suggest/connection   -> ML-ranked next wire suggestions
"""

from flask import Flask, request, jsonify, send_from_directory

# Real-time multiplayer + auth + SQLite persistence
from realtime import init_socketio
from auth     import init_auth, bp as auth_bp, current_user
import db
from flask_cors import CORS
import json, os, traceback
from datetime import datetime

from simulator import simulate_circuit, validate_circuit

from ml_models.fault_detector       import FaultDetector
from ml_models.circuit_optimizer    import CircuitOptimizer
from ml_models.gate_minimizer       import GateMinimizer
from ml_models.question_solver      import QuestionSolver
from ml_models.boolean_synth        import (
    BooleanSynthesizer, BooleanParseError
)
from ml_models.connection_suggester import ConnectionSuggester

# Serve the Vite/React build from frontend/dist.
_DIST = os.path.join(os.path.dirname(__file__), 'frontend', 'dist')

app = Flask(__name__)
CORS(app, supports_credentials=True)

# Production session cookie settings — required so login persists across
# devices when served over HTTPS. In dev (FLASK_ENV != "production") we
# relax these so http://localhost:5000 still works.
_IS_PROD = os.environ.get("FLASK_ENV", "").lower() == "production"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",      # Lax works for first-party OAuth redirects
    SESSION_COOKIE_SECURE=_IS_PROD,     # Secure only under HTTPS
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,   # 30 days
)

# OAuth (no-op when env vars are missing)
init_auth(app)
app.register_blueprint(auth_bp)

# Real-time collaboration via WebSocket
socketio = init_socketio(app)

# ML models are heavy on first boot (training from CSV can take 1-3 min on
# slow free-tier CPUs). To keep Render's port-bind health check happy we
# initialize lazily: stubs first, then a background thread swaps in the real
# objects. ML routes return 503 until training finishes.
import threading

fault_detector       = None
circuit_optimizer    = None
gate_minimizer       = None
boolean_synth        = None
connection_suggester = None
question_solver      = None
_ml_ready            = False

def _load_ml_models():
    global fault_detector, circuit_optimizer, gate_minimizer
    global boolean_synth, connection_suggester, question_solver, _ml_ready
    print("Loading ML models in background...")
    fault_detector       = FaultDetector()
    circuit_optimizer    = CircuitOptimizer()
    gate_minimizer       = GateMinimizer()
    boolean_synth        = BooleanSynthesizer()
    connection_suggester = ConnectionSuggester()
    question_solver      = QuestionSolver(
        fault_detector=fault_detector,
        gate_minimizer=gate_minimizer,
        boolean_synth=boolean_synth,
    )
    _ml_ready = True
    print("All ML models ready.")

import sys
if "pytest" in sys.modules or os.environ.get("LOGICGATE_SYNC_ML") == "1":
    # In tests we want deterministic state, not "warming up" 503s.
    _load_ml_models()
else:
    threading.Thread(target=_load_ml_models, daemon=True).start()

CIRCUITS_DIR = 'circuits'
os.makedirs(CIRCUITS_DIR, exist_ok=True)

# Bring the SQLite schema up — no-op if already created.
db.get_db()
# Migrate any old filesystem-based saved circuits into the DB on first run.
_migrated = db.migrate_filesystem_circuits(CIRCUITS_DIR)
if _migrated:
    print(f"[db] Migrated {_migrated} filesystem circuits into SQLite.")


# -- helpers --------------------------------------------------------------------

def _safe_name(name: str) -> str:
    return ''.join(c for c in (name or 'circuit')
                   if c.isalnum() or c in ' -_').strip() or 'circuit'


def _session_id() -> str:
    """
    Returns the caller's session id. Resolution order:
      1. The logged-in Google user's `id` (highest authority — survives across
         devices and overrides any header the client might send).
      2. The X-Session-Id header (used by guest / named users).
      3.'default' (curl / CI / no-header requests).
    Sanitized so it can be used as a folder name.
    """
    u = current_user()
    if u and u.get('id'):
        raw = u['id']
    else:
        raw = request.headers.get('X-Session-Id', 'default')
    sid = ''.join(c for c in raw if c.isalnum() or c in '_-')[:64]
    return sid or 'default'


def _session_dir(sid: str = None) -> str:
    """Per-session sub-folder under circuits/. Created on demand."""
    sid = sid or _session_id()
    # 'examples' is reserved for the shared examples gallery.
    if sid == 'examples':
        sid = 'default'
    d = os.path.join(CIRCUITS_DIR, sid)
    os.makedirs(d, exist_ok=True)
    return d


def _err(message, code=400, exc=None):
    if exc is not None:
        traceback.print_exc()
    return jsonify({'status': 'error', 'success': False, 'message': str(message)}), code


def _ml_guard():
    """Return a 503 response if ML models haven't finished loading yet."""
    if not _ml_ready:
        return jsonify({
            'status': 'warming_up',
            'message': 'ML models are still loading on first boot. Try again in ~30 seconds.',
        }), 503
    return None


# -- UI -------------------------------------------------------------------------

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def index(path=''):
    """
    Serve the React SPA from frontend/dist. API routes are registered first
    so they take priority over this catch-all.
    """
    if not os.path.isdir(_DIST):
        return jsonify({
            'error': 'React frontend not built. Run `npm run build` in frontend/.'
        }), 500
    target = os.path.join(_DIST, path)
    if path and os.path.isfile(target):
        return send_from_directory(_DIST, path)
    # SPA fallback: always serve index.html so React Router works.
    return send_from_directory(_DIST, 'index.html')


# -- Simulation (frontend-facing) -----------------------------------------------

@app.route('/simulate', methods=['POST'])
def simulate():
    """
    Body: {gates:[{id,type,value?}], wires:[{from_gate,to_gate,from_pin,to_pin}]}
    Returns: {success: true, outputs: {gate_id: 0|1}, warnings: [...]}
    """
    try:
        data  = request.get_json(silent=True) or {}
        gates = data.get('gates', [])
        wires = data.get('wires', [])

        ok, errors, warnings = validate_circuit(gates, wires)
        if not ok:
            return jsonify({'success': False, 'error': '; '.join(errors),
                            'warnings': warnings}), 400

        outputs = simulate_circuit(gates, wires)
        return jsonify({'success': True, 'outputs': outputs,
                        'warnings': warnings})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# -- Save / Load / List (frontend-facing, plain paths) --------------------------

@app.route('/save', methods=['POST'])
def save_short():
    try:
        data  = request.get_json(silent=True) or {}
        name  = _safe_name(data.get('name', 'circuit'))
        gates = data.get('gates', [])
        wires = data.get('wires', [])
        db.save_circuit(_session_id(), name, gates, wires)
        return jsonify({'success': True, 'message': f'Saved: {name}'})
    except Exception as e:
        return _err(e, exc=e)


@app.route('/load/<name>', methods=['GET'])
def load_short(name):
    try:
        name = _safe_name(name)
        # First try the caller's own circuits, then the shared examples folder.
        circuit = db.load_circuit(_session_id(), name)
        if circuit is None:
            ex_path = os.path.join(CIRCUITS_DIR, 'examples', f"{name}.json")
            if os.path.exists(ex_path):
                with open(ex_path) as f:
                    ex_data = json.load(f)
                circuit = {'gates': ex_data.get('gates', []),
                           'wires': ex_data.get('wires', [])}
        if circuit is None:
            return jsonify({'success': False, 'error': f'Not found: {name}'}), 404
        return jsonify({'success': True, 'circuit': {
            'gates': circuit['gates'], 'wires': circuit['wires'],
        }, 'name': name})
    except Exception as e:
        return _err(e, exc=e)


@app.route('/list-circuits', methods=['GET'])
def list_short():
    try:
        my_names = db.list_circuits(_session_id())
        ex_dir   = os.path.join(CIRCUITS_DIR, 'examples')
        examples = sorted([f[:-5] for f in os.listdir(ex_dir) if f.endswith('.json')]) \
                   if os.path.isdir(ex_dir) else []
        return jsonify({
            'success':  True,
            'circuits': my_names,         # back-compat
            'mine':     my_names,
            'examples': examples,
        })
    except Exception as e:
        return _err(e, exc=e)


# ─── Room creation / lookup ─────────────────────────────────────────────────

@app.route('/api/rooms/new', methods=['POST'])
def room_new():
    """Auto-generate a 6-character room code and an owner_token. The token is
    returned ONCE and the client must store it to be recognized as host on
    subsequent calls (the session_id alone isn't enough for guests because
    setRoom() in the client rewrites it to 'room_<code>')."""
    try:
        sid = _session_id()
        code, token = db.generate_room_code(owner_session=sid)
        return jsonify({'success': True, 'code': code,
                        'url': f'/?room={code}',
                        'is_owner': True,
                        'owner_token': token})
    except Exception as e:
        return _err(e, exc=e)


def _is_room_owner(code: str) -> bool:
    """Owner check that accepts EITHER a matching session_id OR a valid
    X-Owner-Token header. The token path lets guest creators stay
    recognized after setRoom() rewrites their session_id."""
    if db.get_room_owner(code) == _session_id():
        return True
    tok = request.headers.get('X-Owner-Token', '').strip()
    if tok and db.verify_owner_token(code, tok):
        return True
    return False


@app.route('/api/rooms/<code>', methods=['GET'])
def room_info(code):
    try:
        code = ''.join(c for c in code.upper() if c.isalnum())[:12]
        info = db.get_room(code)
        if not info:
            return jsonify({'exists': False, 'code': code})
        is_owner = _is_room_owner(code)
        max_users = db.get_room_max_users(code)
        return jsonify({'exists': True, 'is_owner': is_owner,
                        'max_users': max_users, **info})
    except Exception as e:
        return _err(e, exc=e)


@app.route('/api/rooms/<code>/config', methods=['POST'])
def room_config(code):
    """Owner-only: update room settings.
    Body: {max_users: int}"""
    try:
        code = ''.join(c for c in code.upper() if c.isalnum())[:12]
        data = request.get_json(silent=True) or {}
        max_users = data.get('max_users')
        if max_users is None:
            return _err('Missing max_users', 400)
        try:
            max_users = int(max_users)
        except (TypeError, ValueError):
            return _err('max_users must be an integer', 400)
        if max_users < 2 or max_users > 100:
            return _err('max_users must be between 2 and 100', 400)
        if not _is_room_owner(code):
            return _err('Only the room owner can change settings.', 403)
        # Directly update — we already verified ownership via token-or-session.
        with db.cursor() as cur:
            cur.execute("UPDATE rooms SET max_users = ? WHERE code = ?",
                        (max_users, code))
        return jsonify({'success': True, 'max_users': max_users})
    except Exception as e:
        return _err(e, exc=e)


@app.route('/api/rooms/<code>/kick', methods=['POST'])
def room_kick(code):
    """Owner-only: kick a user from the room by their socket id.
    Body: {target_sid: '<sid>'}"""
    try:
        code = ''.join(c for c in code.upper() if c.isalnum())[:12]
        data = request.get_json(silent=True) or {}
        target_sid = (data.get('target_sid') or '').strip()
        if not target_sid:
            return _err('Missing target_sid', 400)
        if not db.get_room_owner(code):
            return _err('Room has no owner — cannot kick.', 403)
        if not _is_room_owner(code):
            return _err('Only the room owner can kick users.', 403)
        from realtime import kick_socket
        ok = kick_socket(code, target_sid)
        return jsonify({'success': True, 'kicked': ok, 'target_sid': target_sid})
    except Exception as e:
        return _err(e, exc=e)


# -- Health --------------------------------------------------------------------

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status':    'online', 'version': '3.1',
        'ml_ready':  _ml_ready,
        'features':  ['fault_detection', 'optimization', 'gate_minimization',
                      'question_solver', 'boolean_synth', 'connection_suggester'],
        'models': {
            'fault_detector':       bool(fault_detector and fault_detector.model is not None),
            'circuit_optimizer':    bool(circuit_optimizer and circuit_optimizer.model is not None),
            'gate_minimizer':       bool(gate_minimizer and gate_minimizer.model is not None),
            'connection_suggester': bool(connection_suggester and connection_suggester.is_ready()),
        }
    })


# -- Fault Detection -----------------------------------------------------------

@app.route('/api/analyze/faults', methods=['POST'])
def analyze_faults():
    if (r := _ml_guard()): return r
    try:
        circuit = (request.get_json(silent=True) or {}).get('circuit', {})
        faults  = fault_detector.detect_faults(circuit)
        return jsonify({'status': 'success', 'fault_count': len(faults),
                        'faults': faults,
                        'timestamp': datetime.now().isoformat()})
    except Exception as e:
        return _err(e, exc=e)


# -- Optimization --------------------------------------------------------------

@app.route('/api/analyze/optimize', methods=['POST'])
def analyze_optimize():
    if (r := _ml_guard()): return r
    try:
        circuit  = (request.get_json(silent=True) or {}).get('circuit', {})
        analysis = circuit_optimizer.analyze_circuit(circuit)
        summary  = circuit_optimizer.get_optimization_summary(circuit)
        return jsonify({'status': 'success', 'analysis': analysis,
                        'summary': summary,
                        'timestamp': datetime.now().isoformat()})
    except Exception as e:
        return _err(e, exc=e)


# -- Gate Minimization ---------------------------------------------------------

@app.route('/api/analyze/minimize', methods=['POST'])
def analyze_minimize():
    if (r := _ml_guard()): return r
    try:
        data       = request.get_json(silent=True) or {}
        circuit    = data.get('circuit', {})
        constraint = data.get('constraint')
        suggestions = gate_minimizer.suggest_implementation(circuit, constraint)
        # Pull gate-count / efficiency / benchmark from the full minimizer so
        # SmartPanel.MinTab can render them. Falls back gracefully if the
        # model can't score this particular circuit.
        try:
            stats = gate_minimizer.minimize_circuit(circuit) or {}
        except Exception:
            stats = {}
        return jsonify({
            'status':             'success',
            'suggestions':        suggestions,
            'current_gate_count': stats.get('current_gate_count'),
            'efficiency_score':   stats.get('efficiency_score'),
            'benchmark':          stats.get('benchmark'),
            'timestamp':          datetime.now().isoformat(),
        })
    except Exception as e:
        return _err(e, exc=e)


# -- Question Solver -----------------------------------------------------------

@app.route('/api/ask', methods=['POST'])
def ask_question():
    if (r := _ml_guard()): return r
    try:
        data     = request.get_json(silent=True) or {}
        question = data.get('question', '')
        circuit  = data.get('circuit', {})
        if not question:
            return _err('No question provided', 400)
        result = question_solver.solve(question, circuit)
        # Log the question + classified intent for online-learning feedback.
        # Each row gets a unique id so the client can attach feedback later.
        qid = _log_query(question, result)
        result['query_id'] = qid
        return jsonify({'status': 'success', **result,
                        'timestamp': datetime.now().isoformat()})
    except Exception as e:
        return _err(e, exc=e)


# ── User-feedback online-learning loop ────────────────────────────────────────
# Every /api/ask call appends one row to data/user_queries.csv. The /api/feedback
# endpoint flips a row's `helpful` flag and optionally corrects the intent
# label. The retrain script (data/retrain_intent.py) merges this file with the
# programmatic dataset before training.

_QUERY_LOG = os.path.join('data', 'user_queries.csv')
_QUERY_LOG_FIELDS = ['id', 'session_id', 'timestamp', 'question', 'intent',
                     'intent_confidence', 'ml_source',
                     'helpful', 'corrected_intent']


def _migrate_query_log_if_needed():
    """One-time migration: add session_id column to existing user_queries.csv."""
    import csv
    if not os.path.exists(_QUERY_LOG):
        return
    with open(_QUERY_LOG, 'r', newline='', encoding='utf-8') as f:
        first = f.readline().strip()
    if 'session_id' in first:
        return   # already migrated
    rows = []
    with open(_QUERY_LOG, 'r', newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            r['session_id'] = 'legacy'
            rows.append(r)
    with open(_QUERY_LOG, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=_QUERY_LOG_FIELDS)
        w.writeheader()
        w.writerows(rows)


def _log_query(question: str, result: dict) -> str:
    """Append the asked question + classified intent to the user-query log."""
    import csv
    import uuid
    _migrate_query_log_if_needed()
    qid = uuid.uuid4().hex[:12]
    row = {
        'id':                qid,
        'session_id':        _session_id(),
        'timestamp':         datetime.now().isoformat(),
        'question':          question.strip()[:300],
        'intent':            result.get('intent', ''),
        'intent_confidence': result.get('intent_confidence', ''),
        'ml_source':         result.get('ml_source', ''),
        'helpful':           '',
        'corrected_intent':  '',
    }
    new_file = not os.path.exists(_QUERY_LOG)
    try:
        with open(_QUERY_LOG, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=_QUERY_LOG_FIELDS)
            if new_file: w.writeheader()
            w.writerow(row)
    except Exception:
        pass
    return qid


@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
    """
    Body: {query_id: str, helpful: bool, corrected_intent?: str}
    Updates the user-query log so the retraining pipeline can use it.
    """
    import csv
    try:
        data = request.get_json(silent=True) or {}
        qid     = data.get('query_id', '').strip()
        helpful = data.get('helpful')
        corrected = (data.get('corrected_intent') or '').strip()
        if not qid:
            return _err('Missing query_id', 400)
        if not os.path.exists(_QUERY_LOG):
            return _err('No query log yet', 404)

        # Rewrite the CSV with the matching row updated.
        rows = []
        updated = False
        with open(_QUERY_LOG, 'r', newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r.get('id') == qid:
                    if helpful is not None: r['helpful'] = '1' if helpful else '0'
                    if corrected:           r['corrected_intent'] = corrected
                    updated = True
                rows.append(r)
        with open(_QUERY_LOG, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=_QUERY_LOG_FIELDS)
            w.writeheader()
            w.writerows(rows)

        return jsonify({'status': 'success', 'updated': updated, 'query_id': qid})
    except Exception as e:
        return _err(e, exc=e)


@app.route('/api/learning/stats', methods=['GET'])
def learning_stats():
    """Show how much user data the ML can learn from."""
    import csv
    if not os.path.exists(_QUERY_LOG):
        return jsonify({'total_queries': 0, 'helpful': 0, 'unhelpful': 0,
                        'corrected': 0, 'intents': {}})
    helpful = unhelpful = corrected = total = 0
    intents = {}
    with open(_QUERY_LOG, 'r', newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            total += 1
            if r.get('helpful') == '1':   helpful   += 1
            if r.get('helpful') == '0':   unhelpful += 1
            if r.get('corrected_intent'): corrected += 1
            i = r.get('intent', '')
            intents[i] = intents.get(i, 0) + 1
    return jsonify({
        'total_queries':   total,
        'helpful':         helpful,
        'unhelpful':       unhelpful,
        'corrected':       corrected,
        'intents':         intents,
    })


@app.route('/api/learning/retrain', methods=['POST'])
def trigger_retrain():
    """
    Merges user-query log into intent training data and retrains the
    classifier. Use sparingly — full retrain takes 10-30 seconds.
    """
    from ml_models.question_solver import QuestionSolver
    try:
        # Wipe the pickle so the IntentClassifier lazily retrains on next /ask.
        pkl = os.path.join('ml_models', 'saved', 'intent_classifier.pkl')
        if os.path.exists(pkl):
            os.remove(pkl)
        # Reset the class-level cache (NOT instance) so the next call rebuilds.
        QuestionSolver._ml_intent = None
        # Pre-train synchronously so the user sees the update happen now.
        from ml_models.intent_classifier import IntentClassifier
        fresh = IntentClassifier()           # this triggers train() via _load_or_train
        QuestionSolver._ml_intent = fresh
        return jsonify({
            'status': 'success',
            'message': 'Intent classifier retrained with your feedback merged in.',
        })
    except Exception as e:
        return _err(e, exc=e)


# -- ML Output Prediction ------------------------------------------------------

@app.route('/api/predict', methods=['POST'])
def predict_output():
    """Directly predict circuit output using ML model."""
    if (r := _ml_guard()): return r
    try:
        circuit = (request.get_json(silent=True) or {}).get('circuit', {})
        row     = fault_detector._circuit_to_row(circuit)
        if row is None or fault_detector.model is None:
            return _err('Model not ready', 503)
        pred = fault_detector.predict_output(row)
        conf = fault_detector.predict_proba(row)
        return jsonify({
            'status': 'success',
            'predicted_output': pred,
            'confidence':   round(max(conf, 1 - conf), 4),
            'confidence_0': round(1 - conf, 4),
            'confidence_1': round(conf, 4),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return _err(e, exc=e)


# -- Full Analysis -------------------------------------------------------------

@app.route('/api/analyze/full', methods=['POST'])
def analyze_full():
    if (r := _ml_guard()): return r
    try:
        data    = request.get_json(silent=True) or {}
        circuit = data.get('circuit', {})
        faults       = fault_detector.detect_faults(circuit)
        optimization = circuit_optimizer.analyze_circuit(circuit)
        opt_summary  = circuit_optimizer.get_optimization_summary(circuit)
        minimization = gate_minimizer.minimize_circuit(circuit)

        def severity(faults):
            for s in ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW'):
                if any(f['severity'] == s for f in faults):
                    return s
            return 'NONE'

        return jsonify({
            'status': 'success',
            'circuit_name': data.get('name', 'Untitled'),
            'analysis': {
                'faults': {
                    'count':    len(faults),
                    'issues':   faults,
                    'severity': severity(faults),
                },
                'optimization': {
                    'suggestions_count': len(optimization['suggestions']),
                    'suggestions':       optimization['suggestions'][:5],
                    'potential_savings': opt_summary['potential_savings'],
                },
                'minimization': {
                    'current_gates':    minimization['current_gate_count'],
                    'benchmark':        minimization['benchmark'],
                    'efficiency_score': minimization['efficiency_score'],
                    'suggestions':      minimization['suggestions'][:3],
                },
            },
            'timestamp': datetime.now().isoformat(),
        })
    except Exception as e:
        return _err(e, exc=e)


# -- Boolean -> Gate JSON -------------------------------------------------------

@app.route('/api/build/boolean', methods=['POST'])
def build_boolean():
    """
    Body: {expression: 'A & B | ~C', target_gates?: ['NAND'], name?: 'expr'}
    Returns the gate/wire JSON the frontend can render directly.
    """
    if (r := _ml_guard()): return r
    try:
        data = request.get_json(silent=True) or {}
        expr = (data.get('expression') or '').strip()
        if not expr:
            return _err('No expression provided', 400)
        target = data.get('target_gates')   # optional list, e.g. ['NAND']
        circuit, info = boolean_synth.build(expr, target_gates=target)
        return jsonify({
            'status': 'success', 'success': True,
            'circuit': circuit, 'info': info,
            'name': data.get('name') or expr[:30],
            'timestamp': datetime.now().isoformat(),
        })
    except BooleanParseError as e:
        return _err(f"Could not parse expression: {e}", 400)
    except Exception as e:
        return _err(e, exc=e)


# -- Question -> Circuit --------------------------------------------------------

@app.route('/api/build/question', methods=['POST'])
def build_question():
    """
    Body: {question: 'build a half adder' / 'A xor B' / 'XOR using NAND'}
    Returns gate JSON if interpretable, otherwise a textual answer.
    """
    if (r := _ml_guard()): return r
    try:
        data     = request.get_json(silent=True) or {}
        question = (data.get('question') or '').strip()
        if not question:
            return _err('No question provided', 400)
        result = question_solver.build_from_text(question)
        return jsonify({'status': 'success', **result,
                        'timestamp': datetime.now().isoformat()})
    except Exception as e:
        return _err(e, exc=e)


# -- Synthesise with a restricted gate set -------------------------------------

@app.route('/api/synthesize', methods=['POST'])
def synthesize():
    """
    Body: {expression: '...', allowed_gates: ['NAND'] | ['NOR'] | ['AND','OR','NOT']}
    """
    if (r := _ml_guard()): return r
    try:
        data    = request.get_json(silent=True) or {}
        expr    = (data.get('expression') or '').strip()
        allowed = data.get('allowed_gates') or ['AND', 'OR', 'NOT']
        if not expr:
            return _err('No expression provided', 400)
        circuit, info = boolean_synth.build(expr, target_gates=allowed)
        return jsonify({'status': 'success', 'success': True,
                        'circuit': circuit, 'info': info,
                        'allowed_gates': allowed,
                        'timestamp': datetime.now().isoformat()})
    except BooleanParseError as e:
        return _err(f"Could not parse expression: {e}", 400)
    except Exception as e:
        return _err(e, exc=e)


# -- Connection suggestions ----------------------------------------------------

@app.route('/api/suggest/connection', methods=['POST'])
def suggest_connection():
    """
    Body: {circuit: {gates,wires}, top_k?: 5}
    Returns ranked candidate wires the ML thinks should be added.
    """
    if (r := _ml_guard()): return r
    try:
        data    = request.get_json(silent=True) or {}
        circuit = data.get('circuit', {})
        top_k   = int(data.get('top_k', 5) or 5)
        suggestions = connection_suggester.suggest(circuit, top_k=top_k)
        return jsonify({
            'status': 'success', 'success': True,
            'suggestions': suggestions,
            'timestamp':   datetime.now().isoformat(),
        })
    except Exception as e:
        return _err(e, exc=e)


# -- Legacy /api save/load/list/delete (kept for compatibility) ----------------

@app.route('/api/save', methods=['POST'])
def save_circuit():
    try:
        data = request.get_json(silent=True) or {}
        name = _safe_name(data.get('name', 'circuit'))
        payload = {
            'name':      name,
            'circuit':   data.get('circuit', {}),
            'timestamp': datetime.now().isoformat(),
        }
        with open(os.path.join(CIRCUITS_DIR, f"{name}.json"), 'w') as f:
            json.dump(payload, f, indent=2)
        return jsonify({'status': 'success', 'message': f'Saved: {name}'})
    except Exception as e:
        return _err(e, exc=e)


@app.route('/api/load/<name>', methods=['GET'])
def load_circuit(name):
    try:
        name = _safe_name(name)
        path = os.path.join(CIRCUITS_DIR, f"{name}.json")
        if not os.path.exists(path):
            return jsonify({'status': 'error', 'message': f'Not found: {name}'}), 404
        with open(path) as f:
            return jsonify({'status': 'success', 'data': json.load(f)})
    except Exception as e:
        return _err(e, exc=e)


@app.route('/api/list', methods=['GET'])
def list_circuits():
    try:
        circuits = []
        for file in os.listdir(CIRCUITS_DIR):
            if file.endswith('.json'):
                stat = os.stat(os.path.join(CIRCUITS_DIR, file))
                circuits.append({
                    'name':     file[:-5],
                    'size':     stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        return jsonify({
            'status': 'success',
            'circuits': sorted(circuits, key=lambda x: x['modified'], reverse=True),
        })
    except Exception as e:
        return _err(e, exc=e)


@app.route('/api/delete/<name>', methods=['DELETE'])
def delete_circuit(name):
    try:
        name = _safe_name(name)
        path = os.path.join(CIRCUITS_DIR, f"{name}.json")
        if not os.path.exists(path):
            return jsonify({'status': 'error', 'message': f'Not found: {name}'}), 404
        os.remove(path)
        return jsonify({'status': 'success', 'message': f'Deleted: {name}'})
    except Exception as e:
        return _err(e, exc=e)


if __name__ == '__main__':
    # Local dev defaults; PaaS hosts set $PORT and we honour it.
    # MUST use socketio.run instead of app.run so WebSocket connections work.
    port  = int(os.environ.get('PORT', '5000'))
    # Debug off in production (FLASK_ENV=production) — debug=True spawns a
    # reloader child that doubles memory usage and OOMs the 512Mi free tier.
    _default_debug = '0' if os.environ.get('FLASK_ENV', '').lower() == 'production' else '1'
    debug = os.environ.get('FLASK_DEBUG', _default_debug) == '1'
    socketio.run(
        app,
        host='0.0.0.0', port=port,
        debug=debug,
        # Werkzeug refuses to run in prod by default; allow it for dev.
        allow_unsafe_werkzeug=True,
    )
