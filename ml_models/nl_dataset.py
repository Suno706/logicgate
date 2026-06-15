"""
NL -> truth-table dataset generator.

Synthesises (text, truth_table) pairs. Each row is one paraphrase of one
boolean function over n_inputs ∈ {1..4} variables. The generator is the
ML data-engine of this project: heavy diversity in phrasing is what lets
the trained model handle wording it has never seen before.

CSV columns:
    text         -  the English description
    n_inputs     -  1, 2, 3, or 4
    minterms     -  comma-separated minterm indices that evaluate to 1
    tt_bits      -  packed 0/1 string of length 2**n_inputs
    canonical    -  simplest boolean expression (for debug)

Run:
    python -m ml_models.nl_dataset
"""
from __future__ import annotations
import csv
import os
import random
from typing import List, Sequence, Tuple

from .boolean_synth import simplify_expression

# ---------------------------------------------------------------------------
# Lexical pools
# ---------------------------------------------------------------------------

_VAR_POOLS = [
    ('A', 'B', 'C', 'D'),
    ('X', 'Y', 'Z', 'W'),
    ('P', 'Q', 'R', 'S'),
    ('a', 'b', 'c', 'd'),
    ('in1', 'in2', 'in3', 'in4'),
    ('I1', 'I2', 'I3', 'I4'),
    ('s1', 's2', 's3', 's4'),
]

_HI_WORDS = ['1', 'high', 'on', 'true', 'hot', 'active', 'asserted', 'set',
             'up', 'enabled']
_LO_WORDS = ['0', 'low', 'off', 'false', 'quiet', 'inactive', 'cleared',
             'silent', 'down', 'disabled']

_OUT_HI = ['output is 1', 'output is high', 'output goes high',
           'output gives 1', 'output equals 1', 'output stays high',
           'result is 1', 'result is high', 'we get 1', 'output becomes 1',
           'it outputs 1', 'output is active', 'output fires',
           'the output goes on', 'output is asserted', 'we see a 1',
           'output is on', 'output equals high']
_OUT_LO = ['output is 0', 'output is low', 'output gives 0',
           'output equals 0', 'output stays low', 'result is 0',
           'result is low', 'we get 0', 'output stays off',
           'it outputs 0', 'output is quiet', 'output is off']

_VERBS = ['build', 'make', 'design', 'create', 'give me', 'show me',
          'i want', 'i need', 'construct', 'engineer', 'sketch', 'draw',
          'produce', 'set up', 'whip up', 'put together']

_NOUNS = ['circuit', 'logic gate', 'gate', 'design', 'thing',
          'arrangement', 'network', 'configuration', 'block']

_HEDGES = ['please ', 'can you ', '', '', '', '',
           'i would like ', 'could you ', '']

_FILLERS = ['', '', '', '', '', '', '', '',
            ' really', ' simply', ' actually', ' basically']


def _hi() -> str:  return random.choice(_HI_WORDS)
def _lo() -> str:  return random.choice(_LO_WORDS)
def _ohi() -> str: return random.choice(_OUT_HI)
def _olo() -> str: return random.choice(_OUT_LO)


# ---------------------------------------------------------------------------
# Per-row English descriptions
# ---------------------------------------------------------------------------

