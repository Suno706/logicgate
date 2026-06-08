"""Comprehensive component health check — run with: python tests/component_check.py"""
import json
import os
import sys
import urllib.request

# Allow running from the tests/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "http://localhost:5000"
results = []


def post(path, body):
    req = urllib.request.Request(
        BASE + path, method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read().decode())


def check(name, ok, detail=""):
    sym = "OK " if ok else "BAD"
    results.append((name, bool(ok), detail))
    print(f"  [{sym}] {name:55s} {detail}")


# ── 1. Health ────────────────────────────────────────────────────────────────
print("\n=== 1. Health endpoint ===")
try:
    h = get("/api/health")
    check("/api/health responds",     h.get("status") == "online")
    models = h.get("models", {})
    check("fault_detector loaded",    models.get("fault_detector"))
    check("circuit_optimizer loaded", models.get("circuit_optimizer"))
    check("gate_minimizer loaded",    models.get("gate_minimizer"))
    check("connection_suggester loaded", models.get("connection_suggester"))
except Exception as e:
    check("/api/health responds", False, str(e))

# ── 2. Simulator (primitives) ────────────────────────────────────────────────
print("\n=== 2. Simulator (primitives) ===")
from simulator import simulate_circuit


def sim_check(name, gates, wires, expected):
    v = simulate_circuit(gates, wires)
    out = {g["id"]: v[g["id"]] for g in gates if g["type"] == "OUTPUT"}
    check(name, out == expected, f"got {out}, want {expected}")


for t, va, vb, e in [("AND", 1, 1, 1), ("AND", 0, 1, 0),
                     ("OR",  1, 0, 1), ("OR",  0, 0, 0),
                     ("NAND", 1, 1, 0), ("NOR", 0, 0, 1),
                     ("XOR",  1, 1, 0), ("XNOR", 1, 1, 1)]:
    gs = [{"id": "a", "type": "INPUT", "value": va},
          {"id": "b", "type": "INPUT", "value": vb},
          {"id": "x", "type": t},
          {"id": "y", "type": "OUTPUT"}]
    ws = [{"from_gate": "a", "to_gate": "x", "from_pin": 0, "to_pin": 0},
          {"from_gate": "b", "to_gate": "x", "from_pin": 0, "to_pin": 1},
          {"from_gate": "x", "to_gate": "y", "from_pin": 0, "to_pin": 0}]
    sim_check(f"{t}({va},{vb})={e}", gs, ws, {"y": e})

# NOT
gs = [{"id": "a", "type": "INPUT", "value": 1},
      {"id": "n", "type": "NOT"},
      {"id": "y", "type": "OUTPUT"}]
ws = [{"from_gate": "a", "to_gate": "n", "from_pin": 0, "to_pin": 0},
      {"from_gate": "n", "to_gate": "y", "from_pin": 0, "to_pin": 0}]
sim_check("NOT(1)=0", gs, ws, {"y": 0})

# ── 3. Macro simulation ──────────────────────────────────────────────────────
print("\n=== 3. Macro simulation ===")

# HA(1,1)=(S=0,C=1)
gs = [{"id": "a", "type": "INPUT", "value": 1},
      {"id": "b", "type": "INPUT", "value": 1},
      {"id": "h", "type": "HA"},
      {"id": "s", "type": "OUTPUT"},
      {"id": "c", "type": "OUTPUT"}]
ws = [{"from_gate": "a", "to_gate": "h", "from_pin": 0, "to_pin": 0},
      {"from_gate": "b", "to_gate": "h", "from_pin": 0, "to_pin": 1},
      {"from_gate": "h", "to_gate": "s", "from_pin": 0, "to_pin": 0},
      {"from_gate": "h", "to_gate": "c", "from_pin": 1, "to_pin": 0}]
sim_check("HA(1,1) S=0 C=1", gs, ws, {"s": 0, "c": 1})

# FA(1,1,1)=(S=1,Co=1)
gs = [{"id": "a", "type": "INPUT", "value": 1},
      {"id": "b", "type": "INPUT", "value": 1},
      {"id": "ci", "type": "INPUT", "value": 1},
      {"id": "f", "type": "FA"},
      {"id": "s", "type": "OUTPUT"},
      {"id": "co", "type": "OUTPUT"}]
ws = [{"from_gate": "a", "to_gate": "f", "from_pin": 0, "to_pin": 0},
      {"from_gate": "b", "to_gate": "f", "from_pin": 0, "to_pin": 1},
      {"from_gate": "ci", "to_gate": "f", "from_pin": 0, "to_pin": 2},
      {"from_gate": "f", "to_gate": "s", "from_pin": 0, "to_pin": 0},
      {"from_gate": "f", "to_gate": "co", "from_pin": 1, "to_pin": 0}]
