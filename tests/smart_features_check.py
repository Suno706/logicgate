"""Smart-panel feature health: probe Build / Suggest / Fault / Minimize for
   answer QUALITY, not just HTTP success."""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = "http://localhost:5000"


def post(path, body):
    req = urllib.request.Request(
        BASE + path, method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def section(t):
    print("\n" + "=" * 78)
    print("  " + t)
    print("=" * 78)


# ── BUILD ─────────────────────────────────────────────────────────────────
section("BUILD — various phrasings and complexities")

build_cases = [
    "half adder",
    "full adder",
    "4 to 1 mux",
    "3 to 8 decoder",
    "D flip flop",
    "JK flip flop",
    "BCD to 7 segment",
    "comparator for 4-bit numbers",
    "4 bit ripple carry adder",
    "circuit that outputs 1 when 3 of 4 inputs are 1",
    "make a XOR using only NAND",
    "build a circuit where Y=1 when A xor B xor C",
    "implement A and B or not C",
    "build a 1-of-8 selector",
    "2-bit binary multiplier",
    "build a parity bit generator for 4 inputs",
]

for q in build_cases:
    r = post("/api/build/question", {"question": q})
    c = r.get("circuit") or {}
    gates = c.get("gates", [])
    wires = c.get("wires", [])
    n_in  = sum(1 for g in gates if g.get("type") in ("INPUT", "CLOCK"))
    n_out = sum(1 for g in gates if g.get("type") == "OUTPUT")
    n_lg  = sum(1 for g in gates if g.get("type") not in ("INPUT", "CLOCK", "OUTPUT"))
    ok    = bool(gates) and n_in > 0 and n_out > 0
    sym   = "OK " if ok else "BAD"
    print(f"  [{sym}] {q[:48]:50s} inp={n_in} out={n_out} logic={n_lg} wires={len(wires)}")
    if not ok:
        ans = (r.get("answer") or "")[:100]
        print(f"        answer: {ans}")


# ── SUGGEST ─────────────────────────────────────────────────────────────────
section("SUGGEST — incomplete circuit wire suggestions")

# Half adder with unwired AND gate — suggester should suggest wires from inputs
ha_unwired = {
    "gates": [
        {"id": "A",   "type": "INPUT",  "value": 1},
        {"id": "B",   "type": "INPUT",  "value": 0},
        {"id": "x",   "type": "XOR"},
        {"id": "y",   "type": "AND"},
        {"id": "Sum", "type": "OUTPUT"},
        {"id": "Cy",  "type": "OUTPUT"},
    ],
    "wires": [],
}
r = post("/api/suggest/connection", {"circuit": ha_unwired})
sugs = r.get("suggestions", [])
print(f"  [{'OK ' if sugs else 'BAD'}] half-adder skeleton (no wires) -> {len(sugs)} suggestions")
for s in sugs[:6]:
    score = s.get("score", "?")
    print(f"        {s.get('from_gate','?'):3s}:{s.get('from_pin','?')} -> {s.get('to_gate','?'):3s}:{s.get('to_pin','?')}  score={score}")

# Just two inputs and an OR — clear wire suggestions
two_in = {
    "gates": [
        {"id": "a", "type": "INPUT", "value": 1},
        {"id": "b", "type": "INPUT", "value": 0},
        {"id": "o", "type": "OR"},
        {"id": "y", "type": "OUTPUT"},
    ],
    "wires": [],
}
r = post("/api/suggest/connection", {"circuit": two_in})
sugs = r.get("suggestions", [])
print(f"  [{'OK ' if sugs else 'BAD'}] OR skeleton -> {len(sugs)} suggestions")
for s in sugs[:4]:
    print(f"        {s.get('from_gate','?'):3s}:{s.get('from_pin','?')} -> {s.get('to_gate','?'):3s}:{s.get('to_pin','?')}  score={s.get('score')}")


# ── FAULT ─────────────────────────────────────────────────────────────────
section("FAULT — detection on circuits with deliberate problems")

# 1. Dangling input pin (AND gate with only one input wired)
dangling = {
    "gates": [
        {"id": "a", "type": "INPUT", "value": 1},
        {"id": "x", "type": "AND"},
        {"id": "y", "type": "OUTPUT"},
    ],
    "wires": [
        {"from_gate": "a", "to_gate": "x", "from_pin": 0, "to_pin": 0},
        {"from_gate": "x", "to_gate": "y", "from_pin": 0, "to_pin": 0},
    ],
}
r = post("/api/analyze/faults", {"circuit": dangling})
issues = r.get("issues", []) or r.get("faults", []) or []
print(f"  [{'OK ' if issues else 'BAD'}] dangling AND input -> {len(issues)} issues detected")
for i in issues[:4]:
    print(f"        {i.get('severity','?'):8s} {i.get('type','?'):20s} {(i.get('message','') or '')[:65]}")

# 2. Floating output (no input)
floating = {
    "gates": [
        {"id": "x", "type": "AND"},
        {"id": "y", "type": "OUTPUT"},
    ],
    "wires": [{"from_gate": "x", "to_gate": "y", "from_pin": 0, "to_pin": 0}],
}
r = post("/api/analyze/faults", {"circuit": floating})
issues = r.get("issues", []) or r.get("faults", []) or []
print(f"  [{'OK ' if issues else 'BAD'}] floating AND (no inputs at all) -> {len(issues)} issues")
for i in issues[:4]:
    print(f"        {i.get('severity','?'):8s} {i.get('type','?'):20s} {(i.get('message','') or '')[:65]}")

# 3. Clean half-adder — should report no critical issues
clean_ha = {
    "gates": [
        {"id": "A", "type": "INPUT", "value": 1},
        {"id": "B", "type": "INPUT", "value": 0},
        {"id": "x", "type": "XOR"},
        {"id": "y", "type": "AND"},
        {"id": "S", "type": "OUTPUT"},
        {"id": "C", "type": "OUTPUT"},
    ],
    "wires": [
        {"from_gate": "A", "to_gate": "x", "from_pin": 0, "to_pin": 0},
        {"from_gate": "B", "to_gate": "x", "from_pin": 0, "to_pin": 1},
        {"from_gate": "A", "to_gate": "y", "from_pin": 0, "to_pin": 0},
        {"from_gate": "B", "to_gate": "y", "from_pin": 0, "to_pin": 1},
        {"from_gate": "x", "to_gate": "S", "from_pin": 0, "to_pin": 0},
        {"from_gate": "y", "to_gate": "C", "from_pin": 0, "to_pin": 0},
    ],
}
r = post("/api/analyze/faults", {"circuit": clean_ha})
issues = r.get("issues", []) or r.get("faults", []) or []
critical = [i for i in issues if i.get("severity") == "CRITICAL"]
print(f"  [{'OK ' if not critical else 'BAD'}] clean half adder -> {len(issues)} issues, {len(critical)} critical")


# ── MINIMIZE ─────────────────────────────────────────────────────────────────
section("MINIMIZE — gate-reduction analysis")

# A circuit with redundant gates
redundant = {
    "gates": [
        {"id": "a", "type": "INPUT", "value": 1},
        {"id": "b", "type": "INPUT", "value": 0},
        {"id": "n1", "type": "NOT"},
        {"id": "n2", "type": "NOT"},
        {"id": "and1", "type": "AND"},
        {"id": "y", "type": "OUTPUT"},
    ],
    "wires": [
        {"from_gate": "a",   "to_gate": "n1", "from_pin": 0, "to_pin": 0},
        {"from_gate": "n1",  "to_gate": "n2", "from_pin": 0, "to_pin": 0},
        {"from_gate": "n2",  "to_gate": "and1", "from_pin": 0, "to_pin": 0},
        {"from_gate": "b",   "to_gate": "and1", "from_pin": 0, "to_pin": 1},
        {"from_gate": "and1","to_gate": "y",  "from_pin": 0, "to_pin": 0},
    ],
}
r = post("/api/analyze/minimize", {"circuit": redundant})
print(f"  [{'OK ' if r else 'BAD'}] redundant-NOT circuit:")
print(f"        current_gates = {r.get('current_gates','?')}")
print(f"        benchmark     = {r.get('benchmark','?')}")
print(f"        efficiency    = {r.get('efficiency_score','?')}")
print(f"        suggestions   = {len(r.get('suggestions',[]))}")
for s in r.get("suggestions", [])[:4]:
    print(f"          - {(s if isinstance(s,str) else s.get('message') or s.get('description') or str(s))[:75]}")

# Pre-minimized circuit
optimal = {
    "gates": [
        {"id": "a", "type": "INPUT", "value": 1},
        {"id": "b", "type": "INPUT", "value": 0},
        {"id": "x", "type": "AND"},
        {"id": "y", "type": "OUTPUT"},
    ],
    "wires": [
        {"from_gate": "a", "to_gate": "x", "from_pin": 0, "to_pin": 0},
        {"from_gate": "b", "to_gate": "x", "from_pin": 0, "to_pin": 1},
        {"from_gate": "x", "to_gate": "y", "from_pin": 0, "to_pin": 0},
    ],
}
r = post("/api/analyze/minimize", {"circuit": optimal})
print(f"\n  [{'OK ' if r else 'BAD'}] already-optimal AND circuit:")
print(f"        current_gates = {r.get('current_gates','?')}")
print(f"        efficiency    = {r.get('efficiency_score','?')}")
print(f"        suggestions   = {len(r.get('suggestions',[]))}")
