"""
Stress test for messy human-style queries.

This is a "soft" test — we assert the parser handles at least N% of
realistic messy phrasings. When a new pattern is added, move its phrasing
into the relevant test in `test_question_solver.py` and remove it here.
"""
import pytest

from tests.conftest import gate_types

MESSY_QUERIES = [
    # Casual / lazy
    "i want and gate",
    "gimme a xor",
    "can u make a half adder",
    "pls build full adder",
    "i need 2:1 mux",
    "show me a comparator",
    # Contractions
    "don't use AND, only NAND",
    "won't u build full adder using NAND",
    # Typos
    "halfadder",
    "biuld a fll addr",
    "make me a multipxer",
    "fulll adder withh nand",
    # Multi-sentence
    "i want a circuit. it should be a full adder. use NAND only.",
    "build full adder. use NAND.",
    # Verbose
    "could you please construct a half adder for me",
    "i would like you to build a 4 to 1 multiplexer",
    "please design a 1 bit alu",
    # Question form
    "how do i make a full adder",
    "what is a half adder circuit",
    # Math / engineering notation
    "make ~A.B + C",
    "construct (A AND B) OR (NOT C)",
    # Truth table / value spec
    "output 1 when A=1 B=1, output 0 otherwise",
    "Y=1 for A=0 B=0 and A=1 B=1",
    "circuit that outputs the bigger of A and B",
    "output is high when more than half of A B C are 1",
]


def _builds(solver, q):
    r = solver.build_from_text(q)
    gates = r.get("circuit", {}).get("gates", []) if r else []
    return sum(1 for g in gates if g["type"] not in ("INPUT", "OUTPUT"))


def test_parser_handles_messy_queries(solver):
    """
    At least 90% of human-style phrasings should produce a circuit.
    This is a regression guard — if a future change drops below 90%,
    CI fails and we can investigate.
    """
    passed = sum(1 for q in MESSY_QUERIES if _builds(solver, q) > 0)
    total = len(MESSY_QUERIES)
    pct = passed / total
    print(f"\nNL stress: {passed}/{total} = {pct:.0%}")
    assert pct >= 0.90, (
        f"NL parser pass rate dropped below 90%: {passed}/{total}. "
        f"Failing queries: "
        f"{[q for q in MESSY_QUERIES if _builds(solver, q) == 0]}"
    )
