"""Tests for ml_models.verilog_export."""
import pytest

from ml_models.verilog_export import (
    export_verilog, export_summary, VerilogExportError,
)


def _half_adder():
    """A → XOR → S,  A & B → AND → C."""
    return {
        "gates": [
            {"id": "A",   "type": "INPUT",  "value": 0},
            {"id": "B",   "type": "INPUT",  "value": 0},
            {"id": "x1",  "type": "XOR"},
            {"id": "a1",  "type": "AND"},
            {"id": "S",   "type": "OUTPUT"},
            {"id": "C",   "type": "OUTPUT"},
        ],
        "wires": [
            {"from_gate": "A", "to_gate": "x1", "from_pin": 0, "to_pin": 0},
            {"from_gate": "B", "to_gate": "x1", "from_pin": 0, "to_pin": 1},
            {"from_gate": "A", "to_gate": "a1", "from_pin": 0, "to_pin": 0},
            {"from_gate": "B", "to_gate": "a1", "from_pin": 0, "to_pin": 1},
            {"from_gate": "x1", "to_gate": "S", "from_pin": 0, "to_pin": 0},
            {"from_gate": "a1", "to_gate": "C", "from_pin": 0, "to_pin": 0},
        ],
    }


def test_half_adder_exports():
    v = export_verilog(_half_adder(), module_name="half_adder")
    assert "module half_adder" in v
    assert "xor u_x1" in v
    assert "and u_a1" in v
    assert "input  wire A" in v and "input  wire B" in v
    assert "output wire S" in v and "output wire C" in v
    assert v.strip().endswith("`default_nettype wire")


def test_full_adder_macro_emits_sum_and_carry():
    circuit = {
        "gates": [
            {"id": "A",  "type": "INPUT"},
            {"id": "B",  "type": "INPUT"},
            {"id": "Ci", "type": "INPUT"},
            {"id": "fa", "type": "FA"},
            {"id": "S",  "type": "OUTPUT"},
            {"id": "Co", "type": "OUTPUT"},
        ],
        "wires": [
            {"from_gate": "A",  "to_gate": "fa", "to_pin": 0},
            {"from_gate": "B",  "to_gate": "fa", "to_pin": 1},
            {"from_gate": "Ci", "to_gate": "fa", "to_pin": 2},
            {"from_gate": "fa", "to_gate": "S",  "from_pin": 0},
            {"from_gate": "fa", "to_gate": "Co", "from_pin": 1},
        ],
    }
    v = export_verilog(circuit, module_name="fa")
    assert "w_fa" in v and "w_fa_1" in v
    # The FA macro emits a sum and a carry expression.
    assert "^" in v and "|" in v


def test_dff_uses_clock_edge():
    circuit = {
        "gates": [
            {"id": "D",   "type": "INPUT"},
            {"id": "CLK", "type": "CLOCK"},
            {"id": "ff",  "type": "DFF"},
            {"id": "Q",   "type": "OUTPUT"},
        ],
        "wires": [
            {"from_gate": "D",   "to_gate": "ff", "to_pin": 0},
            {"from_gate": "CLK", "to_gate": "ff", "to_pin": 1},
            {"from_gate": "ff",  "to_gate": "Q",  "from_pin": 0},
        ],
    }
    v = export_verilog(circuit)
    assert "posedge w_CLK" in v
    assert "reg r_ff" in v


def test_empty_circuit_raises():
    with pytest.raises(VerilogExportError):
        export_verilog({"gates": [], "wires": []})


def test_unknown_gate_raises():
    with pytest.raises(VerilogExportError):
        export_verilog({
            "gates": [
                {"id": "A", "type": "INPUT"},
                {"id": "x", "type": "MAGIC_BOX"},
                {"id": "Y", "type": "OUTPUT"},
            ],
            "wires": [
                {"from_gate": "A", "to_gate": "x"},
                {"from_gate": "x", "to_gate": "Y"},
            ],
        })


def test_summary_counts_by_type():
    s = export_summary(_half_adder())
    assert s["gate_count"] == 6
    assert s["wire_count"] == 6
    assert s["by_type"]["INPUT"] == 2
    assert s["by_type"]["XOR"] == 1
    assert s["has_clock"] is False
    assert s["sequential"] is False


def test_identifiers_sanitized():
    # Gate ids with hyphens/dots/spaces must become valid Verilog identifiers.
    circuit = {
        "gates": [
            {"id": "in.one", "type": "INPUT"},
            {"id": "in-two", "type": "INPUT"},
            {"id": "x 1",    "type": "AND"},
            {"id": "out!",   "type": "OUTPUT"},
        ],
        "wires": [
            {"from_gate": "in.one", "to_gate": "x 1", "to_pin": 0},
            {"from_gate": "in-two", "to_gate": "x 1", "to_pin": 1},
            {"from_gate": "x 1",    "to_gate": "out!"},
        ],
    }
    v = export_verilog(circuit)
    # No raw special chars survive into emitted identifiers.
    for line in v.splitlines():
        if line.startswith("  ") and "//" not in line and "1'b" not in line:
            for bad in (" 1", "in.one", "in-two", "out!"):
                assert bad not in line
