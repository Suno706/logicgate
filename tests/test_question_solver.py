"""
Tests for the natural-language question solver.

These act as both correctness tests AND living documentation for what
phrasings the parser supports. When you add a new pattern, add a test here.
"""
import pytest

from tests.conftest import gate_types


def _build(solver, text):
    """Helper: call build_from_text, return (n_gates, gate_set, answer, circuit)."""
    r = solver.build_from_text(text)
    circuit = r.get("circuit") or {"gates": [], "wires": []}
    types = gate_types(circuit)
    return len(types), set(types), (r.get("answer") or ""), circuit


# -- Known templates ----------------------------------------------------------

def test_half_adder(solver):
    n, types, answer, _ = _build(solver, "half adder")
    assert n == 2
    assert types == {"XOR", "AND"}


def test_full_adder(solver):
    n, types, _, _ = _build(solver, "full adder")
    assert n >= 4   # 2 XOR + 2 AND + 1 OR minimum


def test_full_adder_using_nand(solver):
    n, types, _, _ = _build(solver, "full adder using NAND")
    assert n >= 1
    assert types == {"NAND"}


def test_two_to_one_mux(solver):
    n, types, _, _ = _build(solver, "2 to 1 mux")
    assert n >= 3


def test_xor_gate(solver):
    n, types, _, _ = _build(solver, "XOR gate")
    assert n == 1
    assert types == {"XOR"}


# -- Typo / alias handling ----------------------------------------------------

def test_full_adder_typo_adwer(solver):
    """Common typo: 'adwer' should still resolve to adder."""
    n, _, _, _ = _build(solver, "full adwer")
    assert n >= 4


def test_full_adder_misspelled_full(solver):
    n, _, _, _ = _build(solver, "fll adder")
    assert n >= 4


def test_multiplexer_typo(solver):
    n, _, _, _ = _build(solver, "multipxer")
    assert n >= 3


def test_concatenated_name(solver):
    """'halfadder' (no space) should resolve to 'half adder'."""
    n, _, _, _ = _build(solver, "halfadder")
    assert n == 2


# -- Polite / conversational openers -----------------------------------------

def test_please_prefix(solver):
    n, _, _, _ = _build(solver, "please build a half adder")
    assert n == 2


def test_gimme(solver):
    n, _, _, _ = _build(solver, "gimme a xor")
    assert n == 1


def test_question_form(solver):
    n, _, _, _ = _build(solver, "how do i make a full adder")
    assert n >= 4


def test_could_you(solver):
    n, _, _, _ = _build(solver, "could you please construct a half adder for me")
    assert n == 2


# -- Boolean expression input -------------------------------------------------

def test_direct_boolean_expression(solver):
    n, _, _, _ = _build(solver, "A & B | ~C")
    assert n >= 2


def test_engineering_notation_or(solver):
    """`+` should be treated as OR in engineering-notation boolean expressions."""
    n, _, _, _ = _build(solver, "make ~A.B + C")
    assert n >= 2


def test_word_operators(solver):
    n, _, _, _ = _build(solver, "construct (A AND B) OR (NOT C)")
    assert n >= 2


# -- Truth-table specs -------------------------------------------------------

def test_truth_table_row_spec(solver):
    n, _, _, _ = _build(solver, "output 1 when A=1 B=1, output 0 otherwise")
    assert n >= 1


def test_binary_minterm_spec(solver):
    n, _, _, _ = _build(solver, "Y=1 for A=0 B=0 and A=1 B=1")
    assert n >= 1


# -- Value-set / numeric specs -----------------------------------------------

def test_value_set_in_binary(solver):
    """'ABC reads as 5 or 6 in binary' -> enumerate minterms 5 and 6."""
    n, _, ans, _ = _build(solver, "Y is 1 when ABC reads as 5 or 6 in binary")
    assert n >= 2
    assert "5" in ans or "6" in ans or "value" in ans.lower()


def test_prime_detector(solver):
    """ABCD is prime -> 6 prime minterms (2,3,5,7,11,13)."""
    n, _, ans, _ = _build(
        solver,
        "Y goes high whenever the input number is prime treat ABCD as 4 bit binary",
    )
    assert n >= 10
    assert "prime" in ans.lower()


# -- Conditional / multiplexer-style specs -----------------------------------

def test_conditional_mux(solver):
    n, _, ans, _ = _build(
        solver,
        "output equals A when SEL is 0 and equals NOT B when SEL is 1",
    )
    assert n >= 3
    assert "SEL" in ans


def test_conditional_with_nand(solver):
    n, _, _, _ = _build(
        solver,
        "output equals A when SEL is 0 and equals NOT B when SEL is 1, using only NAND",
    )
    assert n >= 3


# -- Domain-aware concepts ----------------------------------------------------

def test_majority_three_inputs(solver):
    n, _, _, _ = _build(solver, "output is high when more than half of A B C are 1")
    assert n >= 3


def test_max_of_two(solver):
    n, _, _, _ = _build(solver, "circuit that outputs the bigger of A and B")
    assert n >= 1


def test_exactly_two_of_four(solver):
    n, _, _, _ = _build(
        solver,
        "output is 1 when exactly two of A B C D are high, otherwise 0",
    )
    # 6 minterms for C(4,2) = 6
    assert n >= 10


# -- N-bit parametric synthesis ----------------------------------------------

def test_four_bit_adder(solver):
    n, _, _, _ = _build(solver, "4 bit ripple carry adder")
    assert n >= 12


def test_eight_bit_equality_comparator(solver):
    n, _, _, _ = _build(solver, "8 bit equality comparator")
    assert n >= 8


# -- Multi-output circuits ---------------------------------------------------

def test_bcd_to_7_segment(solver):
    n, _, _, circuit = _build(solver, "bcd to 7 segment")
    outputs = [g for g in circuit["gates"] if g["type"] == "OUTPUT"]
    assert len(outputs) == 7  # a..g segments
    assert n >= 10


def test_full_adder_has_two_outputs(solver):
    _, _, _, circuit = _build(solver, "full adder")
    outputs = [g for g in circuit["gates"] if g["type"] == "OUTPUT"]
    assert len(outputs) == 2  # Sum + Cout