def _row_phrasing(row: Tuple[int, ...], vars_: Sequence[str]) -> str:
    """Describe one input row in English (many randomised styles)."""
    n = len(row)
    n_high = sum(row)

    # === Single-input rows ===
    if n == 1:
        v = vars_[0]
        if row[0] == 1:
            return random.choice([
                f"{v}={_hi()}", f"{v} is {_hi()}", f"input is {_hi()}",
                f"the input is {_hi()}", f"{v} equals 1", f"input is 1",
                f"input goes high", f"input is set",
            ])
        return random.choice([
            f"{v}={_lo()}", f"{v} is {_lo()}", f"input is {_lo()}",
            f"the input is {_lo()}", f"{v} equals 0", f"input is 0",
            f"input is cleared", f"input goes low",
        ])

    # === All-high / all-low shortcuts ===
    if all(r == 1 for r in row):
        return random.choice([
            "all inputs are high", "every input is high", "all are on",
            f"all {n} inputs are 1", "all are 1", "every input is 1",
            "all signals are high", "all lines are on",
            "every line is active", f"{' and '.join(vars_)} are all high",
            "all variables are 1", "all are asserted",
        ])
    if all(r == 0 for r in row):
        return random.choice([
            "all inputs are low", "every input is low", "all are off",
            f"all {n} inputs are 0", "all are 0", "every input is 0",
            "all signals are quiet", "all lines are off",
            "every line is inactive", f"{' and '.join(vars_)} are all low",
            "all variables are 0", "all are cleared",
            "all signals are silent",
        ])

    # === "Exactly one high" / "all high except X" shortcuts ===
    if n_high == 1:
        hi_var = vars_[row.index(1)]
        if random.random() < 0.3:
            return random.choice([
                f"only {hi_var} is high",
                f"just {hi_var} is on",
                f"exactly one input is high",
                f"{hi_var} alone is 1",
            ])
    if n_high == n - 1:
        lo_var = vars_[row.index(0)]
        if random.random() < 0.3:
            return random.choice([
                f"all are high except {lo_var}",
                f"every input is on except {lo_var}",
                f"all except {lo_var} are high",
            ])

    # === Several phrasing styles ===
    style = random.randint(0, 7)
    if style == 0:
        return ' and '.join(
            f"{v}={_hi() if r else _lo()}" for v, r in zip(vars_, row))
    if style == 1:
        return ', '.join(
            f"{v} is {_hi() if r else _lo()}" for v, r in zip(vars_, row))
    if style == 2:
        return f"input is {''.join(str(b) for b in row)}"
    if style == 3:
        return ' and '.join(
            f"{v} is " + ("on" if r else "off") for v, r in zip(vars_, row))
    if style == 4:
        return ', '.join(
            f"{v} " + ("high" if r else "low") for v, r in zip(vars_, row))
    if style == 5:
        # ordinal phrasing
        ords = ['first', 'second', 'third', 'fourth']
        pieces = []
        for i, r in enumerate(row):
            if i >= len(ords): break
            pieces.append(f"{ords[i]} input is {_hi() if r else _lo()}")
        return ' and '.join(pieces) if pieces else f"input is {''.join(str(b) for b in row)}"
    if style == 6:
        # mixed: some var=val, others descriptive
        return ' but '.join(
            f"{v} {'high' if r else 'low'}" for v, r in zip(vars_, row))
    # style 7: bit pattern with "for"
    return f"for {''.join(str(b) for b in row)}"


def _rows_phrasing(rows: List[Tuple[int, ...]], vars_: Sequence[str]) -> str:
    """Describe a set of 1-rows."""
    if len(rows) == 1:
        return _row_phrasing(rows[0], vars_)
    style = random.randint(0, 4)
    if style == 0:
        bits = [''.join(str(b) for b in r) for r in rows]
        return "input is " + ' or '.join(bits)
    if style == 1:
        bits = [''.join(str(b) for b in r) for r in rows]
        return "rows " + ', '.join(bits)
    if style == 2:
        bits = [''.join(str(b) for b in r) for r in rows]
        return random.choice(["for inputs ", "on rows ", "when input is "]) + ', '.join(bits)
    if style == 3:
        return ' or '.join('(' + _row_phrasing(r, vars_) + ')' for r in rows)
    # style 4: itemise with "or when"
    return ' or when '.join(_row_phrasing(r, vars_) for r in rows)


# ---------------------------------------------------------------------------
# Sentence templates (the model learns these are interchangeable)
# ---------------------------------------------------------------------------

_TEMPLATES = [
    "{verb} a {noun} where {out} when {cond}",
    "{verb} a {noun} that gives {out_short} when {cond}",
    "{out} when {cond}",
    "if {cond} then {out}",
    "if {cond}, {out}",
    "when {cond}, {out}",
    "when {cond} then {out}",
    "design a {noun} so that {out} only when {cond}",
    "i want a {noun} where the {out} when {cond}",
    "{verb} something where {out} for {cond}",
    "{verb} a {noun} with {n_inputs} inputs that outputs 1 when {cond}",
    "{out_short} when {cond}, else 0",
    "{out_short} when {cond}, otherwise 0",
    "the output should be 1 when {cond}",
    "{verb} {out_short} only if {cond}",
    "output 1 when {cond}",
    "the output goes high when {cond}",
    "output stays 0 except when {cond}",
    "the {noun} should fire when {cond}",
    "the {noun} produces 1 when {cond}",
    "give me a {noun} that {out_short} on {cond}",
    "i need a {noun} where the result is 1 when {cond}",
    "{verb} something that outputs 1 if {cond}",
    "{verb} a {noun} that outputs 1 on {cond}",
    "the {noun} fires when {cond}",
    "we want output high when {cond}",
    "output should be high when {cond}",
    "the result is 1 only when {cond}",
    "the {noun} returns 1 when {cond}",
    "make it so the output is 1 only when {cond}",
    "show me a {noun} where {out} when {cond}",
    "the gate's output is 1 when {cond}",
    "result is high when {cond}",
    "{verb} a {noun} for which {out} when {cond}",
    "i would like a {noun} that outputs 1 when {cond}",
    "the {noun} should output 1 when {cond}",
    "output high if {cond}",
    "{out_short} for {cond}",
    "1 when {cond}",
    "high output when {cond}",
]


