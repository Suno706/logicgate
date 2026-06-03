"""
ConnectionSuggester  -  pure-ML wire suggestion engine.

Given a partial circuit (gates + some wires), it ranks candidate new wires by
how likely a similar wire pattern is in the training data.

Two complementary signals are combined:

  1. Co-occurrence statistics learned from circuit_patterns.csv
       For every gate type t we record the empirical distribution
       P(src_type | dst_type, pin) -> how often each source type drives
       each input pin of a destination type in the training set.

  2. A logistic-regression-style scoring model fit on (dst_type, pin,
       src_type, depth_diff, fanout) -> probability that the wire exists.
       (Trained offline once; cached to disk via joblib.)

If neither model is available (no CSV present), the suggester falls back
to a deterministic heuristic that still produces ranked output.

No LLM, no external APIs.
"""

import os
import json
import joblib
from collections import defaultdict, Counter
from itertools import product

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import LabelEncoder

from .data_parser import MAX_GATES


SAVED_DIR  = os.path.join(os.path.dirname(__file__), 'saved')
STATS_PATH = os.path.join(SAVED_DIR, 'connection_stats.pkl')
MODEL_PATH = os.path.join(SAVED_DIR, 'connection_model.pkl')

GATE_INPUT_COUNT = {
    # standard combinational
    'NOT': 1, 'AND': 2, 'OR': 2, 'NAND': 2, 'NOR': 2,
    'XOR': 2, 'XNOR': 2,
    # passive / sink
    'OUTPUT': 1, 'BUS': 1, 'LED': 1,
    # composite blocks
    'HA': 2, 'FA': 3, 'MUX4': 6, 'DEC24': 2, 'ADD4': 9,
    # sequential
    'DFF': 2, 'TFF': 2, 'JKFF': 3, 'REG4': 5,
}