sim_check("FA(1,1,1) S=1 Co=1", gs, ws, {"s": 1, "co": 1})

# MUX2
gs = [{"id": "a", "type": "INPUT", "value": 1},
      {"id": "b", "type": "INPUT", "value": 0},
      {"id": "s", "type": "INPUT", "value": 1},
      {"id": "m", "type": "MUX2"},
      {"id": "y", "type": "OUTPUT"}]
ws = [{"from_gate": "a", "to_gate": "m", "from_pin": 0, "to_pin": 0},
      {"from_gate": "b", "to_gate": "m", "from_pin": 0, "to_pin": 1},
      {"from_gate": "s", "to_gate": "m", "from_pin": 0, "to_pin": 2},
      {"from_gate": "m", "to_gate": "y", "from_pin": 0, "to_pin": 0}]
sim_check("MUX2 A=1 B=0 S=1 -> Y=0", gs, ws, {"y": 0})

# DEC24 A=1 B=0 → Y2 high
gs = [{"id": "a", "type": "INPUT", "value": 1},
      {"id": "b", "type": "INPUT", "value": 0},
      {"id": "d", "type": "DEC24"},
      {"id": "y0", "type": "OUTPUT"},
      {"id": "y1", "type": "OUTPUT"},
      {"id": "y2", "type": "OUTPUT"},
      {"id": "y3", "type": "OUTPUT"}]
ws = [{"from_gate": "a", "to_gate": "d", "from_pin": 0, "to_pin": 0},
      {"from_gate": "b", "to_gate": "d", "from_pin": 0, "to_pin": 1}]
for i, o in enumerate(["y0", "y1", "y2", "y3"]):
    ws.append({"from_gate": "d", "to_gate": o, "from_pin": i, "to_pin": 0})
sim_check("DEC24 A=1 B=0 -> Y2 high", gs, ws,
          {"y0": 0, "y1": 0, "y2": 1, "y3": 0})

# ── 4. Build requests via /api/ask ───────────────────────────────────────────
print("\n=== 4. Build requests (/api/ask) ===")
for q in [
    "build a half adder",
    "build a 2-to-1 mux",
    "build a 4-bit ripple carry adder",
    "build a JK flip-flop",
    "build a SR latch",
    "build a full adder",
    "make a 3-to-8 decoder",
    "design XOR using only NAND gates",
    "make a circuit Y=1 when A=1 B=0",
    "build a 4-input majority circuit",
    "make a output from 3-5 input when input are 1 then out is 0",
]:
    r = post("/api/ask", {"question": q})
    n = len((r.get("circuit") or {}).get("gates", []))
    check(f"build: {q[:50]!r}", n > 0, f"gates={n}")

# ── 5. Knowledge base routing ────────────────────────────────────────────────
print("\n=== 5. Knowledge base routing ===")
for q in [
    "what is propagation delay",
    "explain NAND universality",
    "what is XOR gate",
    "what is metastability",
    "what is race condition",
    "tell me about karnaugh maps",
    "what is De Morgan's law",
    "what is a flip flop",
]:
    r = post("/api/ask", {"question": q})
    kb = (r.get("details") or {}).get("kb_match")
    check(f"KB: {q[:50]!r}", bool(kb), f"kb={kb}")

# ── 6-8. Backend ML endpoints ────────────────────────────────────────────────
print("\n=== 6. Fault detection ===")
c = {
    "gates": [{"id": "a", "type": "INPUT", "value": 1},
              {"id": "x", "type": "AND"},
              {"id": "y", "type": "OUTPUT"}],
    "wires": [{"from_gate": "a", "to_gate": "x", "from_pin": 0, "to_pin": 0},
              {"from_gate": "x", "to_gate": "y", "from_pin": 0, "to_pin": 0}]
}
try:
    r = post("/api/analyze/faults", {"circuit": c})
    ok = "issues" in r or "faults" in r or "fault_count" in r
    check("/api/analyze/faults responds", ok)
except Exception as e:
    check("/api/analyze/faults responds", False, str(e))

print("\n=== 7. Circuit optimizer ===")
try:
    r = post("/api/analyze/optimize", {"circuit": c})
    analysis = r.get("analysis") or {}
    ok = "suggestions" in analysis and "metrics" in analysis
    check("/api/analyze/optimize responds", ok,
          f"keys: {sorted(analysis.keys())[:3]}")
except Exception as e:
    check("/api/analyze/optimize responds", False, str(e))

