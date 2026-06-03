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

from flask import Flask, request, jsonify, render_template
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

app = Flask(__name__)
CORS(app)

print("Loading ML models...")
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
print("All ML models ready.")

CIRCUITS_DIR = 'circuits'
os.makedirs(CIRCUITS_DIR, exist_ok=True)


# -- helpers --------------------------------------------------------------------

def _safe_name(name: str) -> str:
    return ''.join(c for c in (name or 'circuit')
                   if c.isalnum() or c in ' -_').strip() or 'circuit'


def _err(message, code=400, exc=None):
    if exc is not None:
        traceback.print_exc()
    return jsonify({'status': 'error', 'success': False, 'message': str(message)}), code


# -- UI -------------------------------------------------------------------------

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


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
        data = request.get_json(silent=True) or {}
        name = _safe_name(data.get('name', 'circuit'))
        payload = {
            'name':      name,
            'gates':     data.get('gates', []),
            'wires':     data.get('wires', []),
            'timestamp': datetime.now().isoformat(),
        }
        with open(os.path.join(CIRCUITS_DIR, f"{name}.json"), 'w') as f:
            json.dump(payload, f, indent=2)
        return jsonify({'success': True, 'message': f'Saved: {name}'})
    except Exception as e:
        return _err(e, exc=e)


@app.route('/load/<name>', methods=['GET'])
def load_short(name):
    try:
        name = _safe_name(name)
        path = os.path.join(CIRCUITS_DIR, f"{name}.json")
        if not os.path.exists(path):
            return jsonify({'success': False, 'error': f'Not found: {name}'}), 404
        with open(path) as f:
            data = json.load(f)
        circuit = {
            'gates': data.get('gates', data.get('circuit', {}).get('gates', [])),
            'wires': data.get('wires', data.get('circuit', {}).get('wires', [])),
        }
        return jsonify({'success': True, 'circuit': circuit, 'name': name})
    except Exception as e:
        return _err(e, exc=e)


@app.route('/list-circuits', methods=['GET'])
def list_short():
    try:
        names = [f[:-5] for f in os.listdir(CIRCUITS_DIR)
                 if f.endswith('.json')]
        names.sort()
        return jsonify({'success': True, 'circuits': names})
    except Exception as e:
        return _err(e, exc=e)


# -- Health --------------------------------------------------------------------

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status':   'online', 'version': '3.1',
        'features': ['fault_detection', 'optimization', 'gate_minimization',
                     'question_solver', 'boolean_synth', 'connection_suggester'],
        'models': {
            'fault_detector':       fault_detector.model is not None,
            'circuit_optimizer':    circuit_optimizer.model is not None,
            'gate_minimizer':       gate_minimizer.model is not None,
            'connection_suggester': connection_suggester.is_ready(),
        }
    })


# -- Fault Detection -----------------------------------------------------------

@app.route('/api/analyze/faults', methods=['POST'])
def analyze_faults():
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
    try:
        data       = request.get_json(silent=True) or {}
        circuit    = data.get('circuit', {})
        constraint = data.get('constraint')
        suggestions = gate_minimizer.suggest_implementation(circuit, constraint)
        return jsonify({'status': 'success', 'suggestions': suggestions,
                        'timestamp': datetime.now().isoformat()})
    except Exception as e:
        return _err(e, exc=e)


# -- Question Solver -----------------------------------------------------------

@app.route('/api/ask', methods=['POST'])
def ask_question():
    try:
        data     = request.get_json(silent=True) or {}
        question = data.get('question', '')
        circuit  = data.get('circuit', {})
        if not question:
            return _err('No question provided', 400)
        result = question_solver.solve(question, circuit)
        return jsonify({'status': 'success', **result,
                        'timestamp': datetime.now().isoformat()})
    except Exception as e:
        return _err(e, exc=e)


# -- ML Output Prediction ------------------------------------------------------

@app.route('/api/predict', methods=['POST'])
def predict_output():
    """Directly predict circuit output using ML model."""
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
    # Local dev defaults; PaaS hosts (Render, Railway, Fly, Heroku, etc.) set
    # $PORT and we honour it. Set FLASK_DEBUG=0 in production to disable the
    # debug auto-reloader.
    port  = int(os.environ.get('PORT', '5000'))
    debug = os.environ.get('FLASK_DEBUG', '1') == '1'
    app.run(debug=debug, port=port, host='0.0.0.0')
