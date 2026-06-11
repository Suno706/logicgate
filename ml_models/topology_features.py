"""
Graph-structural feature extractor for digital circuits.

Given a circuit `{"gates": [...], "wires": [...]}`, returns a fixed-length
numeric vector that captures the topology — gate-type counts, fan-in/out,
depth, presence of XOR/feedback/branching, etc. The classifier consumes
these vectors to predict what kind of circuit the user is building.

Design notes:
  - Features must be permutation-invariant in gate IDs so that two
    structurally identical circuits with different ids yield the same
    vector. This makes the augmentation in dataset generation effective.
  - Features must be normalised when sensible (e.g. gate-type fractions)
    so a 4-gate adder and a 10-gate adder both look "adder-like".
  - Order of FEATURE_NAMES is the canonical column order; never reorder
    without re-training, or model weights misalign with feature columns.
"""
from collections import Counter, defaultdict
from typing import Dict, List, Sequence

# Canonical type lists. Anything not in here lumps into "OTHER" or is
# ignored depending on context.
_LOGIC = ("AND", "OR", "NOT", "NAND", "NOR", "XOR", "XNOR", "BUF")
_IO    = ("INPUT", "OUTPUT", "CLOCK", "VCC", "GND", "LED")
_MACRO = ("HA", "FA", "MUX2", "MUX4", "DEC24", "DEC38", "ENC42",
          "DFF", "TFF", "JKFF", "SRLATCH", "REG4")

FEATURE_NAMES: List[str] = [
    # Size / shape
    "n_gates", "n_wires", "n_logic", "n_input", "n_output",
    "wire_to_gate_ratio", "io_balance",
    # Per-type fractions (out of n_logic, so adder vs comparator separates)
    "frac_and", "frac_or", "frac_not", "frac_nand", "frac_nor",
    "frac_xor", "frac_xnor", "frac_buf",
    # Macro indicators (0/1) — strong signal when present
    "has_ha", "has_fa", "has_mux2", "has_mux4",
    "has_dff", "has_tff", "has_jkff", "has_srlatch",
    # Connectivity
    "max_fanout", "max_fanin", "avg_fanout", "avg_fanin",
    "n_unconnected_logic",
    # Depth / cycles
    "depth", "has_cycle",
    # Common derived signals
    "xor_or_xnor_present", "nand_or_nor_present",
    "is_combinational",      # no flip-flop / latch / clock
    "input_to_output_ratio", # nIn / nOut
]


def _wire_endpoints(w: dict):
    """Return (src_id, dst_id) tolerating multiple wire schemas."""
    src = w.get("from") or w.get("from_gate") or w.get("fg")
    dst = w.get("to")   or w.get("to_gate")   or w.get("tg")
    return src, dst


def _build_adjacency(gates: Sequence[dict], wires: Sequence[dict]):
    gate_ids = {g["id"] for g in gates}
    fanout: Dict[str, list] = defaultdict(list)  # id -> [downstream ids]
    fanin:  Dict[str, list] = defaultdict(list)  # id -> [upstream ids]
    for w in wires:
        s, d = _wire_endpoints(w)
        if s in gate_ids and d in gate_ids:
            fanout[s].append(d)
            fanin[d].append(s)
    return fanout, fanin


def _longest_path_depth(gates, fanout) -> int:
    """Longest topological-order path length. 0 for empty/cyclic graphs."""
    if not gates:
        return 0
    in_degree = {g["id"]: 0 for g in gates}
    for src, dsts in fanout.items():
        for d in dsts:
            if d in in_degree:
                in_degree[d] += 1
    # Kahn's algorithm with depth tracking
    from collections import deque
    q   = deque([i for i, deg in in_degree.items() if deg == 0])
    depth = {i: 0 for i in in_degree}
    visited = 0
    while q:
        n = q.popleft()
        visited += 1
        for c in fanout.get(n, []):
            if depth[c] < depth[n] + 1:
                depth[c] = depth[n] + 1
            in_degree[c] -= 1
            if in_degree[c] == 0:
                q.append(c)
    if visited < len(in_degree):
        # Cycle — caller will mark has_cycle separately.
        return 0
    return max(depth.values()) if depth else 0


