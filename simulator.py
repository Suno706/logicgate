"""
simulator.py — single-pass evaluator for a combinational/sequential
gate-level circuit.

The simulator treats a circuit as a directed graph of gates connected
by wires. Evaluation is one pass in topological order:

    1. Validate inputs and detect feedback loops.
    2. Compute a valid evaluation order via Kahn's algorithm. Gates with
       no incoming wires (INPUT, CLOCK, VCC, GND) come first; downstream
       gates fall in dependency order.
    3. Walk the order, reading each gate's input pins from the
       already-computed upstream values and writing the gate's output.

Why one-shot, not iterative-until-stable?
    For purely combinational circuits, one topological pass is exact.
    For sequential elements (D-/JK-/T-FF, SR latch, REG4), this engine
    evaluates the "next state" once — Q reflects the inputs as if the
    clock just ticked. That keeps the simulator cheap and predictable;
    a multi-cycle simulator would need a separate engine.

Wire schema flexibility:
    Wires accept both 'from_gate'/'to_gate'/'from_pin'/'to_pin' (verbose,
    used by the backend) and 'fg'/'tg'/'fp'/'tp' (shorthand, used in
    some JSON dumps). Helper readers normalise this so callers don't
    care which form they emit.

Multi-output gate convention:
    A macro gate G with multiple outputs writes its primary output
    under the key  values[G]  and each additional pin under the key
      values["G:1"], values["G:2"], …
    Wires that target pin > 0 of G resolve to the corresponding "G:p"
    entry. This matches the multi-pin convention used elsewhere in the
    project (api.ts, boolean_synth.py).
"""

from collections import defaultdict, deque


def _wire_endpoints(wire):
    """Extract (src_gate_id, dst_gate_id) from a wire dict, accepting
    either the verbose ('from_gate'/'to_gate') or shorthand ('fg'/'tg')
    schema. Returns (None, None) for malformed wires so callers can skip
    them without raising."""
    src = wire.get("from_gate") or wire.get("fg")
    dst = wire.get("to_gate")   or wire.get("tg")
    return src, dst


def detect_cycles(gates, wires):
    """
    Identify any gate that's part of a feedback loop.

    Returns (has_cycle: bool, gates_in_cycle: list).

    Algorithm: try Kahn's topological sort. Gates that can't be reached
    from any source (i.e. their in-degree never falls to zero) must be
    part of a cycle. This is the same primitive used by
    `topological_sort` below; we keep them as separate functions because
    callers like the fault detector want only the cycle membership,
    not the evaluation order.
    """
    gate_ids       = {g["id"] for g in gates}
    in_degree      = {gid: 0 for gid in gate_ids}
    downstream_of  = defaultdict(list)   # src_gate_id -> [dst_gate_id, ...]

    for wire in wires:
        src, dst = _wire_endpoints(wire)
        if src in gate_ids and dst in gate_ids:
            downstream_of[src].append(dst)
            in_degree[dst] += 1

    # Kahn's: peel off zero-in-degree nodes, then their successors, etc.
    ready    = deque([gid for gid, deg in in_degree.items() if deg == 0])
    settled  = set()
    while ready:
        gate_id = ready.popleft()
        settled.add(gate_id)
        for dst in downstream_of[gate_id]:
            in_degree[dst] -= 1
            if in_degree[dst] == 0:
                ready.append(dst)

    # Whatever didn't settle is reachable only through a cycle.
    gates_in_cycle = [gid for gid in gate_ids if gid not in settled]
    return len(gates_in_cycle) > 0, gates_in_cycle


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
        "DFF", "TFF", "JKFF", "REG4", "SRLATCH",
        # combinational macros (single-block versions)
        "MUX2", "DEC38", "ENC42", "CMP2",
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

    # Composite / sequential macros: return primary (pin 0) output.
    # Multi-pin outputs are emitted by evaluate_macro_pins() and stored
    # under "<gate_id>:<pin>" keys for wires that target pin > 0.
    if t in ("HA", "FA", "DFF", "JKFF", "TFF", "SRLATCH",
             "MUX2", "MUX4", "DEC24", "DEC38", "ENC42", "CMP2", "REG4"):
        return evaluate_macro_pins(t, inputs)[0]

    # Unknown gate type  -  default to 0
    print(f"Warning: unknown gate type '{gate_type}', defaulting output to 0")
    return 0


