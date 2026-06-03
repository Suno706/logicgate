# simulator.py
from collections import defaultdict, deque


def detect_cycles(gates, wires):
    """
    Detects cycles in the circuit graph.
    Returns (has_cycle: bool, nodes_in_cycles: list)
    """
    gate_ids = {g["id"] for g in gates}
    in_degree = {g["id"]: 0 for g in gates}
    dependents = defaultdict(list)

    for w in wires:
        src = w.get("from_gate") or w.get("fg")
        dst = w.get("to_gate") or w.get("tg")
        if src in gate_ids and dst in gate_ids:
            dependents[src].append(dst)
            in_degree[dst] += 1

    # Try topological sort
    queue = deque([gid for gid, deg in in_degree.items() if deg == 0])
    processed = set()

    while queue:
        cur = queue.popleft()
        processed.add(cur)
        for nb in dependents[cur]:
            in_degree[nb] -= 1
            if in_degree[nb] == 0:
                queue.append(nb)

    # Any unprocessed nodes are in a cycle
    cyclic_nodes = [gid for gid in gate_ids if gid not in processed]
    return len(cyclic_nodes) > 0, cyclic_nodes


def validate_circuit(gates, wires):
    """
    Validates circuit structure before simulation.
    Returns (is_valid: bool, errors: list, warnings: list)
    """
    errors = []
    warnings = []

    # Check for empty gates
    if not gates:
        errors.append("Circuit has no gates")
        return False, errors, warnings

    # Check for duplicate gate IDs
    gate_ids = [g.get("id") for g in gates]
    if len(gate_ids) != len(set(gate_ids)):
        errors.append("Duplicate gate IDs detected")
        return False, errors, warnings

    # Check for cycles
    has_cycle, cyclic_nodes = detect_cycles(gates, wires)
    if has_cycle:
        warnings.append(f"Circular dependency detected: gates {cyclic_nodes}")

    # Validate gate types. The backend simulator only fully evaluates the
    # standard combinational gates; the composite/sequential/source types
    # introduced for the UI sidebar are accepted here but evaluated client-
    # side (the frontend routes such circuits to its own simulator).
    valid_types = {
        # standard
        "INPUT", "OUTPUT", "NOT", "AND", "OR", "NAND", "NOR", "XOR", "XNOR",
        "BUS", "CLOCK",
        # power & indicators
        "VCC", "GND", "LED",
        # composites
        "HA", "FA", "MUX4", "DEC24", "ADD4",
        # sequential
        "DFF", "TFF", "JKFF", "REG4",
    }
    for g in gates:
        t = g.get("type", "").upper()
        if t not in valid_types:
            errors.append(f"Unknown gate type: {g.get('type')}")

    # Check for dangling wires
    gate_id_set = set(gid for gid in gate_ids)
    for w in wires:
        src = w.get("from_gate") or w.get("fg")
        dst = w.get("to_gate") or w.get("tg")
        if src and src not in gate_id_set:
            errors.append(f"Wire references non-existent source gate: {src}")
        if dst and dst not in gate_id_set:
            errors.append(f"Wire references non-existent destination gate: {dst}")

    return len(errors) == 0, errors, warnings


def evaluate_gate(gate_type, inputs):
    """
    Evaluate a logic gate given its type and a list of binary inputs.
    All inputs are normalized to 0 or 1 before evaluation.
    """
    t = gate_type.upper()

    # Normalize inputs to strict binary (handles any non-binary upstream values)
    inputs = [1 if i else 0 for i in inputs]

    if t in ("INPUT", "CLOCK"):
        return inputs[0] if inputs else 0
    if t == "VCC":
        return 1
    if t == "GND":
        return 0
    if t in ("OUTPUT", "LED"):
        return inputs[0] if inputs else 0
    if t == "BUS":
        return inputs[0] if inputs else 0   # passes through to all output pins
    if t == "NOT":
        return 1 - inputs[0] if inputs else 1
    if t == "AND":
        return int(all(i == 1 for i in inputs)) if inputs else 0
    if t == "OR":
        return int(any(i == 1 for i in inputs)) if inputs else 0
    if t == "NAND":
        return int(not all(i == 1 for i in inputs)) if inputs else 1
    if t == "NOR":
        return int(not any(i == 1 for i in inputs)) if inputs else 1
    if t == "XOR":
        r = 0
        for i in inputs:
            r ^= i
        return r
    if t == "XNOR":
        r = 0
        for i in inputs:
            r ^= i
        return int(not r)

    # Unknown gate type  -  default to 0
    print(f"Warning: unknown gate type '{gate_type}', defaulting output to 0")
    return 0