def _has_cycle(gates, fanout) -> bool:
    if not gates:
        return False
    in_degree = {g["id"]: 0 for g in gates}
    for src, dsts in fanout.items():
        for d in dsts:
            if d in in_degree:
                in_degree[d] += 1
    from collections import deque
    q = deque([i for i, deg in in_degree.items() if deg == 0])
    visited = 0
    while q:
        n = q.popleft()
        visited += 1
        for c in fanout.get(n, []):
            in_degree[c] -= 1
            if in_degree[c] == 0:
                q.append(c)
    return visited < len(in_degree)


def extract(circuit: dict) -> List[float]:
    """
    Reduce a circuit to FEATURE_NAMES-aligned vector of floats. Order is
    stable; consumers (training, inference) should rely on FEATURE_NAMES
    rather than positional knowledge.
    """
    gates: List[dict] = list(circuit.get("gates", []))
    wires: List[dict] = list(circuit.get("wires", []))

    # Type bookkeeping
    types = Counter((g.get("type", "") or "").upper() for g in gates)
    n_gates  = len(gates)
    n_wires  = len(wires)
    n_logic  = sum(types[t] for t in _LOGIC)
    n_input  = types.get("INPUT", 0) + types.get("CLOCK", 0)
    n_output = types.get("OUTPUT", 0)

    fanout, fanin = _build_adjacency(gates, wires)

    def frac(t: str) -> float:
        return (types.get(t, 0) / n_logic) if n_logic else 0.0

    fan_out_counts = [len(fanout.get(g["id"], [])) for g in gates]
    fan_in_counts  = [len(fanin.get(g["id"], []))  for g in gates]

    has_cyc = _has_cycle(gates, fanout)
    depth   = _longest_path_depth(gates, fanout)

    # Logic gates with zero wires touching them are "unconnected" — a useful
    # signal because complete circuits rarely have such drift gates.
    n_unconnected_logic = sum(
        1 for g in gates
        if (g.get("type", "").upper() in _LOGIC)
        and (not fanin.get(g["id"]) and not fanout.get(g["id"]))
    )

    is_combinational = (
        types.get("CLOCK", 0) == 0
        and types.get("DFF",  0) == 0
        and types.get("TFF",  0) == 0
        and types.get("JKFF", 0) == 0
        and types.get("SRLATCH", 0) == 0
        and not has_cyc
    )

    feats = [
        # Size / shape
        n_gates,
        n_wires,
        n_logic,
        n_input,
        n_output,
        (n_wires / n_gates) if n_gates else 0.0,
        (n_input - n_output) / max(n_input + n_output, 1),
        # Per-type fractions
        frac("AND"), frac("OR"), frac("NOT"), frac("NAND"), frac("NOR"),
        frac("XOR"), frac("XNOR"), frac("BUF"),
        # Macro indicators
        1.0 if types.get("HA")      else 0.0,
        1.0 if types.get("FA")      else 0.0,
        1.0 if types.get("MUX2")    else 0.0,
        1.0 if types.get("MUX4")    else 0.0,
        1.0 if types.get("DFF")     else 0.0,
        1.0 if types.get("TFF")     else 0.0,
        1.0 if types.get("JKFF")    else 0.0,
        1.0 if types.get("SRLATCH") else 0.0,
        # Connectivity stats
        max(fan_out_counts) if fan_out_counts else 0,
        max(fan_in_counts)  if fan_in_counts  else 0,
        (sum(fan_out_counts) / len(fan_out_counts)) if fan_out_counts else 0.0,
        (sum(fan_in_counts)  / len(fan_in_counts))  if fan_in_counts  else 0.0,
        n_unconnected_logic,
        # Depth / cycles
        depth,
        1.0 if has_cyc else 0.0,
        # Derived flags
        1.0 if (types.get("XOR", 0) + types.get("XNOR", 0)) > 0 else 0.0,
        1.0 if (types.get("NAND", 0) + types.get("NOR", 0))  > 0 else 0.0,
        1.0 if is_combinational else 0.0,
        (n_input / n_output) if n_output else float(n_input),
    ]

    assert len(feats) == len(FEATURE_NAMES), (
        f"feature length drift: {len(feats)} vs {len(FEATURE_NAMES)}. "
        "Update FEATURE_NAMES and re-train."
    )
    return feats
