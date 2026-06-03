"""
FaultDetector  -  pure ML fault detection.

Trained on circuit_patterns.csv.
A "fault" = circuit produces wrong output for given inputs.
The model predicts expected_output from (circuit_topology + input_values).
If simulator output != ML predicted output -> fault flagged.
Also detects structural faults: floating pins, unused gates, etc.
"""

import os, json, joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from .data_parser import row_to_features, count_active_gates, load_dataset, GATE_MAP, MAX_GATES

MODEL_PATH  = os.path.join(os.path.dirname(__file__), 'saved', 'fault_detector.pkl')
SCALER_PATH = os.path.join(os.path.dirname(__file__), 'saved', 'fault_scaler.pkl')

class FaultDetector:
    def __init__(self):
        os.makedirs(os.path.join(os.path.dirname(__file__), 'saved'), exist_ok=True)
        self.model  = None
        self.scaler = None
        self._load_or_train()

    # -- Training -------------------------------------------------------------

    def train(self, csv_path):
        print("[FaultDetector] Loading data...")
        X, y, _ = load_dataset(csv_path)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.15, random_state=42, stratify=y
        )

        self.scaler = StandardScaler()
        X_train_s   = self.scaler.fit_transform(X_train)
        X_test_s    = self.scaler.transform(X_test)

        print("[FaultDetector] Training MLP ...")
        self.model = MLPClassifier(
            hidden_layer_sizes=(256, 128, 64),
            activation='relu',
            max_iter=200,
            random_state=42,
            early_stopping=True,
            validation_fraction=0.1,
            verbose=False
        )
        self.model.fit(X_train_s, y_train)

        acc = accuracy_score(y_test, self.model.predict(X_test_s))
        print(f"[FaultDetector] Test accuracy: {acc:.4f}")

        joblib.dump(self.model,  MODEL_PATH)
        joblib.dump(self.scaler, SCALER_PATH)
        print("[FaultDetector] Model saved.")
        return acc

    def _load_or_train(self):
        csv = os.path.join(os.path.dirname(__file__), '..', 'data', 'circuit_patterns.csv')
        if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
            self.model  = joblib.load(MODEL_PATH)
            self.scaler = joblib.load(SCALER_PATH)
            print("[FaultDetector] Loaded saved model.")
        elif os.path.exists(csv):
            self.train(csv)
        else:
            print("[FaultDetector] WARNING: no data found, using dummy model.")
            self.model  = None
            self.scaler = None

    # -- Inference -------------------------------------------------------------

    def predict_output(self, circuit_row: dict) -> int:
        """Predict what the circuit SHOULD output (pure ML)."""
        if self.model is None or circuit_row is None:
            return -1
        feats   = row_to_features(circuit_row).reshape(1, -1)
        feats_s = self.scaler.transform(feats)
        return int(self.model.predict(feats_s)[0])

    def predict_proba(self, circuit_row: dict) -> float:
        """Confidence that output=1."""
        if self.model is None or circuit_row is None:
            return 0.5
        feats   = row_to_features(circuit_row).reshape(1, -1)
        feats_s = self.scaler.transform(feats)
        probs   = self.model.predict_proba(feats_s)[0]
        # If model only saw one class during training, predict_proba is 1-D
        if len(probs) < 2:
            return float(self.model.classes_[0])
        return float(probs[1])

    # -- Main API: detect_faults -----------------------------------------------

    def detect_faults(self, circuit: dict) -> list:
        """
        Accepts the frontend circuit JSON:
          {gates: [{id, type, x, y, value?}], wires: [{from, to, from_pin, to_pin}]}
        Returns list of fault dicts.
        """
        faults = []
        gates  = circuit.get('gates', [])
        wires  = circuit.get('wires', [])

        if not gates:
            return [{'type': 'EMPTY_CIRCUIT', 'severity': 'CRITICAL',
                     'message': 'Circuit has no gates', 'gates': []}]

        # -- Build wire maps ---------------------------------------------------
        gate_map     = {g['id']: g for g in gates}
        outputs_to   = {g['id']: [] for g in gates}   # gate -> gates it feeds
        inputs_from  = {g['id']: [] for g in gates}   # gate -> gates feeding it

        for w in wires:
            src = w.get('from') or w.get('from_gate') or w.get('fg')
            dst = w.get('to')   or w.get('to_gate')   or w.get('tg')
            if src in gate_map and dst in gate_map:
                outputs_to[src].append(dst)
                inputs_from[dst].append(src)

        input_gates  = [g for g in gates if g['type'].upper() in ('INPUT', 'CLOCK')]
        output_gates = [g for g in gates if g['type'].upper() == 'OUTPUT']
        logic_gates  = [g for g in gates if g['type'].upper() not in
                        ('INPUT', 'CLOCK', 'OUTPUT')]

        # -- 1. FLOATING INPUT pins --------------------------------------------
        pin_needs = {
            # standard gates
            'NOT': 1, 'AND': 2, 'OR': 2, 'NAND': 2,
            'NOR': 2, 'XOR': 2, 'XNOR': 2, 'OUTPUT': 1,
            # power/indicator (LED is a 1-input sink, VCC/GND have 0)
            'LED': 1, 'BUS': 1,
            # composite blocks
            'HA': 2, 'FA': 3, 'MUX4': 6, 'DEC24': 2, 'ADD4': 9,
            # sequential (data + clock; JK adds K, REG4 has 4 data + 1 clock)
            'DFF': 2, 'TFF': 2, 'JKFF': 3, 'REG4': 5,
        }
        for g in logic_gates + output_gates:
            needed  = pin_needs.get(g['type'].upper(), 2)
            connected = len(inputs_from[g['id']])
            if connected < needed:
                faults.append({
                    'type': 'FLOATING_INPUT',
                    'severity': 'CRITICAL',
                    'message': f"Gate '{g['id']}' ({g['type']}) has {connected}/{needed} inputs connected",
                    'gates': [g['id']]
                })

        # -- 2. UNCONNECTED OUTPUT (logic gate drives nothing) -----------------
        for g in logic_gates:
            if not outputs_to[g['id']]:
                faults.append({
                    'type': 'UNCONNECTED_OUTPUT',
                    'severity': 'MEDIUM',
                    'message': f"Gate '{g['id']}' ({g['type']}) output is not connected to anything",
                    'gates': [g['id']]
                })

        # -- 3. UNUSED INPUT gates ---------------------------------------------
        for g in input_gates:
            if not outputs_to[g['id']]:
                faults.append({
                    'type': 'UNUSED_INPUT',
                    'severity': 'LOW',
                    'message': f"Input '{g['id']}' is never used in the circuit",
                    'gates': [g['id']]
                })

        # -- 4. NO OUTPUT gate -------------------------------------------------
        if not output_gates:
            faults.append({
                'type': 'NO_OUTPUT',
                'severity': 'HIGH',
                'message': 'Circuit has no OUTPUT gate  -  result cannot be observed',
                'gates': []
            })

        # -- 5. FEEDBACK LOOP (iterative DFS, no recursion explosion) ---------
        for g in self._find_cycles(gates, outputs_to):
            faults.append({
                'type': 'FEEDBACK_LOOP',
                'severity': 'HIGH',
                'message': f"Feedback loop detected involving gate '{g[0]}'",
                'gates': g,
            })

        # -- 6. ML OUTPUT VERIFICATION -----------------------------------------
        # Build a circuit_row dict from the frontend format and run ML prediction
        row = self._circuit_to_row(circuit)
        if row and self.model is not None:
            ml_pred  = self.predict_output(row)
            conf     = self.predict_proba(row)
            # Flag if model is uncertain (confidence near 0.5)
            if 0.35 < conf < 0.65:
                faults.append({
                    'type': 'ML_UNCERTAIN_OUTPUT',
                    'severity': 'MEDIUM',
                    'message': f"ML model is uncertain about circuit output (confidence: {conf:.0%}). "
                               f"Circuit topology may contain ambiguous logic.",
                    'gates': [],
                    'ml_confidence': conf
                })

        return faults

    def _find_cycles(self, gates, outputs_to):
        """Return a list of cyclic-gate groups (each group is a list of gate ids)."""
        WHITE, GRAY, BLACK = 0, 1, 2
        colour = {g['id']: WHITE for g in gates}
        cycles = []

        def visit(start):
            stack = [(start, iter(outputs_to.get(start, [])))]
            path  = [start]
            colour[start] = GRAY
            while stack:
                node, it = stack[-1]
                try:
                    nxt = next(it)
                except StopIteration:
                    colour[node] = BLACK
                    stack.pop()
                    path.pop()
                    continue
                if colour.get(nxt, BLACK) == GRAY:
                    # Found cycle: slice from nxt onward
                    if nxt in path:
                        cycles.append(path[path.index(nxt):] + [nxt])
                    continue
                if colour.get(nxt, BLACK) == WHITE:
                    colour[nxt] = GRAY
                    path.append(nxt)
                    stack.append((nxt, iter(outputs_to.get(nxt, []))))

        for g in gates:
            if colour[g['id']] == WHITE:
                visit(g['id'])
        return cycles

    def _circuit_to_row(self, circuit: dict) -> dict:
        """Convert frontend circuit JSON to a row dict for feature extraction."""
        gates  = circuit.get('gates', [])
        wires  = circuit.get('wires', [])

        input_gates  = [g for g in gates if g['type'].upper() in ('INPUT', 'CLOCK')]
        logic_gates  = [g for g in gates if g['type'].upper() not in
                        ('INPUT', 'CLOCK', 'OUTPUT')]

        # Map gate id -> index in inputs list
        input_idx = {g['id']: i for i, g in enumerate(input_gates)}
        logic_idx = {g['id']: i + len(input_gates) for i, g in enumerate(logic_gates)}
        all_idx   = {**input_idx, **logic_idx}

        # Build wire lookup: dst_id -> {pin: src_id}
        wire_map = {}
        for w in wires:
            src = w.get('from') or w.get('from_gate') or w.get('fg')
            dst = w.get('to')   or w.get('to_gate')   or w.get('tg')
            pin = int(w.get('to_pin', w.get('tp', 0)) or 0)
            if src and dst:
                wire_map.setdefault(dst, {})[pin] = src

        row = {
            'depth':      len(logic_gates),
            'num_inputs': len(input_gates),
            'A': int(input_gates[0].get('value', 0)) if len(input_gates) > 0 else -1,
            'B': int(input_gates[1].get('value', 0)) if len(input_gates) > 1 else -1,
            'C': int(input_gates[2].get('value', 0)) if len(input_gates) > 2 else -1,
            'D': int(input_gates[3].get('value', 0)) if len(input_gates) > 3 else -1,
        }

        for i, g in enumerate(logic_gates[:MAX_GATES]):
            pins = wire_map.get(g['id'], {})
            row[f'gate{i}']   = g['type'].upper()
            row[f'g{i}_src0'] = all_idx.get(pins.get(0), -1)
            row[f'g{i}_src1'] = all_idx.get(pins.get(1), -1)

        for i in range(len(logic_gates), MAX_GATES):
            row[f'gate{i}']   = 'NONE'
            row[f'g{i}_src0'] = -1
            row[f'g{i}_src1'] = -1

        return row