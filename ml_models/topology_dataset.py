"""
Synthetic labeled-circuit generator for the topology classifier.

Each generator emits a list of (circuit, label) pairs covering common
digital-logic structures and their wiring variants:

    half_adder, full_adder, two_to_one_mux, four_to_one_mux,
    two_to_four_decoder, d_flip_flop, jk_flip_flop, sr_latch,
    n_bit_register, generic

The "generic" class is a noise/negative bucket of small random circuits
that don't fit any canonical type — without it the model would be biased
to always pick *some* canonical answer for arbitrary user input.

The output of `build()` is a list of dicts: {"circuit": ..., "label": str}.
Train/val/test splitting is the caller's responsibility.
"""
import random
from typing import Dict, List

# Canonical labels — re-used by the trainer + frontend chip.
LABELS: List[str] = [
    "half_adder", "full_adder",
    "two_to_one_mux", "four_to_one_mux",
    "two_to_four_decoder",
    "d_flip_flop", "jk_flip_flop", "sr_latch",
    "n_bit_register",
    "generic",
]

# ---------- shared helpers -------------------------------------------------

_PRIMITIVE_GATES = ("AND", "OR", "NOT", "NAND", "NOR", "XOR", "XNOR")


def _gid(prefix: str, n: int) -> str:
    """Stable id helper; randomised suffix improves augmentation diversity."""
    return f"{prefix}_{n}_{random.randint(1000, 9999)}"


def _gate(_id: str, typ: str, x: int = 0, y: int = 0, **kw) -> dict:
    g = {"id": _id, "type": typ, "x": x, "y": y}
    g.update(kw)
    return g


def _wire(src: str, dst: str, pin: int = 0) -> dict:
    return {"from_gate": src, "to_gate": dst, "to_pin": pin}


# ---------- per-label generators ------------------------------------------

def _half_adder_textbook() -> dict:
    """A^B / A&B with XOR + AND."""
    a, b = _gid("a", 0), _gid("b", 0)
    x    = _gid("xor", 0)
    ad   = _gid("and", 0)
    sum_, carry = _gid("sum", 0), _gid("carry", 0)
    return {
        "gates": [
            _gate(a, "INPUT", label="A"), _gate(b, "INPUT", label="B"),
            _gate(x, "XOR"), _gate(ad, "AND"),
            _gate(sum_, "OUTPUT", label="S"),
            _gate(carry, "OUTPUT", label="C"),
        ],
        "wires": [
            _wire(a, x, 0), _wire(b, x, 1),
            _wire(a, ad, 0), _wire(b, ad, 1),
            _wire(x, sum_, 0), _wire(ad, carry, 0),
        ],
    }


def _half_adder_nand_only() -> dict:
    """Same function, different topology — all NAND. Tests generalisation."""
    a, b   = _gid("a", 0), _gid("b", 0)
    n1, n2, n3, n4, n5 = [_gid("nand", i) for i in range(5)]
    sum_, carry = _gid("sum", 0), _gid("carry", 0)
    return {
        "gates": [
            _gate(a, "INPUT", label="A"), _gate(b, "INPUT", label="B"),
            _gate(n1, "NAND"), _gate(n2, "NAND"), _gate(n3, "NAND"),
            _gate(n4, "NAND"), _gate(n5, "NAND"),
            _gate(sum_, "OUTPUT", label="S"),
            _gate(carry, "OUTPUT", label="C"),
        ],
        "wires": [
            _wire(a, n1, 0), _wire(b, n1, 1),
            _wire(a, n2, 0), _wire(n1, n2, 1),
            _wire(b, n3, 0), _wire(n1, n3, 1),
            _wire(n2, n4, 0), _wire(n3, n4, 1),
            _wire(n4, sum_, 0),
            _wire(a, n5, 0), _wire(b, n5, 1),
            _wire(n5, carry, 0),
        ],
    }


def _full_adder_textbook() -> dict:
    a, b, c = _gid("a", 0), _gid("b", 0), _gid("c", 0)
    x1, x2  = _gid("xor", 0), _gid("xor", 1)
    a1, a2  = _gid("and", 0), _gid("and", 1)
    o       = _gid("or", 0)
    sum_, cout = _gid("sum", 0), _gid("cout", 0)
    return {
        "gates": [
            _gate(a, "INPUT", label="A"), _gate(b, "INPUT", label="B"),
            _gate(c, "INPUT", label="Cin"),
            _gate(x1, "XOR"), _gate(x2, "XOR"),
            _gate(a1, "AND"), _gate(a2, "AND"), _gate(o, "OR"),
            _gate(sum_, "OUTPUT", label="S"),
            _gate(cout, "OUTPUT", label="Cout"),
        ],
        "wires": [
            _wire(a, x1, 0), _wire(b, x1, 1),
            _wire(x1, x2, 0), _wire(c, x2, 1),
            _wire(x1, a1, 0), _wire(c, a1, 1),
            _wire(a, a2, 0), _wire(b, a2, 1),
            _wire(a1, o, 0), _wire(a2, o, 1),
            _wire(x2, sum_, 0), _wire(o, cout, 0),
        ],
    }


