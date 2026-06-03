"""
Shared data parser for all ML models.
Converts raw CSV rows into numeric feature vectors.
"""
import numpy as np
import pandas as pd

GATE_TYPES = ['NONE', 'AND', 'OR', 'NOT', 'NAND', 'NOR', 'XOR', 'XNOR']
GATE_MAP   = {g: i for i, g in enumerate(GATE_TYPES)}
MAX_GATES  = 20
NUM_INPUTS = 4   # A, B, C, D

def encode_gate(gate_str):
    return GATE_MAP.get(str(gate_str).upper(), 0)

def row_to_features(row):
    """
    Convert one CSV row (as dict or Series) to a flat float32 feature vector.

    Layout:
      [0]        depth          (1-20, normalised /20)
      [1]        num_inputs     (1-4,  normalised /4)
      [2..5]     A, B, C, D    (0/1, -1 -> 0)
      [6..65]    for each gate slot (20 slots × 3 features):
                   gate_type_encoded /7
                   src0_normalised   /23   (0..3 = input idx, 4..23 = gate idx, -1 -> 0)
                   src1_normalised   /23
    Total: 6 + 60 = 66 features
    """
    feats = np.zeros(66, dtype=np.float32)

    feats[0] = float(row.get('depth', 1)) / 20.0
    feats[1] = float(row.get('num_inputs', 1)) / 4.0

    for i, inp in enumerate(['A', 'B', 'C', 'D']):
        v = row.get(inp, -1)
        feats[2 + i] = max(0.0, float(v))   # -1 -> 0

    for g in range(MAX_GATES):
        base = 6 + g * 3
        gate_type = str(row.get(f'gate{g}', 'NONE')).upper()
        src0      = row.get(f'g{g}_src0', -1)
        src1      = row.get(f'g{g}_src1', -1)

        feats[base]     = encode_gate(gate_type) / 7.0
        feats[base + 1] = (float(src0) + 1) / 23.0   # -1->0, 0..3=inputs, 4..19=gates
        feats[base + 2] = (float(src1) + 1) / 23.0

    return feats

def count_active_gates(row):
    """Return how many non-NONE gate slots are used."""
    count = 0
    for g in range(MAX_GATES):
        if str(row.get(f'gate{g}', 'NONE')).upper() != 'NONE':
            count += 1
    return count

def load_dataset(csv_path, sample=None):
    """Load CSV and return (X, y) numpy arrays."""
    df = pd.read_csv(csv_path)
    if sample and sample < len(df):
        df = df.sample(n=sample, random_state=42)

    X = np.array([row_to_features(row) for _, row in df.iterrows()], dtype=np.float32)
    y = df['output'].astype(int).values
    return X, y, df