def _render_one(cond_text: str, n_inputs: int) -> str:
    tmpl = random.choice(_TEMPLATES)
    txt = (tmpl
           .replace('{verb}', random.choice(_VERBS))
           .replace('{noun}', random.choice(_NOUNS))
           .replace('{out}', _ohi())
           .replace('{out_short}', random.choice(
               ['1', 'high', 'output 1', 'output high', 'a 1', 'on']))
           .replace('{cond}', cond_text)
           .replace('{n_inputs}', str(n_inputs)))
    if random.random() < 0.25:
        txt = random.choice(_HEDGES) + txt
    if random.random() < 0.15:
        txt = txt + random.choice([' please', '.', '?', ''])
    return txt.lower()


# ---------------------------------------------------------------------------
# Special phrase generators  -  common gate-name shortcuts and negation
# ---------------------------------------------------------------------------

def _named_gate_phrasing(n_in: int, gate: str,
                         vars_: Sequence[str]) -> str:
    """Phrasings that mention the gate name directly."""
    v = vars_[:n_in]
    if gate == 'AND':
        return random.choice([
            f"build an AND of {' and '.join(v)}",
            f"AND gate with inputs {' and '.join(v)}",
            f"output is the AND of {', '.join(v)}",
            f"make an AND between {' and '.join(v)}",
            f"AND {' '.join(v)}",
            f"give me an AND gate",
            f"plain AND gate",
            f"output equals the AND of all inputs",
        ])
    if gate == 'OR':
        return random.choice([
            f"build an OR of {' and '.join(v)}",
            f"OR gate with inputs {' and '.join(v)}",
            f"output is the OR of {', '.join(v)}",
            f"OR {' '.join(v)}",
            f"give me an OR gate",
            f"output equals the OR of all inputs",
        ])
    if gate == 'NAND':
        return random.choice([
            f"NAND of {' and '.join(v)}",
            f"build a NAND gate",
            f"output is the NAND of {', '.join(v)}",
            f"opposite of AND",
            f"inverse of AND",
            f"AND but inverted",
            f"NOT all inputs high",
            f"output 0 only when all inputs are 1",
        ])
    if gate == 'NOR':
        return random.choice([
            f"NOR of {' and '.join(v)}",
            f"build a NOR gate",
            f"output is the NOR of {', '.join(v)}",
            f"opposite of OR",
            f"inverse of OR",
            f"OR but inverted",
            f"output 1 only when all inputs are 0",
            f"neither {v[0]} nor {v[1] if len(v)>1 else v[0]}",
            f"none of the inputs are high",
        ])
    if gate == 'XOR':
        return random.choice([
            f"XOR of {' and '.join(v)}",
            f"build an XOR gate",
            f"output is the XOR of {', '.join(v)}",
            f"output 1 when {v[0]} and {v[1] if len(v)>1 else v[0]} differ",
            f"output high when inputs are different",
            f"odd number of inputs are 1",
            f"parity of inputs",
            f"{v[0]} not equal to {v[1] if len(v)>1 else v[0]}",
            f"exactly one input is 1",
        ]) if n_in == 2 else f"XOR of {' '.join(v)}"
    if gate == 'XNOR':
        return random.choice([
            f"XNOR of {' and '.join(v)}",
            f"build an XNOR gate",
            f"output 1 when {v[0]} equals {v[1] if len(v)>1 else v[0]}",
            f"output high when inputs match",
            f"opposite of XOR",
            f"equality of inputs",
            f"{v[0]} equals {v[1] if len(v)>1 else v[0]}",
            f"both inputs the same",
            f"even number of inputs are 1",
        ]) if n_in == 2 else f"XNOR of {' '.join(v)}"
    if gate == 'NOT':
        return random.choice([
            f"NOT gate", f"invert {v[0]}", f"inverter",
            f"complement of {v[0]}", f"opposite of {v[0]}",
            f"input 1 gives 0 and input 0 gives 1",
            f"the input is inverted", f"NOT {v[0]}",
            f"output is the complement of input",
        ])
    return f"{gate} of {' '.join(v)}"