def topological_sort(gates, wires):
    """
    Kahn's algorithm topological sort.
    Returns a valid evaluation order.
    Detects and reports cycles (feedback loops).
    """
    gate_ids   = {g["id"] for g in gates}
    in_degree  = {g["id"]: 0 for g in gates}
    dependents = defaultdict(list)   # src_id -> [dst_id, ...]

    for w in wires:
        # Support both 'from_gate'/'to_gate' (backend) and 'fg'/'tg' (frontend shorthand)
        src = w.get("from_gate") or w.get("fg")
        dst = w.get("to_gate")   or w.get("tg")

        if src in gate_ids and dst in gate_ids:
            dependents[src].append(dst)
            in_degree[dst] += 1

    # Start with all source nodes (no incoming edges)
    queue = deque([gid for gid, deg in in_degree.items() if deg == 0])
    order = []

    while queue:
        cur = queue.popleft()
        order.append(cur)
        for nb in dependents[cur]:
            in_degree[nb] -= 1
            if in_degree[nb] == 0:
                queue.append(nb)

    # -- Cycle detection ------------------------------------------------------
    if len(order) < len(gate_ids):
        cyclic_ids = [gid for gid in gate_ids if gid not in set(order)]
        print(
            f"Warning: cycle detected in circuit. "
            f"The following gates are part of a feedback loop and will hold 0: "
            f"{cyclic_ids}"
        )

    return order


def simulate_circuit(gates, wires):
    """
    Simulate the full circuit and return a dict of {gate_id: output_value}.

    Handles:
      - INPUT and CLOCK gates (read their 'value' field)
      - Standard logic gates: NOT, AND, OR, NAND, NOR, XOR, XNOR
      - Pass-through gates: OUTPUT, BUS
      - Unconnected input pins (default to 0)
      - Multiple wires targeting the same pin (warns, uses last writer)
      - Cyclic circuits (warns, affected gates hold 0)
      - Unknown gate types (warns, output 0)
    """

    gate_map = {g["id"]: g for g in gates}

    # input_map[gate_id][pin_index] = source_gate_id
    input_map = defaultdict(dict)

    for w in wires:
        src     = w.get("from_gate") or w.get("fg")
        dst     = w.get("to_gate")   or w.get("tg")
        pin_raw = w.get("to_pin")    if "to_pin" in w else w.get("tp")

        if pin_raw is None:
            pin_raw = 0
        try:
            pin_idx = int(pin_raw)
        except (ValueError, TypeError):
            pin_idx = 0

        if src and dst:
            # -- Bug 4 fix: warn on duplicate wire to same pin ---------------
            if pin_idx in input_map[dst]:
                print(
                    f"Warning: pin {pin_idx} of gate '{dst}' already has a driver "
                    f"('{input_map[dst][pin_idx]}'). Overwriting with '{src}'."
                )
            input_map[dst][pin_idx] = src

    order = topological_sort(gates, wires)

    # Pre-populate all gates with 0 so unvisited / cyclic gates are safe to read
    values = {g["id"]: 0 for g in gates}

    # Expected number of input pins per gate type
    # -- Bug 1 fix: CLOCK added alongside INPUT -------------------------------
    gate_input_counts = {
        "INPUT":  0,
        "CLOCK":  0,
        "VCC":    0, "GND":    0,
        "LED":    1,
        "NOT":    1,
        "BUS":    1,
        "OUTPUT": 1,
        "AND":    2,
        "OR":     2,
        "NAND":   2,
        "NOR":    2,
        "XOR":    2,
        "XNOR":   2,
        # composite + sequential  -  accepted here but evaluated client-side
        "HA":     2, "FA":   3, "MUX4":  6, "DEC24": 2, "ADD4": 9,
        "DFF":    2, "TFF":  2, "JKFF":  3, "REG4":  5,
    }

    for gid in order:
        gate = gate_map.get(gid)
        if not gate:
            continue

        t = gate["type"].upper()

        # -- Bug 1 fix: CLOCK handled exactly like INPUT ----------------------
        if t in ("INPUT", "CLOCK"):
            values[gid] = 1 if int(gate.get("value", 0)) else 0
            continue

        pins = input_map.get(gid, {})

        # For known types use the fixed count; for unknown types infer from
        # actually connected pins (avoids crashes on custom / future gate types)
        if t in gate_input_counts:
            num_inputs = gate_input_counts[t]
        else:
            num_inputs = (max(pins.keys()) + 1) if pins else 0

        # -- Bug 3 fix: normalize inputs to strict binary ---------------------
        inputs = [
            1 if values.get(pins.get(p), 0) else 0
            for p in range(num_inputs)
        ]

        values[gid] = evaluate_gate(t, inputs)

    return values