def _full_adder_from_half_adders() -> dict:
    """FA built as 2× HA macro + OR. Same intent, different shape."""
    a, b, c = _gid("a", 0), _gid("b", 0), _gid("c", 0)
    h1, h2  = _gid("ha", 0), _gid("ha", 1)
    o       = _gid("or", 0)
    sum_, cout = _gid("sum", 0), _gid("cout", 0)
    return {
        "gates": [
            _gate(a, "INPUT", label="A"), _gate(b, "INPUT", label="B"),
            _gate(c, "INPUT", label="Cin"),
            _gate(h1, "HA"), _gate(h2, "HA"), _gate(o, "OR"),
            _gate(sum_, "OUTPUT", label="S"),
            _gate(cout, "OUTPUT", label="Cout"),
        ],
        "wires": [
            _wire(a, h1, 0), _wire(b, h1, 1),
            _wire(h1, h2, 0), _wire(c, h2, 1),
            _wire(h1, o, 0), _wire(h2, o, 1),
            _wire(h2, sum_, 0), _wire(o, cout, 0),
        ],
    }


def _two_to_one_mux() -> dict:
    a, b, sel = _gid("a", 0), _gid("b", 0), _gid("sel", 0)
    not_sel, and1, and2, orout = (
        _gid("not", 0), _gid("and", 0), _gid("and", 1), _gid("or", 0)
    )
    y = _gid("y", 0)
    return {
        "gates": [
            _gate(a, "INPUT", label="A"), _gate(b, "INPUT", label="B"),
            _gate(sel, "INPUT", label="S"),
            _gate(not_sel, "NOT"),
            _gate(and1, "AND"), _gate(and2, "AND"), _gate(orout, "OR"),
            _gate(y, "OUTPUT", label="Y"),
        ],
        "wires": [
            _wire(sel, not_sel, 0),
            _wire(a, and1, 0), _wire(not_sel, and1, 1),
            _wire(b, and2, 0), _wire(sel, and2, 1),
            _wire(and1, orout, 0), _wire(and2, orout, 1),
            _wire(orout, y, 0),
        ],
    }


def _four_to_one_mux() -> dict:
    """4:1 mux made out of three 2:1 mux primitives — clear macro signature."""
    a, b, c, d = (_gid(x, 0) for x in "abcd")
    s0, s1     = _gid("s0", 0), _gid("s1", 0)
    m1, m2, m3 = (_gid(f"mux{i}", 0) for i in range(3))
    y = _gid("y", 0)
    return {
        "gates": [
            _gate(a, "INPUT", label="A"), _gate(b, "INPUT", label="B"),
            _gate(c, "INPUT", label="C"), _gate(d, "INPUT", label="D"),
            _gate(s0, "INPUT", label="S0"), _gate(s1, "INPUT", label="S1"),
            _gate(m1, "MUX2"), _gate(m2, "MUX2"), _gate(m3, "MUX2"),
            _gate(y, "OUTPUT", label="Y"),
        ],
        "wires": [
            _wire(a, m1, 0), _wire(b, m1, 1), _wire(s0, m1, 2),
            _wire(c, m2, 0), _wire(d, m2, 1), _wire(s0, m2, 2),
            _wire(m1, m3, 0), _wire(m2, m3, 1), _wire(s1, m3, 2),
            _wire(m3, y, 0),
        ],
    }


def _two_to_four_decoder() -> dict:
    s0, s1 = _gid("s0", 0), _gid("s1", 0)
    n0, n1 = _gid("not0", 0), _gid("not1", 0)
    y0, y1, y2, y3 = (_gid(f"y{i}", 0) for i in range(4))
    g0, g1, g2, g3 = (_gid(f"and{i}", 0) for i in range(4))
    return {
        "gates": [
            _gate(s0, "INPUT", label="S0"), _gate(s1, "INPUT", label="S1"),
            _gate(n0, "NOT"), _gate(n1, "NOT"),
            _gate(g0, "AND"), _gate(g1, "AND"),
            _gate(g2, "AND"), _gate(g3, "AND"),
            _gate(y0, "OUTPUT", label="Y0"), _gate(y1, "OUTPUT", label="Y1"),
            _gate(y2, "OUTPUT", label="Y2"), _gate(y3, "OUTPUT", label="Y3"),
        ],
        "wires": [
            _wire(s0, n0, 0), _wire(s1, n1, 0),
            _wire(n1, g0, 0), _wire(n0, g0, 1), _wire(g0, y0, 0),
            _wire(n1, g1, 0), _wire(s0, g1, 1), _wire(g1, y1, 0),
            _wire(s1, g2, 0), _wire(n0, g2, 1), _wire(g2, y2, 0),
            _wire(s1, g3, 0), _wire(s0, g3, 1), _wire(g3, y3, 0),
        ],
    }