print("\n=== 8. Gate minimizer ===")
try:
    r = post("/api/analyze/minimize", {"circuit": c})
    ok = "current_gates" in r or "suggestions" in r or "efficiency_score" in r
    check("/api/analyze/minimize responds", ok)
except Exception as e:
    check("/api/analyze/minimize responds", False, str(e))

# ── 9. Boolean synthesizer ──────────────────────────────────────────────────
print("\n=== 9. Boolean synthesizer ===")
try:
    r = post("/api/build/boolean", {"expression": "A & B | ~C"})
    n = len((r.get("circuit") or {}).get("gates", []))
    check("boolean synth 'A & B | ~C'", n > 0, f"gates={n}")
except Exception as e:
    check("boolean synth", False, str(e))

# ── 10. Connection suggester ────────────────────────────────────────────────
print("\n=== 10. Connection suggester ===")
c2 = {
    "gates": [{"id": "a", "type": "INPUT", "value": 1},
              {"id": "b", "type": "INPUT", "value": 0},
              {"id": "x", "type": "AND"}],
    "wires": []
}
try:
    r = post("/api/suggest/connection", {"circuit": c2})
    check("/api/suggest/connection responds", "suggestions" in r,
          f"got {len(r.get('suggestions',[]))} suggestions")
except Exception as e:
    check("/api/suggest responds", False, str(e))

# ── 11. Full analysis ──────────────────────────────────────────────────────
print("\n=== 11. Full analysis ===")
try:
    r = post("/api/analyze/full", {"circuit": c})
    ok = "analysis" in r and "faults" in r.get("analysis", {})
    check("/api/analyze/full responds", ok)
except Exception as e:
    check("/api/analyze/full responds", False, str(e))

# ── 12. Intent classifier on informal phrasings ──────────────────────────────
print("\n=== 12. Intent classifier on informal phrasings ===")
expected = {
    "hey can u build me a flip flop":  "build",
    "how many gates are in this thing": "gate_count",
    "any problems with this circuit":   "fault_check",
    "can you shrink this circuit down": "minimize",
    "what happens if A=1 and B=0":      "input_effect",
    "what does this thing do":          "explain",
    "what gates am i using":            "gate_type",
}
for q, exp in expected.items():
    r = post("/api/ask", {
        "question": q,
        "circuit": {"gates": [{"id": "x", "type": "AND"}], "wires": []},
    })
    got = r.get("intent")
    check(f"{q[:42]!r:44s} -> {exp}", got == exp, f"got {got}")

# ── 13. Hard NL phrasings (stress test — typos, slang, broken grammar) ──────
print("\n=== 13. Hard NL phrasings — typo/slang/broken-grammar tolerance ===")
hard = {
    "i wnt 2 buld a haf addr":               ("build",         True),  # typos
    "plz make me 4 bit addr":                ("build",         True),  # plz + abbrev
    "circuit jb sb input 1 ho to output 0":  ("build",         True),  # hindi/english
    "y u no give me xor gate":               ("build",         False), # informal but build-ish
    "wat is meant by dff":                   ("explain",       True),  # wat=what
    "this thing has how many gates":         ("gate_count",    True),
    "simplify my circuit using nand":        ("build",         False), # could go either way
    "is this thing busted":                  ("fault_check",   True),
    "tell me about flip flops bro":          ("explain",       True),
    "what would happen if A becomes 1":      ("input_effect",  True),  # would happen if
    "what does this output for A=1 B=1":     ("output_query",  True),
    "make me a 3-input nand":                ("build",         True),
    "construct a circuit on A B C output is parity": ("build", True),
    "explain how cmos works":                ("explain",       True),
}
hard_passed = 0
hard_must = 0
for q, (exp, must_pass) in hard.items():
    r = post("/api/ask", {
        "question": q,
        "circuit": {"gates": [{"id": "x", "type": "AND"}], "wires": []},
    })
    got = r.get("intent")
    matches = got == exp
    if must_pass:
        check(f"hard: {q[:48]!r:50s} -> {exp}", matches, f"got {got}")
        hard_must += 1
        if matches:
            hard_passed += 1
    else:
        # Informational — not a pass/fail
        print(f"  [INF] hard: {q[:50]!r:52s} -> wanted {exp}, got {got}")

# ── Summary ─────────────────────────────────────────────────────────────────
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"\n{'='*70}")
print(f"  SUMMARY: {passed}/{total} components healthy")
print(f"{'='*70}")
if passed < total:
    print("\nFAILURES:")
    for name, ok, det in results:
        if not ok:
            print(f"  - {name}  ({det})")
sys.exit(0 if passed == total else 1)