def _count_constraint_phrasing(n_in: int, k: int, kind: str,
                               vars_: Sequence[str]) -> str:
    """Counting-style phrasings: 'exactly k inputs are 1' etc."""
    kw = random.choice(['inputs', 'lines', 'signals', 'of them',
                        'variables', 'of the inputs'])
    state = random.choice(['high', 'on', '1', 'hot', 'active'])
    quantifier = {
        'exactly':   random.choice(['exactly', 'precisely', 'just']),
        'at_least':  random.choice(['at least', 'no fewer than', 'at minimum']),
        'at_most':   random.choice(['at most', 'no more than', 'up to']),
        'more':      random.choice(['more than', 'over', 'greater than']),
        'less':      random.choice(['fewer than', 'less than', 'under']),
    }[kind]
    return f"{quantifier} {k} {kw} are {state}"


# ---------------------------------------------------------------------------
# Boolean expression for canonical column
# ---------------------------------------------------------------------------

def _sop_expression(minterms: List[int], n: int,
                    vars_: Sequence[str]) -> str:
    if not minterms:                          return '0'
    if len(minterms) == (1 << n):             return '1'
    terms = []
    for m in minterms:
        bits = format(m, f'0{n}b')
        lits = [v if b == '1' else f'~{v}' for v, b in zip(vars_, bits)]
        terms.append('(' + ' & '.join(lits) + ')')
    return ' | '.join(terms)


# ---------------------------------------------------------------------------
# Truth-table sampling
# ---------------------------------------------------------------------------

def _enumerate_or_sample_tables(n: int, cap: int) -> List[int]:
    total = 1 << (1 << n)
    if total <= cap:
        return list(range(total))
    seen = set()
    while len(seen) < cap:
        seen.add(random.randrange(total))
    return list(seen)


# Gate -> truth-table mask shortcut (so we can target named-gate phrasings)
def _gate_mask(n: int, gate: str) -> int:
    n_rows = 1 << n
    mask = 0
    for i in range(n_rows):
        bits = [(i >> (n - 1 - b)) & 1 for b in range(n)]
        if gate == 'AND':  out = all(bits)
        elif gate == 'OR':  out = any(bits)
        elif gate == 'NAND':out = not all(bits)
        elif gate == 'NOR': out = not any(bits)
        elif gate == 'XOR': out = sum(bits) % 2 == 1
        elif gate == 'XNOR':out = sum(bits) % 2 == 0
        elif gate == 'NOT' and n == 1: out = not bits[0]
        else: out = False
        if out: mask |= (1 << i)
    return mask