def evaluate_macro_pins(t, inputs):
    """
    Returns the list of per-pin output values for macro components.
    Flip-flops are evaluated *combinationally* (next-state) because the
    simulator is a one-shot evaluator without persistent state — Q reflects
    what the FF would latch on the next clock edge.
    """
    pad = lambda i: 1 if i < len(inputs) and inputs[i] else 0
    if t == "HA":
        a, b = pad(0), pad(1)
        return [a ^ b, a & b]                                   # S, C
    if t == "FA":
        a, b, ci = pad(0), pad(1), pad(2)
        s  = a ^ b ^ ci
        co = (a & b) | (b & ci) | (a & ci)
        return [s, co]                                          # S, Co
    if t == "DFF":
        d = pad(0)                                              # next Q = D
        return [d, 1 - d]                                       # Q, Q̅
    if t == "JKFF":
        j, k = pad(0), pad(1)
        # Stateless approximation: assume previous Q = 0. The JK truth table:
        #   J K | Q(next)
        #   0 0 |  Q       hold  (0 here)
        #   0 1 |  0       reset
        #   1 0 |  1       set
        #   1 1 |  Q̅       toggle (1 here, since 0 → NOT 0)
        # Collapses to Q(next) = J under the old_Q = 0 assumption.
        return [j, 1 - j]                                       # Q, Q̅
    if t == "TFF":
        t_in = pad(0)
        return [t_in, 1 - t_in]                                 # toggle from 0
    if t == "SRLATCH":
        s, r = pad(0), pad(1)
        if s and not r: q = 1
        elif r and not s: q = 0
        elif s and r:    q = 0   # invalid — convention
        else:            q = 0   # hold (stateless: assume 0)
        return [q, 1 - q]                                       # Q, Q̅

    if t == "MUX2":
        a, b, s = pad(0), pad(1), pad(2)
        return [b if s else a]                                  # Y
    if t == "MUX4":
        d = [pad(0), pad(1), pad(2), pad(3)]
        s0, s1 = pad(4), pad(5)
        sel = (s1 << 1) | s0
        return [d[sel]]                                         # Y
    if t == "DEC24":
        a, b = pad(0), pad(1)
        sel = (a << 1) | b
        return [1 if i == sel else 0 for i in range(4)]         # Y0..Y3
    if t == "DEC38":
        a, b, c = pad(0), pad(1), pad(2)
        sel = (a << 2) | (b << 1) | c
        return [1 if i == sel else 0 for i in range(8)]         # Y0..Y7
    if t == "ENC42":
        # 4-to-2 priority encoder; I3 highest priority.
        i0, i1, i2, i3 = pad(0), pad(1), pad(2), pad(3)
        if   i3: y1, y0 = 1, 1
        elif i2: y1, y0 = 1, 0
        elif i1: y1, y0 = 0, 1
        else:    y1, y0 = 0, 0
        return [y0, y1]                                         # Y0, Y1
    if t == "CMP2":
        a0, a1, b0, b1 = pad(0), pad(1), pad(2), pad(3)
        return [1 if (a0 == b0 and a1 == b1) else 0]            # EQ
    if t == "REG4":
        # 4-bit register: 4 D-FFs sharing CLK. Stateless next-state: Q = D.
        # CLK (pad(4)) is not read in the combinational approximation.
        return [pad(0), pad(1), pad(2), pad(3)]                 # Q0..Q3
    return [0]