def _d_flip_flop() -> dict:
    d, clk = _gid("d", 0), _gid("clk", 0)
    ff = _gid("dff", 0)
    q  = _gid("q", 0)
    return {
        "gates": [
            _gate(d, "INPUT", label="D"), _gate(clk, "CLOCK", label="CLK"),
            _gate(ff, "DFF"), _gate(q, "OUTPUT", label="Q"),
        ],
        "wires": [_wire(d, ff, 0), _wire(clk, ff, 1), _wire(ff, q, 0)],
    }


def _jk_flip_flop() -> dict:
    j, k, clk = _gid("j", 0), _gid("k", 0), _gid("clk", 0)
    ff = _gid("jkff", 0)
    q  = _gid("q", 0)
    return {
        "gates": [
            _gate(j, "INPUT", label="J"), _gate(k, "INPUT", label="K"),
            _gate(clk, "CLOCK", label="CLK"),
            _gate(ff, "JKFF"), _gate(q, "OUTPUT", label="Q"),
        ],
        "wires": [_wire(j, ff, 0), _wire(k, ff, 1),
                  _wire(clk, ff, 2), _wire(ff, q, 0)],
    }


def _sr_latch() -> dict:
    """Cross-coupled NAND SR latch — has a feedback loop, which is a strong
    structural signal."""
    s, r = _gid("s", 0), _gid("r", 0)
    n1, n2 = _gid("nand0", 0), _gid("nand1", 0)
    q, qbar = _gid("q", 0), _gid("qbar", 0)
    return {
        "gates": [
            _gate(s, "INPUT", label="S"), _gate(r, "INPUT", label="R"),
            _gate(n1, "NAND"), _gate(n2, "NAND"),
            _gate(q, "OUTPUT", label="Q"),
            _gate(qbar, "OUTPUT", label="Qbar"),
        ],
        "wires": [
            _wire(s, n1, 0), _wire(n2, n1, 1),
            _wire(r, n2, 0), _wire(n1, n2, 1),
            _wire(n1, q, 0), _wire(n2, qbar, 0),
        ],
    }


def _n_bit_register(n_bits: int = 4) -> dict:
    """N D-flip-flops sharing a clock — register signature."""
    clk = _gid("clk", 0)
    gates = [_gate(clk, "CLOCK", label="CLK")]
    wires: List[dict] = []
    for i in range(n_bits):
        din = _gid(f"d{i}", 0)
        ff  = _gid(f"dff{i}", 0)
        q   = _gid(f"q{i}", 0)
        gates += [
            _gate(din, "INPUT", label=f"D{i}"),
            _gate(ff,  "DFF"),
            _gate(q,   "OUTPUT", label=f"Q{i}"),
        ]
        wires += [
            _wire(din, ff, 0),
            _wire(clk, ff, 1),
            _wire(ff,  q,  0),
        ]
    return {"gates": gates, "wires": wires}


def _generic_random(min_g: int = 1, max_g: int = 5) -> dict:
    """Random small circuit — used as the negative / 'other' class so the
    model isn't forced to always pick a canonical label."""
    n = random.randint(min_g, max_g)
    inputs = [_gid(f"in{i}", 0) for i in range(random.randint(1, 3))]
    gates: List[dict] = [_gate(g, "INPUT", label=f"X{i}")
                         for i, g in enumerate(inputs)]
    intermediates: List[str] = []
    wires: List[dict] = []
    for _ in range(n):
        g = _gid("g", 0)
        t = random.choice(_PRIMITIVE_GATES)
        gates.append(_gate(g, t))
        pool = inputs + intermediates
        if t == "NOT":
            wires.append(_wire(random.choice(pool), g, 0))
        else:
            wires.append(_wire(random.choice(pool), g, 0))
            wires.append(_wire(random.choice(pool), g, 1))
        intermediates.append(g)
    # No OUTPUT — these are deliberately incomplete to look "user is mid-build"
    return {"gates": gates, "wires": wires}


# ---------- public builder -------------------------------------------------

# Each label points to a list of generators that produce one example call.
_GENERATORS: Dict[str, list] = {
    "half_adder":          [_half_adder_textbook, _half_adder_nand_only],
    "full_adder":          [_full_adder_textbook, _full_adder_from_half_adders],
    "two_to_one_mux":      [_two_to_one_mux],
    "four_to_one_mux":     [_four_to_one_mux],
    "two_to_four_decoder": [_two_to_four_decoder],
    "d_flip_flop":         [_d_flip_flop],
    "jk_flip_flop":        [_jk_flip_flop],
    "sr_latch":            [_sr_latch],
    "n_bit_register":      [lambda: _n_bit_register(random.choice([2, 4, 8]))],
    "generic":             [_generic_random],
}


def build(per_label: int = 200, seed: int = 0) -> List[dict]:
    """
    Returns ~`per_label * len(LABELS)` labeled samples. Repeatable for a
    given seed (helpful for diffable model metrics).
    """
    random.seed(seed)
    samples: List[dict] = []
    for label in LABELS:
        gens = _GENERATORS[label]
        for i in range(per_label):
            g = gens[i % len(gens)]
            samples.append({"circuit": g(), "label": label})
    random.shuffle(samples)
    return samples