def _count_mask(n: int, k: int, kind: str) -> int:
    n_rows = 1 << n
    mask = 0
    for i in range(n_rows):
        c = bin(i).count('1')
        if kind == 'exactly':   ok = (c == k)
        elif kind == 'at_least':ok = (c >= k)
        elif kind == 'at_most': ok = (c <= k)
        elif kind == 'more':    ok = (c >  k)
        elif kind == 'less':    ok = (c <  k)
        else: ok = False
        if ok: mask |= (1 << i)
    return mask


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def generate_dataset(out_path: str,
                     samples_per_function: int = 12,
                     cap_4input: int = 5000,
                     seed: int = 0) -> int:
    """
    Generate the full training set. Default scale: ~200K rows.
    """
    random.seed(seed)
    rows_written = 0
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    plan = [
        (1, _enumerate_or_sample_tables(1, 4),     samples_per_function * 40),
        (2, _enumerate_or_sample_tables(2, 16),    samples_per_function * 25),
        (3, _enumerate_or_sample_tables(3, 256),   samples_per_function * 6),
        (4, _enumerate_or_sample_tables(4, cap_4input), samples_per_function),
    ]

    with open(out_path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['text', 'n_inputs', 'minterms', 'tt_bits', 'canonical'])

        # === 1. The exhaustive plan: for every function, many paraphrases ===
        for n_in, tables, per in plan:
            n_rows = 1 << n_in
            for tt_mask in tables:
                minterms = [i for i in range(n_rows) if (tt_mask >> i) & 1]
                tt_bits  = ''.join('1' if (tt_mask >> i) & 1 else '0'
                                    for i in range(n_rows))
                vars_canon = _VAR_POOLS[0][:n_in]
                raw_expr   = _sop_expression(minterms, n_in, vars_canon)
                try:
                    canonical = simplify_expression(raw_expr)
                except Exception:
                    canonical = raw_expr

                for _ in range(per):
                    vars_ = random.choice(_VAR_POOLS)[:n_in]
                    if minterms:
                        row_tuples = [tuple((m >> (n_in - 1 - b)) & 1
                                            for b in range(n_in))
                                       for m in minterms]
                        cond = _rows_phrasing(row_tuples, vars_)
                    else:
                        cond = "the output is never high"
                    text = _render_one(cond, n_in)
                    w.writerow([text, n_in,
                                ','.join(str(m) for m in minterms),
                                tt_bits, canonical])
                    rows_written += 1

        # === 2. Heavy boost for named gates (so model learns "NAND" etc.) ===
        for n_in in (1, 2, 3, 4):
            gates_for_n = ['AND', 'OR', 'NAND', 'NOR']
            if n_in == 2: gates_for_n += ['XOR', 'XNOR']
            if n_in == 1: gates_for_n = ['NOT']
            for gate in gates_for_n:
                mask = _gate_mask(n_in, gate)
                minterms = [i for i in range(1 << n_in) if (mask >> i) & 1]
                tt_bits = ''.join('1' if (mask >> i) & 1 else '0'
                                   for i in range(1 << n_in))
                for _ in range(500):
                    vars_ = random.choice(_VAR_POOLS)[:n_in]
                    text = _named_gate_phrasing(n_in, gate, vars_)
                    if random.random() < 0.3:
                        # Wrap with a request verb
                        text = random.choice([
                            f"{random.choice(_VERBS)} {text}",
                            f"i want {text}",
                            f"design {text}",
                            f"build {text}",
                        ])
                    w.writerow([text.lower(), n_in,
                                ','.join(str(m) for m in minterms),
                                tt_bits, gate])
                    rows_written += 1

        # === 3. Counting constraints (exactly N, at least N, etc.) ===
        for n_in in (2, 3, 4):
            for k in range(n_in + 1):
                for kind in ('exactly', 'at_least', 'at_most', 'more', 'less'):
                    mask = _count_mask(n_in, k, kind)
                    if mask == 0 or mask == (1 << (1 << n_in)) - 1:
                        continue
                    minterms = [i for i in range(1 << n_in) if (mask >> i) & 1]
                    tt_bits = ''.join('1' if (mask >> i) & 1 else '0'
                                       for i in range(1 << n_in))
                    for _ in range(80):
                        vars_ = random.choice(_VAR_POOLS)[:n_in]
                        cond = _count_constraint_phrasing(n_in, k, kind, vars_)
                        text = _render_one(cond, n_in)
                        w.writerow([text.lower(), n_in,
                                    ','.join(str(m) for m in minterms),
                                    tt_bits, f'count_{kind}_{k}'])
                        rows_written += 1

        # === 3b. Counting with "of N inputs/signals/lines" ===
        for n_in in (3, 4):
            for k in range(1, n_in):
                for kind in ('exactly', 'at_least', 'at_most', 'more', 'less'):
                    mask = _count_mask(n_in, k, kind)
                    if mask == 0 or mask == (1 << (1 << n_in)) - 1:
                        continue
                    minterms = [i for i in range(1 << n_in) if (mask >> i) & 1]
                    tt_bits = ''.join('1' if (mask >> i) & 1 else '0'
                                       for i in range(1 << n_in))
                    qmap = {'exactly':'exactly','at_least':'at least',
                            'at_most':'at most','more':'more than','less':'fewer than'}
                    k_word = {1:'one',2:'two',3:'three',4:'four'}.get(k, str(k))
                    n_word = {2:'two',3:'three',4:'four'}.get(n_in, str(n_in))
                    for _ in range(80):
                        kw = random.choice(['inputs','lines','signals'])
                        state = random.choice(['high','on','1','hot','asserted'])
                        # "exactly two of four signals are high"
                        text = (f"{qmap[kind]} {k_word} of {n_word} {kw} "
                                f"are {state}")
                        rendered = _render_one(text, n_in)
                        w.writerow([rendered.lower(), n_in,
                                    ','.join(str(m) for m in minterms),
                                    tt_bits, f'count_of_{kind}_{k}'])
                        rows_written += 1

        # === 3c. "Except when" / "unless" inverted conditions ===
        # For a random tt, generate a phrasing of the COMPLEMENT framed as
        # "output is 1 except when X"  -  equivalent to "X -> output 0".
        for n_in in (1, 2, 3):
            for _ in range(3000):
                tt_mask = random.randrange(1 << (1 << n_in))
                if tt_mask == 0 or tt_mask == (1 << (1 << n_in)) - 1:
                    continue
                comp_mask = ((1 << (1 << n_in)) - 1) ^ tt_mask
                comp_mt = [i for i in range(1 << n_in) if (comp_mask >> i) & 1]
                if not comp_mt:
                    continue
                minterms = [i for i in range(1 << n_in) if (tt_mask >> i) & 1]
                tt_bits = ''.join('1' if (tt_mask >> i) & 1 else '0'
                                   for i in range(1 << n_in))
                vars_ = random.choice(_VAR_POOLS)[:n_in]
                row_tuples = [tuple((m >> (n_in - 1 - b)) & 1
                                    for b in range(n_in))
                              for m in comp_mt]
                cond = _rows_phrasing(row_tuples, vars_)
                tmpl = random.choice([
                    "output is 1 except when {cond}",
                    "output high except when {cond}",
                    "output 1 unless {cond}",
                    "result is 1 unless {cond}",
                    "gives 1 except when {cond}",
                    "fires unless {cond}",
                    "output is high except when {cond}",
                ])
                text = tmpl.replace('{cond}', cond).lower()
                w.writerow([text, n_in,
                            ','.join(str(m) for m in minterms),
                            tt_bits, _sop_expression(minterms, n_in, vars_)])
                rows_written += 1

        # === 4. Negated output specs: "output is 0 when X" ===
        #     For every (n, mask) we also emit phrasings of its complement
        #     framed as "output is 0 when X"  -  teaches the model that the
        #     stated condition is when the output is LOW.
        for n_in in (1, 2, 3):
            for _ in range(2000):
                tt_mask = random.randrange(1 << (1 << n_in))
                # Skip degenerate constant functions
                if tt_mask == 0 or tt_mask == (1 << (1 << n_in)) - 1:
                    continue
                comp_mask = ((1 << (1 << n_in)) - 1) ^ tt_mask
                comp_minterms = [i for i in range(1 << n_in)
                                  if (comp_mask >> i) & 1]
                minterms = [i for i in range(1 << n_in) if (tt_mask >> i) & 1]
                tt_bits = ''.join('1' if (tt_mask >> i) & 1 else '0'
                                   for i in range(1 << n_in))
                vars_ = random.choice(_VAR_POOLS)[:n_in]
                # Describe the COMPLEMENT rows as the condition under which
                # the output is 0.
                if not comp_minterms:
                    continue
                row_tuples = [tuple((m >> (n_in - 1 - b)) & 1
                                    for b in range(n_in))
                              for m in comp_minterms]
                cond = _rows_phrasing(row_tuples, vars_)
                tmpl = random.choice([
                    "output is 0 when {cond}",
                    "output is low when {cond}",
                    "output stays 0 when {cond}",
                    "the gate should not output 1 when {cond}",
                    "result is 0 when {cond}",
                    "give 0 when {cond}",
                    "output stays low for {cond}",
                    "the output is 0 only when {cond}",
                ])
                text = tmpl.replace('{cond}', cond).lower()
                w.writerow([text, n_in,
                            ','.join(str(m) for m in minterms),
                            tt_bits, _sop_expression(minterms, n_in, vars_)])
                rows_written += 1

        # === 5. Bit-pattern style: "for input 0110 output is 1" ===
        for n_in in (2, 3, 4):
            for _ in range(2000):
                # Pick 1-3 random rows to set as 1
                k = random.randint(1, min(3, 1 << n_in))
                ones = random.sample(range(1 << n_in), k)
                tt_mask = 0
                for o in ones: tt_mask |= (1 << o)
                minterms = sorted(ones)
                tt_bits = ''.join('1' if (tt_mask >> i) & 1 else '0'
                                   for i in range(1 << n_in))
                bit_strs = [format(o, f'0{n_in}b') for o in ones]
                tmpl = random.choice([
                    f"output is 1 for input {' or '.join(bit_strs)}",
                    f"give 1 only for input {' or '.join(bit_strs)}",
                    f"output high on rows {', '.join(bit_strs)}",
                    f"fire on inputs {', '.join(bit_strs)}",
                    f"output 1 when input is " + (' or '.join(bit_strs)),
                    f"input {bit_strs[0]} gives 1" + (
                        ", input " + " gives 1, input ".join(bit_strs[1:]) + " gives 1"
                        if len(bit_strs) > 1 else ""),
                ])
                w.writerow([tmpl.lower(), n_in,
                            ','.join(str(m) for m in minterms),
                            tt_bits, _sop_expression(
                                minterms, n_in, _VAR_POOLS[0][:n_in])])
                rows_written += 1

        # === 5b. Named digital-circuit phrasings ===
        # These don't get exhaustively enumerated against truth tables (they
        # have too many inputs to fit MAX_INPUTS=4); the model just learns to
        # treat them as "I don't know the bits, but route this to the named
        # template." We tag them with a sentinel truth table that won't be
        # used at inference  -  they always match a template first.
        NAMED_PHRASINGS = {
            'binary to gray':   ['binary to gray code', 'convert binary to gray',
                                 '4-bit binary to gray', 'gray code generator',
                                 'binary to gray converter'],
            'gray to binary':   ['gray to binary code', 'convert gray to binary',
                                 '4-bit gray to binary', 'gray code decoder'],
            'even parity':      ['even parity generator', 'even parity bit',
                                 'compute even parity', 'parity bit even'],
            'odd parity':       ['odd parity generator', 'odd parity bit',
                                 'compute odd parity', 'parity bit odd'],
            'parity checker':   ['parity error detector', 'parity check',
                                 'check parity of inputs', 'detect parity error'],
            'magnitude comparator': ['2-bit magnitude comparator',
                                     'compare magnitude of two 2-bit numbers',
                                     'which 2-bit number is greater'],
            "1's complement":   ["1's complement of 4 bits", 'ones complement',
                                 'bitwise inverter', 'invert all bits'],
            'bcd to excess-3':  ['bcd to excess 3', 'convert bcd to excess-3 code',
                                 'bcd2excess3'],
            'excess-3 to bcd':  ['excess 3 to bcd', 'convert excess-3 to bcd'],
        }
        # We can't write a real truth table for these (too many inputs).
        # Emit them with n_inputs=4 and tt_bits='0'*16  -  they'll route via
        # the template matcher in question_solver, not the ML model. This
        # mostly trains the ML to NOT confidently misclassify them.
        for canonical, phrasings in NAMED_PHRASINGS.items():
            for p in phrasings:
                for _ in range(30):
                    txt = random.choice([
                        f"{random.choice(_VERBS)} a {p}",
                        f"{p}",
                        f"i want a {p}",
                        f"design a {p}",
                        f"build a {p}",
                        f"can you make a {p}",
                    ]).lower()
                    w.writerow([txt, 4, '', '0' * 16, canonical])
                    rows_written += 1

        # === 6. Identity / passthrough / constant edge cases ===
        for _ in range(500):
            # 1-input identity
            vars_ = random.choice(_VAR_POOLS)[:1]
            text = random.choice([
                f"output equals {vars_[0]}",
                f"output is the same as input",
                f"passthrough",
                f"input 1 gives 1 and input 0 gives 0",
                f"{vars_[0]} is the output",
                f"output mirrors the input",
                f"buffer",
                f"buffer gate",
            ])
            w.writerow([text.lower(), 1, '1', '01', vars_[0]])
            rows_written += 1

    return rows_written


if __name__ == '__main__':
    out = os.path.join(os.path.dirname(__file__), '..',
                       'data', 'nl_training.csv')
    n = generate_dataset(out)
    print(f"wrote {n} rows to {out}")