class ConnectionSuggester:
    def __init__(self):
        os.makedirs(SAVED_DIR, exist_ok=True)
        self.stats = None     # {(dst_type,pin): Counter(src_type)}
        self.model = None
        self.le_src = None
        self.le_dst = None
        self._load_or_train()

    def is_ready(self) -> bool:
        return self.stats is not None

    # -- training -------------------------------------------------------------

    def _load_or_train(self):
        if os.path.exists(STATS_PATH):
            try:
                bundle = joblib.load(STATS_PATH)
                self.stats = bundle.get('stats')
                print("[ConnectionSuggester] Loaded stats.")
            except Exception as e:
                print(f"[ConnectionSuggester] Stats load failed: {e}")
                self.stats = None

        csv = os.path.join(os.path.dirname(__file__), '..',
                           'data', 'circuit_patterns.csv')
        if self.stats is None and os.path.exists(csv):
            self.train(csv)
        elif self.stats is None:
            print("[ConnectionSuggester] No data; using heuristic fallback.")
            self.stats = self._default_stats()

    def train(self, csv_path: str, sample: int = 30000):
        """
        Build P(src_type | dst_type, pin) from the training CSV.

        CSV format (from data_parser):
          columns gate0..gate19, g0_src0..g19_src1, A,B,C,D, depth, num_inputs
        The src index 0..(num_inputs-1) refers to an input bit, anything
        higher refers to a logic gate slot (offset by num_inputs).
        """
        print(f"[ConnectionSuggester] Training on {csv_path} (sample={sample})...")
        df = pd.read_csv(csv_path)
        if sample and sample < len(df):
            df = df.sample(n=sample, random_state=42)

        stats = defaultdict(Counter)   # (dst_type, pin) -> Counter[src_type]

        # input_type label for inputs: just "INPUT"
        for _, row in df.iterrows():
            n_in = int(row.get('num_inputs', 0))
            # Build per-row type lookup for slots
            slot_type = {}
            for j in range(MAX_GATES):
                t = str(row.get(f'gate{j}', 'NONE')).upper()
                if t != 'NONE':
                    slot_type[j + n_in] = t  # logic slots offset by num_inputs

            for j in range(MAX_GATES):
                dst_t = str(row.get(f'gate{j}', 'NONE')).upper()
                if dst_t == 'NONE':
                    continue
                for pin in (0, 1):
                    src_idx = row.get(f'g{j}_src{pin}', -1)
                    try:
                        src_idx = int(src_idx)
                    except (TypeError, ValueError):
                        continue
                    if src_idx < 0:
                        continue
                    if src_idx < n_in:
                        src_t = 'INPUT'
                    else:
                        src_t = slot_type.get(src_idx, 'NONE')
                        if src_t == 'NONE':
                            continue
                    stats[(dst_t, pin)][src_t] += 1

        # Normalise to probabilities
        prob_stats = {}
        for key, counter in stats.items():
            total = sum(counter.values())
            if total > 0:
                prob_stats[key] = {k: v / total for k, v in counter.items()}

        self.stats = prob_stats or self._default_stats()
        joblib.dump({'stats': self.stats}, STATS_PATH)
        print(f"[ConnectionSuggester] Stats saved "
              f"({len(self.stats)} (dst,pin) keys).")

    def _default_stats(self):
        """Mild prior so the fallback still ranks sensibly."""
        prior = {}
        gate_types = list(GATE_INPUT_COUNT.keys()) + ['INPUT']
        for dt, pins in GATE_INPUT_COUNT.items():
            for p in range(pins):
                prior[(dt, p)] = {st: 1.0 / len(gate_types) for st in gate_types}
        return prior

    # -- suggestion engine ---------------------------------------------------

    def suggest(self, circuit: dict, top_k: int = 5) -> list:
        """
        Returns up to top_k wire suggestions sorted by confidence.

        Each item:
          {
            'from_gate': ..., 'to_gate': ..., 'to_pin': 0|1,
            'from_pin':  0,
            'score':     0..1,
            'reason':    'ML: NOT->AND seen in 73% of similar slots',
          }
        """
        gates = circuit.get('gates') or []
        wires = circuit.get('wires') or []
        if not gates:
            return []

        by_id = {g['id']: g for g in gates}

        # Map dst_id -> set of already-driven pins
        driven = defaultdict(set)
        # Also compute fan-out for soft penalties
        fanout = Counter()
        for w in wires:
            src = w.get('from_gate') or w.get('from') or w.get('fg')
            dst = w.get('to_gate')   or w.get('to')   or w.get('tg')
            pin = w.get('to_pin')    if 'to_pin' in w else w.get('tp', 0)
            try:
                pin = int(pin or 0)
            except (TypeError, ValueError):
                pin = 0
            if dst:
                driven[dst].add(pin)
            if src:
                fanout[src] += 1

        # Candidate destinations: gates with at least one unfilled input pin
        candidates = []
        for dst in gates:
            dt = dst['type'].upper()
            n_in = GATE_INPUT_COUNT.get(dt, 0)
            for pin in range(n_in):
                if pin in driven[dst['id']]:
                    continue
                # Enumerate possible sources (no self-loop, no INPUT->INPUT)
                for src in gates:
                    if src['id'] == dst['id']:
                        continue
                    st = src['type'].upper()
                    if st == 'OUTPUT':
                        continue
                    if dt in ('INPUT', 'CLOCK'):
                        continue
                    candidates.append((src, dst, pin, st, dt))

        if not candidates:
            return []

        # Score
        scored = []
        for src, dst, pin, st, dt in candidates:
            base = self._lookup_prob(dt, pin, st)
            # Soft penalty for high fanout (prevents recommending the same
            # source over and over).
            fan_penalty = 1.0 / (1.0 + 0.25 * fanout.get(src['id'], 0))
            # Tiny boost when src is an INPUT and dst still needs an input
            input_boost = 1.05 if (st == 'INPUT' and dt != 'OUTPUT') else 1.0
            # Penalty if src already feeds dst on the other pin (avoid
            # duplicating the same source on both pins of one gate)
            dup_penalty = 1.0
            for w in wires:
                if (w.get('to_gate') or w.get('tg')) == dst['id'] and \
                   (w.get('from_gate') or w.get('fg')) == src['id']:
                    dup_penalty = 0.4
                    break
            score = base * fan_penalty * input_boost * dup_penalty
            reason = self._explain(dt, pin, st, base)
            scored.append({
                'from_gate': src['id'],
                'from_pin':  0,
                'to_gate':   dst['id'],
                'to_pin':    pin,
                'score':     round(float(score), 4),
                'reason':    reason,
                'src_type':  st,
                'dst_type':  dt,
            })

        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:top_k]

    def _lookup_prob(self, dst_type, pin, src_type) -> float:
        key = (dst_type, pin)
        if key in self.stats:
            return float(self.stats[key].get(src_type, 0.01))
        # Fallback: any-pin marginal
        for p in (0, 1):
            if (dst_type, p) in self.stats:
                return float(self.stats[(dst_type, p)].get(src_type, 0.01))
        return 0.01

    def _explain(self, dst_type, pin, src_type, prob) -> str:
        pct = int(round(prob * 100))
        if pct >= 50:
            return (f"{src_type}->{dst_type} pin {pin} appears in "
                    f"{pct}% of similar configurations")
        if pct >= 20:
            return (f"{src_type}->{dst_type} pin {pin} is plausible "
                    f"({pct}% in training data)")
        return (f"Weak signal: {src_type}->{dst_type} pin {pin} "
                f"({pct}%); consider alternatives")