def topological_sort(gates, wires):
    """
    Produce a valid evaluation order via Kahn's algorithm.

    Gates with no incoming wires (sources: INPUT, CLOCK, VCC, GND)
    appear first; downstream gates follow once all their drivers have
    been emitted. Cycles are surfaced via a print() warning so the
    caller's logs explain why some gates will hold 0 in the result.

    Returns a list of gate ids in evaluation order. If the circuit has
    cycles, only the acyclic portion is returned — `simulate_circuit`
    pre-fills the dict with zeros so cyclic gates still read safely.
    """
    gate_ids       = {g["id"] for g in gates}
    in_degree      = {gid: 0 for gid in gate_ids}
    downstream_of  = defaultdict(list)   # src_gate_id -> [dst_gate_id, ...]

    for wire in wires:
        src, dst = _wire_endpoints(wire)
        if src in gate_ids and dst in gate_ids:
            downstream_of[src].append(dst)
            in_degree[dst] += 1

    ready             = deque([gid for gid, deg in in_degree.items() if deg == 0])
    evaluation_order  = []

    while ready:
        gate_id = ready.popleft()
        evaluation_order.append(gate_id)
        for dst in downstream_of[gate_id]:
            in_degree[dst] -= 1
            if in_degree[dst] == 0:
                ready.append(dst)

    # Cycle report — surfaced as a warning rather than an exception so
    # the rest of the circuit still evaluates. Cyclic gates default to
    # zero in `simulate_circuit` via its pre-fill pass.
    if len(evaluation_order) < len(gate_ids):
        cyclic_ids = [gid for gid in gate_ids if gid not in set(evaluation_order)]
        print(
            f"Warning: cycle detected in circuit. "
            f"The following gates are part of a feedback loop and will hold 0: "
            f"{cyclic_ids}"
        )

    return evaluation_order


# Expected number of input pins per gate type. Lookup table kept at
# module scope so we don't rebuild it on every simulate_circuit call.
# Composite + sequential entries are accepted here even though their
# *evaluation* lives in evaluate_macro_pins — keeping the count co-located
# with the primitives means there's one place to check when adding a
# new gate.
_PINS_PER_GATE = {
    # Sources — no inputs.
    "INPUT":  0,
    "CLOCK":  0,
    "VCC":    0,
    "GND":    0,
    # Single-input sinks and inverters.
    "LED":    1,
    "NOT":    1,
    "BUS":    1,
    "OUTPUT": 1,
    # Standard combinational gates.
    "AND":    2,
    "OR":     2,
    "NAND":   2,
    "NOR":    2,
    "XOR":    2,
    "XNOR":   2,
    # Composite combinational macros.
    "HA":     2,   # half adder            (A, B)
    "FA":     3,   # full adder            (A, B, Cin)
    "MUX2":   3,   # 2-to-1 mux            (A, B, S)
    "MUX4":   6,   # 4-to-1 mux            (D0..D3, S0, S1)
    "DEC24":  2,   # 2-to-4 decoder        (S0, S1)
    "DEC38":  3,   # 3-to-8 decoder        (S0..S2)
    "ENC42":  4,   # 4-to-2 encoder        (D0..D3)
    "CMP2":   4,   # 2-bit comparator      (A1, A0, B1, B0)
    "ADD4":   9,   # 4-bit adder           (A0..A3, B0..B3, Cin)
    # Sequential elements — evaluated combinationally, see module docstring.
    "DFF":    2,   # D flip-flop           (D, CLK)
    "TFF":    2,   # T flip-flop           (T, CLK)
    "JKFF":   3,   # JK flip-flop          (J, K, CLK)
    "REG4":   5,   # 4-bit register        (D0..D3, CLK)
    "SRLATCH":2,   # SR latch              (S, R)
}

# Gates whose evaluation returns more than one output pin and must be
# routed through evaluate_macro_pins.
_MACRO_GATES = frozenset((
    "HA", "FA", "DFF", "JKFF", "TFF", "SRLATCH",
    "MUX2", "MUX4", "DEC24", "DEC38", "ENC42", "CMP2", "REG4",
))


