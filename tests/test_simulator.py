"""
Tests for the circuit simulator.

We hand-build a few small circuits (no synthesis) and check that the
simulator produces correct outputs.
"""
import pytest

from simulator import simulate_circuit, validate_circuit


def _and_gate_circuit(a, b):
    """A two-input AND gate with A and B as inputs."""
    return {
        "gates": [
            {"id": "g1", "type": "INPUT", "label": "A", "value": a},
            {"id": "g2", "type": "INPUT", "label": "B", "value": b},
            {"id": "g3", "type": "AND"},
            {"id": "g4", "type": "OUTPUT", "label": "Y"},
        ],
        "wires": [
            {"from_gate": "g1", "from_pin": 0, "to_gate": "g3", "to_pin": 0},
            {"from_gate": "g2", "from_pin": 0, "to_gate": "g3", "to_pin": 1},
            {"from_gate": "g3", "from_pin": 0, "to_gate": "g4", "to_pin": 0},
        ],
    }


# -- AND truth table ----------------------------------------------------------

@pytest.mark.parametrize("a,b,expected", [
    (0, 0, 0), (0, 1, 0), (1, 0, 0), (1, 1, 1),
])
def test_and_gate(a, b, expected):
    c = _and_gate_circuit(a, b)
    out = simulate_circuit(c["gates"], c["wires"])
    assert out["g4"] == expected


# -- Validation ---------------------------------------------------------------

def test_validate_accepts_good_circuit():
    c = _and_gate_circuit(1, 0)
    ok, errors, warnings = validate_circuit(c["gates"], c["wires"])
    assert ok
    assert not errors


def test_validate_flags_dangling_wire():
    """A wire from a non-existent gate should be flagged."""
    c = _and_gate_circuit(1, 0)
    c["wires"].append({
        "from_gate": "ghost",
        "from_pin": 0,
        "to_gate": "g3",
        "to_pin": 0,
    })
    ok, errors, warnings = validate_circuit(c["gates"], c["wires"])
    # Either reported as error or warning is fine, but it must be flagged.
    assert errors or warnings


# -- NAND / NOR / XOR truth tables (via simulator) ----------------------------

def _two_input_gate(gate_type, a, b):
    return {
        "gates": [
            {"id": "g1", "type": "INPUT", "label": "A", "value": a},
            {"id": "g2", "type": "INPUT", "label": "B", "value": b},
            {"id": "g3", "type": gate_type},
            {"id": "g4", "type": "OUTPUT", "label": "Y"},
        ],
        "wires": [
            {"from_gate": "g1", "from_pin": 0, "to_gate": "g3", "to_pin": 0},
            {"from_gate": "g2", "from_pin": 0, "to_gate": "g3", "to_pin": 1},
            {"from_gate": "g3", "from_pin": 0, "to_gate": "g4", "to_pin": 0},
        ],
    }


@pytest.mark.parametrize("gate_type,truth", [
    ("AND",  {(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 1}),
    ("OR",   {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 1}),
    ("NAND", {(0, 0): 1, (0, 1): 1, (1, 0): 1, (1, 1): 0}),
    ("NOR",  {(0, 0): 1, (0, 1): 0, (1, 0): 0, (1, 1): 0}),
    ("XOR",  {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 0}),
    ("XNOR", {(0, 0): 1, (0, 1): 0, (1, 0): 0, (1, 1): 1}),
])
def test_two_input_gate_truth_table(gate_type, truth):
    for (a, b), expected in truth.items():
        c = _two_input_gate(gate_type, a, b)
        out = simulate_circuit(c["gates"], c["wires"])
        assert out["g4"] == expected, (
            f"{gate_type} wrong at A={a},B={b}: got {out['g4']}, want {expected}"
        )


# -- NOT gate ----------------------------------------------------------------

@pytest.mark.parametrize("a,expected", [(0, 1), (1, 0)])
def test_not_gate(a, expected):
    c = {
        "gates": [
            {"id": "g1", "type": "INPUT", "label": "A", "value": a},
            {"id": "g2", "type": "NOT"},
            {"id": "g3", "type": "OUTPUT", "label": "Y"},
        ],
        "wires": [
            {"from_gate": "g1", "from_pin": 0, "to_gate": "g2", "to_pin": 0},
            {"from_gate": "g2", "from_pin": 0, "to_gate": "g3", "to_pin": 0},
        ],
    }
    out = simulate_circuit(c["gates"], c["wires"])
    assert out["g3"] == expected
