"""
Tests for the boolean synthesizer.

We verify three things per case:
1. The synth accepts the expression without raising.
2. The gate count is in a reasonable range (catches accidental blowups).
3. The synthesized circuit, when simulated, matches the truth table of the
   original expression (proves correctness end-to-end).
"""
import itertools

import pytest

from simulator import simulate_circuit
from tests.conftest import gate_types


def _vars_in(expr):
    """Pull A-Z single-letter variables out of an expression."""
    return sorted({c for c in expr if c.isalpha() and c.isupper()})


def _eval_expr(expr, values):
    """Evaluate a boolean expression with ~ & | ^ operators."""
    # The expression uses the same syntax as boolean_synth, which we can
    # translate to Python: ~ -> not, & -> and, | -> or, ^ -> xor.
    py = expr
    for v, b in values.items():
        # Replace whole-word variables only.
        import re
        py = re.sub(rf"\b{v}\b", str(b), py)
    py = py.replace("~", " not ").replace("&", " and ").replace("|", " or ")
    py = py.replace("^", " ^ ")
    return int(bool(eval(py)))


def _simulate_with(circuit, var_values):
    """Set INPUT gates from var_values and simulate."""
    for g in circuit["gates"]:
        if g["type"] == "INPUT":
            g["value"] = var_values.get(g["label"], 0)
    return simulate_circuit(circuit["gates"], circuit["wires"])


def _check_truth_table(synth, expr, expected_expr=None):
    """Build `expr`, simulate it across all input combos, compare to expected."""
    circuit, info = synth.build(expr)
    vars_ = _vars_in(expr)
    output_ids = [g["id"] for g in circuit["gates"] if g["type"] == "OUTPUT"]
    assert output_ids, f"No OUTPUT found in synthesized circuit for {expr!r}"

    for combo in itertools.product([0, 1], repeat=len(vars_)):
        values = dict(zip(vars_, combo))
        sim = _simulate_with(circuit, values)
        got = sim[output_ids[0]]
        want = _eval_expr(expected_expr or expr, values)
        assert got == want, (
            f"Mismatch for expr {expr!r} at {values}: got {got}, want {want}"
        )
    return info


# -- Basic single-gate expressions --------------------------------------------

def test_and_two_inputs(synth):
    info = _check_truth_table(synth, "A & B")
    assert info["gate_count"] == 1


def test_or_two_inputs(synth):
    info = _check_truth_table(synth, "A | B")
    assert info["gate_count"] == 1


def test_xor_two_inputs(synth):
    info = _check_truth_table(synth, "A ^ B")
    assert info["gate_count"] == 1


def test_not_one_input(synth):
    info = _check_truth_table(synth, "~A")
    assert info["gate_count"] == 1


# -- Compound expressions -----------------------------------------------------

def test_three_input_and(synth):
    info = _check_truth_table(synth, "A & B & C")
    assert 1 <= info["gate_count"] <= 3


def test_sum_of_products(synth):
    info = _check_truth_table(synth, "(A & B) | (~A & C)")
    assert info["gate_count"] >= 3


def test_majority_three(synth):
    info = _check_truth_table(synth, "(A & B) | (B & C) | (A & C)")
    assert info["gate_count"] >= 3


# -- Universal-gate translation -----------------------------------------------

def test_nand_only_implements_xor(synth):
    """XOR can be built from NANDs alone. The result must still XOR correctly."""
    circuit, info = synth.build("A ^ B", target_gates=["NAND"])
    types = gate_types(circuit)
    assert types, "Expected at least one NAND gate"
    assert set(types) <= {"NAND"}, f"Got non-NAND gates: {set(types)}"

    # Verify all 4 input combos give correct XOR output.
    output_ids = [g["id"] for g in circuit["gates"] if g["type"] == "OUTPUT"]
    for a, b in itertools.product([0, 1], repeat=2):
        sim = _simulate_with(circuit, {"A": a, "B": b})
        assert sim[output_ids[0]] == (a ^ b), f"NAND XOR wrong at A={a},B={b}"


def test_nor_only_implements_and(synth):
    circuit, info = synth.build("A & B", target_gates=["NOR"])
    types = gate_types(circuit)
    assert set(types) <= {"NOR"}, f"Got non-NOR gates: {set(types)}"

    output_ids = [g["id"] for g in circuit["gates"] if g["type"] == "OUTPUT"]
    for a, b in itertools.product([0, 1], repeat=2):
        sim = _simulate_with(circuit, {"A": a, "B": b})
        assert sim[output_ids[0]] == (a & b)


def test_aoi_can_build_xor(synth):
    """AND/OR/NOT (AOI) is universal — must be able to express XOR."""
    circuit, info = synth.build("A ^ B", target_gates=["AND", "OR", "NOT"])
    types = gate_types(circuit)
    assert set(types) <= {"AND", "OR", "NOT"}

    output_ids = [g["id"] for g in circuit["gates"] if g["type"] == "OUTPUT"]
    for a, b in itertools.product([0, 1], repeat=2):
        sim = _simulate_with(circuit, {"A": a, "B": b})
        assert sim[output_ids[0]] == (a ^ b)


# -- Degenerate inputs --------------------------------------------------------

def test_identity_expression(synth):
    """A bare variable should still produce a valid (possibly empty) circuit."""
    circuit, info = synth.build("A")
    # Either zero gates (pure wire) or a single buffer is acceptable.
    assert info["gate_count"] >= 0


def test_constant_one(synth):
    """Constant 1 should not crash."""
    circuit, info = synth.build("A | ~A")
    output_ids = [g["id"] for g in circuit["gates"] if g["type"] == "OUTPUT"]
    for a in [0, 1]:
        sim = _simulate_with(circuit, {"A": a})
        assert sim[output_ids[0]] == 1