def simulate_circuit(gates, wires):
    """
    Evaluate a complete circuit in one pass and return the output values.

    Args:
        gates: list of gate dicts. Each gate has 'id', 'type', and for
               sources an integer 'value' field that's already been set
               by the caller (the UI, the truth-table runner, etc).
        wires: list of wire dicts mapping (src_gate, src_pin) ->
               (dst_gate, dst_pin). Both verbose and shorthand schemas
               are accepted (see module docstring).

    Returns:
        A dict keyed by gate id (and "id:pin" for multi-output macros).
        Every gate appears in the result — gates we never reached and
        gates inside a feedback loop both default to 0, so callers can
        always read a value without a KeyError check.

    Behaviour notes:
      * Multiple wires landing on the same input pin: a warning is
        printed and the last-arriving writer wins. The caller would
        normally have caught this in fault analysis, but we don't make
        it fatal — the simulator's job is to produce numbers, not
        enforce design rules.
      * Unknown gate types: handled by inferring pin count from the
        wires actually present, then printing a warning and returning 0.
        This keeps the engine forward-compatible with new macro types
        the boolean synthesiser might add without breaking immediately.
    """
    gate_map = {g["id"]: g for g in gates}

    # drivers[dst_gate_id][input_pin] = (src_gate_id, src_output_pin)
    # We resolve to per-pin keys (id:pin) at read time so multi-output
    # macros routed to different downstream pins still work.
    drivers = defaultdict(dict)

    for wire in wires:
        src, dst = _wire_endpoints(wire)
        dst_pin_raw = wire.get("to_pin",   wire.get("tp"))
        src_pin_raw = wire.get("from_pin", wire.get("fp"))

        # Defensive int-coercion. Wires can come from third-party callers
        # (tests, NL-built circuits) that occasionally pass strings.
        try:    dst_pin = int(dst_pin_raw) if dst_pin_raw is not None else 0
        except (ValueError, TypeError): dst_pin = 0
        try:    src_pin = int(src_pin_raw) if src_pin_raw is not None else 0
        except (ValueError, TypeError): src_pin = 0

        if src and dst:
            if dst_pin in drivers[dst]:
                print(
                    f"Warning: pin {dst_pin} of gate '{dst}' already has a driver "
                    f"('{drivers[dst][dst_pin]}'). Overwriting with '{src}'."
                )
            drivers[dst][dst_pin] = (src, src_pin)

    evaluation_order = topological_sort(gates, wires)

    # Pre-fill so unvisited / cyclic gates are safe to read as 0.
    values = {g["id"]: 0 for g in gates}

    def read_pin(dst_pins, pin):
        """Read input `pin` of the current gate, resolving src multi-output."""
        entry = dst_pins.get(pin)
        if entry is None:
            return 0
        src_id, src_pin = entry
        # Multi-output macros write per-pin values under "id:pin"; fall
        # back to the primary "id" key for single-output gates.
        v = values.get(f"{src_id}:{src_pin}")
        if v is None:
            v = values.get(src_id, 0)
        # Strict binary normalisation. Eliminates 0/1 drift if any caller
        # stashed a non-binary value (e.g. None) for an unconnected source.
        return 1 if v else 0

    for gate_id in evaluation_order:
        gate = gate_map.get(gate_id)
        if not gate:
            continue

        gate_type = gate["type"].upper()

        # Sources read their pre-set 'value' field directly. CLOCK is
        # treated identically to INPUT here; the difference only matters
        # to fault analysis and the UI presentation layer.
        if gate_type in ("INPUT", "CLOCK"):
            values[gate_id] = 1 if int(gate.get("value", 0)) else 0
            continue

        dst_pins = drivers.get(gate_id, {})

        # Known type → use the declared pin count. Unknown type → infer
        # from whatever wires are actually attached so future macros
        # don't crash the simulator before they're added to the table.
        if gate_type in _PINS_PER_GATE:
            num_inputs = _PINS_PER_GATE[gate_type]
        else:
            num_inputs = (max(dst_pins.keys()) + 1) if dst_pins else 0

        inputs = [read_pin(dst_pins, p) for p in range(num_inputs)]

        if gate_type in _MACRO_GATES:
            macro_outputs = evaluate_macro_pins(gate_type, inputs)
            values[gate_id] = macro_outputs[0]
            for pin_index, pin_value in enumerate(macro_outputs):
                values[f"{gate_id}:{pin_index}"] = pin_value
        else:
            values[gate_id] = evaluate_gate(gate_type, inputs)

    return values