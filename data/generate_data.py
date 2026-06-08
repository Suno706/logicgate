"""
generate_data.py  —  Synthetic training data generator for LogicGate ML models.

Generates circuit_patterns.csv rows covering a wide range of realistic
gate-count, wire-count, input-count, and gate-type combinations.

Run:
    python data/generate_data.py            # appends to data/circuit_patterns.csv
    python data/generate_data.py --replace  # overwrites existing file
    python data/generate_data.py -n 50000   # custom row count

The CSV schema matches what fault_detector.py / circuit_optimizer.py expect:
  gate_count, wire_count, input_count, output_count,
  and_count, or_count, not_count, nand_count, nor_count, xor_count, xnor_count,
  max_depth, avg_fan_in, avg_fan_out, has_feedback,
  label  (0=clean, 1=faulty)
"""

import csv
import os
import random
import argparse
import math
from itertools import product

FIELDNAMES = [
    'gate_count', 'wire_count', 'input_count', 'output_count',
    'and_count', 'or_count', 'not_count', 'nand_count', 'nor_count',
    'xor_count', 'xnor_count',
    'max_depth', 'avg_fan_in', 'avg_fan_out', 'has_feedback',
    'label',
]

# --- circuit archetypes -------------------------------------------------------

ARCHETYPE_WEIGHTS = {
    'half_adder':      3,
    'full_adder':      3,
    'ripple_adder':    4,
    'multiplexer':     4,
    'decoder':         4,
    'encoder':         3,
    'comparator':      3,
    'parity':          3,
    'flip_flop':       5,
    'counter':         3,
    'alu':             3,
    'random_clean':    30,
    'random_faulty':   25,
}

def _weighted_choice(d: dict) -> str:
    keys   = list(d.keys())
    weights = list(d.values())
    return random.choices(keys, weights=weights, k=1)[0]


def _rand(lo: int, hi: int) -> int:
    return random.randint(lo, hi)


def _row_from_values(**kw) -> dict:
    r = {f: 0 for f in FIELDNAMES}
    r.update(kw)
    # Derived sanity: wire_count can't exceed combinatorial maximum
    max_wires = r['gate_count'] * 4
    r['wire_count'] = min(r['wire_count'], max_wires)
    r['avg_fan_in']  = round(r.get('avg_fan_in', 0), 2)
    r['avg_fan_out'] = round(r.get('avg_fan_out', 0), 2)
    return r


def _faulty_variant(base: dict) -> dict:
    """Take a clean circuit row and inject one of several common fault patterns."""
    r = dict(base)
    r['label'] = 1
    fault_kind = random.randint(0, 5)
    if fault_kind == 0:
        # Dangling input: remove some wires
        r['wire_count'] = max(0, r['wire_count'] - _rand(1, 3))
        r['avg_fan_in']  = max(0.0, r['avg_fan_in'] - 0.4)
    elif fault_kind == 1:
        # Short circuit / extra wire
        r['wire_count'] += _rand(1, 4)
        r['avg_fan_out'] += 0.5
    elif fault_kind == 2:
        # Wrong gate type substitution (change distribution slightly)
        extra = _rand(0, 2)
        r['and_count'] = max(0, r['and_count'] - extra)
        r['nand_count'] = r['nand_count'] + extra
    elif fault_kind == 3:
        # Missing output gate
        r['output_count'] = max(0, r['output_count'] - 1)
        r['wire_count'] = max(0, r['wire_count'] - _rand(1, 2))
    elif fault_kind == 4:
        # Feedback (unexpected latch)
        r['has_feedback'] = 1
    else:
        # Gate count mismatch (too many gates for function)
        r['gate_count'] += _rand(2, 5)
        r['wire_count'] += _rand(1, 4)
    return r


# --- archetype row generators -------------------------------------------------

def gen_half_adder() -> dict:
    return _row_from_values(
        gate_count=5, wire_count=6, input_count=2, output_count=2,
        xor_count=1, and_count=1,
        max_depth=2, avg_fan_in=1.5, avg_fan_out=1.2, has_feedback=0, label=0,
    )


def gen_full_adder() -> dict:
    style = random.choice(['standard', 'nand_only', 'nor_only'])
    if style == 'nand_only':
        return _row_from_values(
            gate_count=11, wire_count=14, input_count=3, output_count=2,
            nand_count=9,
            max_depth=5, avg_fan_in=1.8, avg_fan_out=1.3, has_feedback=0, label=0,
        )
    if style == 'nor_only':
        return _row_from_values(
            gate_count=11, wire_count=14, input_count=3, output_count=2,
            nor_count=9,
            max_depth=5, avg_fan_in=1.8, avg_fan_out=1.3, has_feedback=0, label=0,
        )
    return _row_from_values(
        gate_count=8, wire_count=10, input_count=3, output_count=2,
        xor_count=2, and_count=2, or_count=1,
        max_depth=3, avg_fan_in=1.7, avg_fan_out=1.3, has_feedback=0, label=0,
    )


