"""
Schema-A row generator for circuit_patterns.csv.

Writes rows matching what ml_models/data_parser.py actually loads:
    depth, num_inputs, A, B, C, D,
    gate0, g0_src0, g0_src1,
    gate1, g1_src0, g1_src1,
    ...
    gate19, g19_src0, g19_src1,
    output

Each row encodes a randomly-generated small circuit (up to 20 gates),
the input vector (A..D), and the simulated output.

Run:
    python data/generate_training_rows.py             # default: top up to 200,000 rows
    python data/generate_training_rows.py -n 50000    # add N rows
    python data/generate_training_rows.py --target 250000
"""
import argparse
import csv
import os
import random

GATE_TYPES = ['AND', 'OR', 'NOT', 'NAND', 'NOR', 'XOR', 'XNOR']
MAX_GATES  = 20
NUM_INPUT_SLOTS = 4   # A, B, C, D
INPUT_OFFSET    = 0   # input idx 0..3
GATE_OFFSET     = 4   # gate idx maps to 4..23 in the source-id space

FIELDNAMES = ['depth', 'num_inputs', 'A', 'B', 'C', 'D']
for g in range(MAX_GATES):
    FIELDNAMES += [f'gate{g}', f'g{g}_src0', f'g{g}_src1']
FIELDNAMES.append('output')


def _eval_gate(gtype, a, b):
    if gtype == 'AND':  return int(a == 1 and b == 1)
    if gtype == 'OR':   return int(a == 1 or b == 1)
    if gtype == 'NOT':  return int(a != 1)
    if gtype == 'NAND': return int(not (a == 1 and b == 1))
    if gtype == 'NOR':  return int(not (a == 1 or b == 1))
    if gtype == 'XOR':  return int((a == 1) ^ (b == 1))
    if gtype == 'XNOR': return int(not ((a == 1) ^ (b == 1)))
    return 0


def _gen_row(depth_target: int):
    """Generate one valid circuit row of approximately the requested depth."""
    num_inputs = random.randint(1, NUM_INPUT_SLOTS)
    input_vals = [random.randint(0, 1) for _ in range(num_inputs)] + [-1] * (NUM_INPUT_SLOTS - num_inputs)

    # Build a layered DAG.  Layer 0 = inputs.  Each layer can draw from prior layers.
    n_gates = min(MAX_GATES, max(1, depth_target + random.randint(0, depth_target)))
    layers = []                # list[list[gate_index_in_circuit]]
    gates_out = {}             # circuit gate idx -> computed output value
    gate_records = []          # in-order list of (type, src0, src1)

    # We'll spread n_gates across `depth_target` layers (last gate is the output).
    layer_sizes = []
    remaining = n_gates
    for li in range(depth_target):
        if li == depth_target - 1:
            layer_sizes.append(remaining)
        else:
            sz = max(1, remaining // (depth_target - li))
            layer_sizes.append(sz)
            remaining -= sz
    layer_sizes = [s for s in layer_sizes if s > 0]

    gate_counter = 0
    prev_pool = list(range(num_inputs))    # source ids drawn from inputs
    for li, sz in enumerate(layer_sizes):
        layer_ids = []
        for _ in range(sz):
            if gate_counter >= MAX_GATES:
                break
            gtype = random.choice(GATE_TYPES)
            # Source picks: prev_pool is in "global source id" space
            #   - 0..num_inputs-1 -> input idx
            #   - GATE_OFFSET + gate_counter_id -> gate idx (encoded as 4+idx)
            src0 = random.choice(prev_pool)
            if gtype == 'NOT':
                src1 = -1
            else:
                src1 = random.choice(prev_pool)

            # Compute the output of this gate now
            def read(sid):
                if sid < 0: return 0
                if sid < num_inputs:
                    return input_vals[sid]
                return gates_out.get(sid - GATE_OFFSET, 0)

            val = _eval_gate(gtype, read(src0), read(src1))
            this_id = gate_counter
            gates_out[this_id] = val
            gate_records.append((gtype, src0, src1))
            layer_ids.append(GATE_OFFSET + this_id)
            gate_counter += 1
        if not layer_ids:
            break
        layers.append(layer_ids)
        # Next layer draws from all earlier layers and inputs (richer DAG)
        prev_pool = list(range(num_inputs)) + [g for layer in layers for g in layer]

    # The last gate that was added is the circuit output
    if not gate_records:
        return None
    final_gate_idx = gate_counter - 1
    output = gates_out[final_gate_idx]

    # Build the CSV row.  Unused slots stay NONE / -1.
    row = {
        'depth':       min(20, max(1, depth_target)),
        'num_inputs':  num_inputs,
        'A': input_vals[0], 'B': input_vals[1], 'C': input_vals[2], 'D': input_vals[3],
        'output':      output,
    }
    for g in range(MAX_GATES):
        if g < len(gate_records):
            gt, s0, s1 = gate_records[g]
            row[f'gate{g}']    = gt
            row[f'g{g}_src0']  = s0
            row[f'g{g}_src1']  = s1
        else:
            row[f'gate{g}']    = 'NONE'
            row[f'g{g}_src0']  = -1
            row[f'g{g}_src1']  = -1
    return row


def generate(n: int):
    rows = []
    while len(rows) < n:
        # Heavily sample the full 1..20 depth range so the model sees every depth bucket.
        depth = random.randint(1, 20)
        row = _gen_row(depth)
        if row:
            rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description='Top up Schema-A training data.')
    parser.add_argument('-n', type=int, default=None,
                        help='Number of rows to append. If unset, top up to --target.')
    parser.add_argument('--target', type=int, default=200_000,
                        help='Total desired row count (default 200,000).')
    parser.add_argument('--replace', action='store_true',
                        help='Overwrite the CSV instead of appending.')
    args = parser.parse_args()

    out_path = os.path.join(os.path.dirname(__file__), 'circuit_patterns.csv')

    if args.replace or not os.path.exists(out_path):
        existing = 0
        mode = 'w'
    else:
        with open(out_path, 'r', encoding='utf-8') as f:
            existing = sum(1 for _ in f) - 1  # minus header
        mode = 'a'

    n_to_add = args.n if args.n is not None else max(0, args.target - existing)
    if n_to_add <= 0:
        print(f"Already at {existing:,} rows; nothing to do.")
        return

    print(f"Existing rows: {existing:,}; generating {n_to_add:,} more…")
    rows = generate(n_to_add)
    random.shuffle(rows)

    with open(out_path, mode, newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if mode == 'w':
            writer.writeheader()
        writer.writerows(rows)

    # Depth distribution sanity
    from collections import Counter
    c = Counter(r['depth'] for r in rows)
    print(f"Wrote {len(rows):,} rows.  New depth spread (new rows only):")
    for d in sorted(c):
        print(f"  depth {d:2d}: {c[d]:,}")
    print(f"Total CSV rows: {existing + len(rows):,}")


if __name__ == '__main__':
    main()
