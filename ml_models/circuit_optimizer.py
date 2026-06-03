"""
CircuitOptimizer  -  ML-powered optimization suggestions.

Uses a trained model to score circuit quality and suggest
better gate configurations based on patterns in training data.
"""

import os, joblib
import numpy as np
import pandas as pd
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from .data_parser import row_to_features, load_dataset, MAX_GATES, GATE_TYPES

MODEL_PATH  = os.path.join(os.path.dirname(__file__), 'saved', 'optimizer.pkl')
SCALER_PATH = os.path.join(os.path.dirname(__file__), 'saved', 'optimizer_scaler.pkl')
STATS_PATH  = os.path.join(os.path.dirname(__file__), 'saved', 'gate_stats.pkl')

class CircuitOptimizer:
    def __init__(self):
        os.makedirs(os.path.join(os.path.dirname(__file__), 'saved'), exist_ok=True)
        self.model      = None
        self.scaler     = None
        self.gate_stats = {}   # learned gate usage statistics
        self._load_or_train()

    # -- Training -------------------------------------------------------------

    def train(self, csv_path):
        print("[CircuitOptimizer] Loading data...")
        X, y, df = load_dataset(csv_path)

        self._learn_gate_stats(df)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.15, random_state=42, stratify=y
        )

        self.scaler = StandardScaler()
        X_train_s   = self.scaler.fit_transform(X_train)
        X_test_s    = self.scaler.transform(X_test)

        print("[CircuitOptimizer] Training MLP optimizer ...")
        self.model = MLPClassifier(
            hidden_layer_sizes=(64, 32),
            activation='relu',
            max_iter=80,
            random_state=42,
            early_stopping=True,
            validation_fraction=0.1
        )
        self.model.fit(X_train_s, y_train)

        acc = accuracy_score(y_test, self.model.predict(X_test_s))
        print(f"[CircuitOptimizer] Test accuracy: {acc:.4f}")

        joblib.dump(self.model,      MODEL_PATH)
        joblib.dump(self.scaler,     SCALER_PATH)
        joblib.dump(self.gate_stats, STATS_PATH)
        print("[CircuitOptimizer] Model saved.")
        return acc

    def _learn_gate_stats(self, df):
        """
        Learn: for each gate slot position, what gate types are most common
        and what connection patterns work best.
        """
        gate_cols = [f'gate{i}' for i in range(MAX_GATES)]
        for i in range(MAX_GATES):
            col = f'gate{i}'
            if col not in df.columns:
                continue
            active = df[df[col] != 'NONE']
            if active.empty:
                continue
            freq   = active[col].value_counts(normalize=True).to_dict()
            # Best performing gate types at this position
            gate_output = {}
            for gt in freq:
                subset = active[active[col] == gt]
                if len(subset) > 0:
                    gate_output[gt] = {
                        'frequency': freq[gt],
                        'output_1_rate': float(subset['output'].mean())
                    }
            self.gate_stats[f'pos_{i}'] = gate_output

    def _load_or_train(self):
        csv = os.path.join(os.path.dirname(__file__), '..', 'data', 'circuit_patterns.csv')
        if (os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH)
                and os.path.exists(STATS_PATH)):
            self.model      = joblib.load(MODEL_PATH)
            self.scaler     = joblib.load(SCALER_PATH)
            self.gate_stats = joblib.load(STATS_PATH)
            print("[CircuitOptimizer] Loaded saved model.")
        elif os.path.exists(csv):
            self.train(csv)
        else:
            print("[CircuitOptimizer] WARNING: no data found.")

    # -- Main API --------------------------------------------------------------

    def analyze_circuit(self, circuit: dict) -> dict:
        """Full optimization analysis of a circuit."""
        suggestions = []
        gates  = circuit.get('gates', [])
        wires  = circuit.get('wires', [])

        logic_gates = [g for g in gates if g['type'].upper() not in
                       ('INPUT', 'CLOCK', 'OUTPUT')]
        input_gates = [g for g in gates if g['type'].upper() in ('INPUT', 'CLOCK')]

        # -- 1. Gate type distribution analysis -------------------------------
        type_counts = {}
        for g in logic_gates:
            t = g['type'].upper()
            type_counts[t] = type_counts.get(t, 0) + 1

        # Check if NAND-heavy (can often reduce)
        total = len(logic_gates)
        if total == 0:
            return {'suggestions': [], 'metrics': {}, 'score': 0}

        # -- 2. ML feature importance analysis --------------------------------
        # Build row and get feature importances
        ml_suggestions = self._ml_gate_suggestions(circuit, logic_gates, input_gates)
        suggestions.extend(ml_suggestions)

        # -- 3. Wire complexity analysis ---------------------------------------
        wire_suggestions = self._analyze_wire_complexity(gates, wires)
        suggestions.extend(wire_suggestions)

        # -- 4. Gate position efficiency (learned from data) -------------------
        pos_suggestions = self._position_efficiency(logic_gates)
        suggestions.extend(pos_suggestions)

        # -- 5. Depth analysis -------------------------------------------------
        depth_suggestions = self._depth_analysis(circuit)
        suggestions.extend(depth_suggestions)

        metrics = self._calculate_metrics(circuit)

        return {
            'suggestions': suggestions,
            'metrics': metrics,
            'total_suggestions': len(suggestions)
        }

    def get_optimization_summary(self, circuit: dict) -> dict:
        analysis = self.analyze_circuit(circuit)
        total_savings = sum(s.get('savings', 0) for s in analysis['suggestions'])
        return {
            'total_suggestions': len(analysis['suggestions']),
            'potential_savings': total_savings,
            'metrics': analysis['metrics']
        }

    # -- Internal helpers ------------------------------------------------------

    def _ml_gate_suggestions(self, circuit, logic_gates, input_gates) -> list:
        """Use ML model to evaluate gate configuration quality."""
        suggestions = []
        if self.model is None or not logic_gates:
            return suggestions

        from .data_parser import row_to_features

        # Build a representation of the circuit
        row = self._build_row(circuit, logic_gates, input_gates)
        feats   = row_to_features(row).reshape(1, -1)
        feats_s = self.scaler.transform(feats)
        conf    = float(self.model.predict_proba(feats_s)[0].max())

        if conf < 0.75:
            suggestions.append({
                'type': 'ML_LOW_CONFIDENCE',
                'severity': 'MEDIUM',
                'description': f"ML model confidence in this circuit's output is {conf:.0%}. "
                               f"Circuit may have suboptimal gate selection.",
                'savings': 0,
                'confidence': conf
            })

        # Compare gate type frequencies to learned optimal patterns
        for i, g in enumerate(logic_gates[:MAX_GATES]):
            pos_key = f'pos_{i}'
            if pos_key not in self.gate_stats:
                continue
            pos_data = self.gate_stats[pos_key]
            current_type = g['type'].upper()
            if current_type not in pos_data:
                continue

            current_freq = pos_data[current_type]['frequency']
            # Find most common gate at this position
            best_type = max(pos_data, key=lambda t: pos_data[t]['frequency'])
            best_freq  = pos_data[best_type]['frequency']

            if best_type != current_type and best_freq > current_freq * 1.5:
                suggestions.append({
                    'type': 'SUBOPTIMAL_GATE_POSITION',
                    'severity': 'LOW',
                    'description': f"Gate #{i} ({current_type})  -  in similar circuits, "
                                   f"{best_type} is used here {best_freq:.0%} of the time",
                    'gate_id': g['id'],
                    'current': current_type,
                    'suggested': best_type,
                    'savings': 0
                })

        return suggestions[:5]  # Top 5

    def _analyze_wire_complexity(self, gates, wires) -> list:
        """Flag gates with unusually high fan-in or fan-out."""
        suggestions = []
        fanout = {}
        fanin  = {}

        for w in wires:
            src = w.get('from') or w.get('from_gate') or w.get('fg')
            dst = w.get('to')   or w.get('to_gate')   or w.get('tg')
            if src: fanout[src] = fanout.get(src, 0) + 1
            if dst: fanin[dst]  = fanin.get(dst, 0)  + 1

        gate_map = {g['id']: g for g in gates}

        for gid, count in fanout.items():
            if count > 3:
                g = gate_map.get(gid, {})
                suggestions.append({
                    'type': 'HIGH_FANOUT',
                    'severity': 'MEDIUM',
                    'description': f"Gate '{gid}' ({g.get('type','?')}) drives {count} outputs. "
                                   f"High fan-out can cause signal integrity issues. "
                                   f"Consider buffering.",
                    'gate_id': gid,
                    'savings': 0
                })

        return suggestions

    def _position_efficiency(self, logic_gates) -> list:
        """Check if gate sequence has unnecessary complexity."""
        suggestions = []
        types = [g['type'].upper() for g in logic_gates]

        # Detect long NOT chains
        not_chain = 0
        for t in types:
            if t == 'NOT':
                not_chain += 1
            else:
                if not_chain >= 2:
                    suggestions.append({
                        'type': 'LONG_NOT_CHAIN',
                        'severity': 'LOW',
                        'description': f"Chain of {not_chain} NOT gates detected. "
                                       f"Even-number NOT chains can be fully removed, "
                                       f"saving up to {not_chain} gates.",
                        'savings': not_chain
                    })
                not_chain = 0

        return suggestions

    def _depth_analysis(self, circuit) -> list:
        """Estimate circuit depth and suggest pipelining if deep."""
        suggestions = []
        gates  = circuit.get('gates', [])
        wires  = circuit.get('wires', [])

        logic_gates = [g for g in gates if g['type'].upper() not in
                       ('INPUT', 'CLOCK', 'OUTPUT')]

        if len(logic_gates) > 10:
            suggestions.append({
                'type': 'DEEP_CIRCUIT',
                'severity': 'LOW',
                'description': f"Circuit has {len(logic_gates)} logic gates in series. "
                               f"ML models show similar outputs achievable with fewer levels. "
                               f"Consider restructuring for parallel logic.",
                'savings': max(0, len(logic_gates) - 8)
            })

        return suggestions

    def _calculate_metrics(self, circuit) -> dict:
        gates       = circuit.get('gates', [])
        wires       = circuit.get('wires', [])
        logic_gates = [g for g in gates if g['type'].upper() not in
                       ('INPUT', 'CLOCK', 'OUTPUT')]
        return {
            'total_gates':  len(gates),
            'logic_gates':  len(logic_gates),
            'total_wires':  len(wires),
            'wire_to_gate_ratio': round(len(wires) / max(len(logic_gates), 1), 2)
        }

    def _build_row(self, circuit, logic_gates, input_gates) -> dict:
        wires   = circuit.get('wires', [])
        wire_map = {}
        for w in wires:
            src = w.get('from') or w.get('from_gate') or w.get('fg')
            dst = w.get('to')   or w.get('to_gate')   or w.get('tg')
            pin = int(w.get('to_pin', w.get('tp', 0)) or 0)
            if src and dst:
                wire_map.setdefault(dst, {})[pin] = src

        input_idx = {g['id']: i for i, g in enumerate(input_gates)}
        logic_idx = {g['id']: i + len(input_gates) for i, g in enumerate(logic_gates)}
        all_idx   = {**input_idx, **logic_idx}

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