def gen_ripple_adder() -> dict:
    n = random.choice([2, 4, 8, 16])
    fa_gates = 8
    total    = n * fa_gates + n + 2  # FAs + INs + OUT
    wires    = n * 10 + n
    return _row_from_values(
        gate_count=total, wire_count=wires, input_count=n * 2 + 1, output_count=n + 1,
        xor_count=n * 2, and_count=n * 2, or_count=n,
        max_depth=n * 3 + 1, avg_fan_in=1.8, avg_fan_out=1.3, has_feedback=0, label=0,
    )


def gen_multiplexer() -> dict:
    n = random.choice([2, 4, 8])       # data inputs
    sel = int(math.log2(n))
    gates_per_path = sel + 1
    total_logic  = n * gates_per_path + 1
    total        = total_logic + n + sel + 1
    wires        = n * (sel + 2) + sel + 2
    return _row_from_values(
        gate_count=total, wire_count=wires,
        input_count=n + sel, output_count=1,
        and_count=n, or_count=1, not_count=sel,
        max_depth=sel + 2, avg_fan_in=1.9, avg_fan_out=2.0, has_feedback=0, label=0,
    )


def gen_decoder() -> dict:
    n = random.choice([2, 3, 4])       # input bits → 2^n outputs
    outputs = 2 ** n
    not_gates = n
    and_gates = outputs
    total    = and_gates + not_gates + n + outputs
    wires    = outputs * (n + 1) + n + outputs
    return _row_from_values(
        gate_count=total, wire_count=wires,
        input_count=n, output_count=outputs,
        and_count=and_gates, not_count=not_gates,
        max_depth=3, avg_fan_in=n * 0.8, avg_fan_out=outputs / n,
        has_feedback=0, label=0,
    )


def gen_encoder() -> dict:
    n_out = random.choice([2, 3, 4])   # output bits
    n_in  = 2 ** n_out
    or_gates = n_out
    total  = or_gates + n_in + n_out
    wires  = n_out * (n_in // 2) + n_in + n_out
    return _row_from_values(
        gate_count=total, wire_count=wires,
        input_count=n_in, output_count=n_out,
        or_count=or_gates,
        max_depth=2, avg_fan_in=n_in // 2, avg_fan_out=1.0, has_feedback=0, label=0,
    )


def gen_comparator() -> dict:
    n = random.choice([1, 2, 4])
    xnor_g = n
    and_g  = n - 1 if n > 1 else 0
    total  = xnor_g + and_g + n * 2 + 1
    wires  = xnor_g + and_g * 2 + n * 2 + 1
    return _row_from_values(
        gate_count=total, wire_count=wires,
        input_count=n * 2, output_count=1,
        xnor_count=xnor_g, and_count=and_g,
        max_depth=n + 1, avg_fan_in=1.5, avg_fan_out=1.2, has_feedback=0, label=0,
    )


def gen_parity() -> dict:
    n = random.choice([3, 4, 5, 8])
    xor_g = n - 1
    total = xor_g + n + 1
    wires = xor_g * 2 + n + 1
    return _row_from_values(
        gate_count=total, wire_count=wires,
        input_count=n, output_count=1,
        xor_count=xor_g,
        max_depth=n - 1, avg_fan_in=1.8, avg_fan_out=1.0, has_feedback=0, label=0,
    )


def gen_flip_flop() -> dict:
    kind = random.choice(['d', 'jk', 't', 'sr'])
    has_fb = 1
    if kind == 'd':
        return _row_from_values(
            gate_count=8, wire_count=11, input_count=2, output_count=2,
            nand_count=4,
            max_depth=4, avg_fan_in=1.9, avg_fan_out=1.8, has_feedback=has_fb, label=0,
        )
    if kind == 'jk':
        return _row_from_values(
            gate_count=7, wire_count=9, input_count=3, output_count=2,
            and_count=2, nor_count=2,
            max_depth=4, avg_fan_in=2.0, avg_fan_out=1.9, has_feedback=has_fb, label=0,
        )
    if kind == 't':
        return _row_from_values(
            gate_count=6, wire_count=8, input_count=2, output_count=2,
            xor_count=1, and_count=1, nor_count=2,
            max_depth=4, avg_fan_in=1.9, avg_fan_out=1.9, has_feedback=has_fb, label=0,
        )
    # SR
    return _row_from_values(
        gate_count=6, wire_count=8, input_count=2, output_count=2,
        nor_count=2, and_count=1,
        max_depth=3, avg_fan_in=2.0, avg_fan_out=2.0, has_feedback=has_fb, label=0,
    )


def gen_counter() -> dict:
    n = random.choice([2, 3, 4])
    ff_gates = 6 * n
    total = ff_gates + n * 2 + 1 + 1
    wires = ff_gates * 2 + n * 3
    return _row_from_values(
        gate_count=total, wire_count=wires,
        input_count=n + 1, output_count=n,
        xor_count=n, and_count=n - 1, nand_count=n,
        max_depth=n * 4, avg_fan_in=1.8, avg_fan_out=2.0, has_feedback=1, label=0,
    )


def gen_alu() -> dict:
    n = random.choice([1, 2, 4])
    ops = 4
    sel_g = 2
    total = (5 * n + sel_g) + n * 2 + sel_g + n
    wires = total * 2
    return _row_from_values(
        gate_count=total, wire_count=wires,
        input_count=n * 2 + sel_g + 1, output_count=n + 1,
        and_count=n * 2, or_count=n, xor_count=n, not_count=n,
        max_depth=ops + 1, avg_fan_in=1.9, avg_fan_out=1.5, has_feedback=0, label=0,
    )


def gen_random_clean() -> dict:
    # Wider gate-count range so depth up to 20 is achievable.
    gate_count = _rand(3, 80)
    input_count = _rand(2, 12)
    output_count = _rand(1, max(1, gate_count // 4))
    logic_gates = gate_count - input_count - output_count
    logic_gates = max(1, logic_gates)

    # Distribute gate types
    gate_types = ['and_count', 'or_count', 'not_count', 'nand_count',
                  'nor_count', 'xor_count', 'xnor_count']
    counts = {t: 0 for t in gate_types}
    remainder = logic_gates
    for i, t in enumerate(gate_types):
        if i == len(gate_types) - 1:
            counts[t] = remainder
        else:
            counts[t] = _rand(0, remainder)
            remainder -= counts[t]

    wire_count = _rand(gate_count, min(gate_count * 3, 240))
    # Depth ceiling raised to 20 (matches deepest archetype circuits).
    max_depth  = _rand(2, min(gate_count, 20))
    avg_fan_in  = round(random.uniform(1.2, 2.5), 2)
    avg_fan_out = round(random.uniform(0.8, 3.0), 2)

    return _row_from_values(
        gate_count=gate_count, wire_count=wire_count,
        input_count=input_count, output_count=output_count,
        max_depth=max_depth, avg_fan_in=avg_fan_in, avg_fan_out=avg_fan_out,
        has_feedback=0, label=0,
        **counts,
    )


def gen_random_faulty() -> dict:
    base = gen_random_clean()
    return _faulty_variant(base)


# --- dispatch -----------------------------------------------------------------

GENERATORS = {
    'half_adder':   gen_half_adder,
    'full_adder':   gen_full_adder,
    'ripple_adder': gen_ripple_adder,
    'multiplexer':  gen_multiplexer,
    'decoder':      gen_decoder,
    'encoder':      gen_encoder,
    'comparator':   gen_comparator,
    'parity':       gen_parity,
    'flip_flop':    gen_flip_flop,
    'counter':      gen_counter,
    'alu':          gen_alu,
    'random_clean': gen_random_clean,
    'random_faulty':gen_random_faulty,
}


def generate(n_rows: int) -> list:
    rows = []
    for _ in range(n_rows):
        arch = _weighted_choice(ARCHETYPE_WEIGHTS)
        row  = GENERATORS[arch]()
        rows.append(row)
        # For each clean archetype, randomly inject a fault copy (25% chance)
        if row['label'] == 0 and random.random() < 0.25:
            rows.append(_faulty_variant(row))
    return rows


def main():
    parser = argparse.ArgumentParser(description='Generate circuit training data')
    parser.add_argument('-n', type=int, default=20_000, help='Number of base rows to generate')
    parser.add_argument('--replace', action='store_true', help='Overwrite existing CSV')
    args = parser.parse_args()

    out_path = os.path.join(os.path.dirname(__file__), 'circuit_patterns.csv')
    mode     = 'w' if args.replace or not os.path.exists(out_path) else 'a'
    write_header = (mode == 'w')

    rows = generate(args.n)
    random.shuffle(rows)

    with open(out_path, mode, newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    label_counts = {0: sum(1 for r in rows if r['label'] == 0),
                    1: sum(1 for r in rows if r['label'] == 1)}
    print(f"Wrote {len(rows):,} rows to {out_path}")
    print(f"  Clean (0): {label_counts[0]:,}  Faulty (1): {label_counts[1]:,}")


if __name__ == '__main__':
    main()
