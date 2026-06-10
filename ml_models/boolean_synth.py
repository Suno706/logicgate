"""
BooleanSynthesizer  -  convert a boolean expression into a gate/wire JSON
that the frontend can render.

Supports:
  Operators:   & && AND . *      -> AND
               | || OR + v       -> OR
               ~ ! NOT '         -> NOT (prefix or postfix ')
               ^ XOR ⊕            -> XOR
               NAND NOR XNOR
  Constants:   0 1 TRUE FALSE
  Identifiers: A, B, C, foo_1   (case-preserved as labels)
  Grouping:    ( ... )

Gate-set restriction (target_gates):
  ['NAND']            -> rebuild using ONLY NAND
  ['NOR']             -> rebuild using ONLY NOR
  ['AND','OR','NOT']  -> classical 3-gate form (default)
  any combination of {AND, OR, NOT, NAND, NOR, XOR, XNOR}

Macro building blocks (also accepted in target_gates):
  'HA'   -> XOR terms become HA Sum pins, AND terms become HA Carry pins
            (the classic "full adder = 2 HA + OR" generalised to ANY function;
            leftover OR/NOT are plain glue gates)
  'FA'   -> same idea with Cin tricks: XOR=FA(a,b,0).S, AND=FA(a,b,0).Co,
            OR=FA(a,b,1).Co (majority with a constant 1)
  'MUX2' -> full Shannon expansion: ANY truth table as a tree of 2:1 muxes
  'DFF' / 'TFF' / 'JKFF' / 'SRLATCH'
         -> the combinational core is built normally, then every output is
            registered through the storage element (D=f; J=f,K=~f; S=f,R=~f)
            with a shared CLK. Mixing macros with primitive gates is always
            allowed, which is what makes every truth table reachable.

The output is:
  {
    'gates': [{'id', 'type', 'x', 'y', 'value'?, 'label'?, 'clockHz'?}, ...],
    'wires': [{'id', 'from_gate', 'from_pin', 'to_gate', 'to_pin'}, ...]
  }
No external API, no LLM. Pure Python.
"""

import re
from itertools import count


class BooleanParseError(ValueError):
    pass


# -- Lexer --------------------------------------------------------------------

# Multi-char operator words come first.
_TOKEN_SPEC = [
    (r'\s+',                None),
    (r'NAND\b',             'NAND'),
    (r'NOR\b',              'NOR'),
    (r'XNOR\b',             'XNOR'),
    (r'XOR\b',              'XOR'),
    (r'AND\b',              'AND'),
    (r'OR\b',               'OR'),
    (r'NOT\b',              'NOT'),
    (r'TRUE\b',             'CONST1'),
    (r'FALSE\b',            'CONST0'),
    (r'&&|&|\.|\*|·',       'AND'),
    (r'\|\||\||\+',         'OR'),
    (r'\^|⊕',               'XOR'),
    (r'~|!',                'NOT'),
    (r"'",                  'NOT_POST'),
    (r'\(',                 'LP'),
    (r'\)',                 'RP'),
    (r'[01]',               'CONST'),
    (r'[A-Za-z_][A-Za-z0-9_]*', 'IDENT'),
]

_TOKEN_RE = [(re.compile(p, re.IGNORECASE), t) for p, t in _TOKEN_SPEC]


def _tokenize(src: str):
    pos    = 0
    tokens = []
    s      = src
    while pos < len(s):
        matched = False
        for rx, ttype in _TOKEN_RE:
            m = rx.match(s, pos)
            if not m:
                continue
            matched = True
            text    = m.group(0)
            pos     = m.end()
            if ttype is None:
                break  # whitespace
            if ttype == 'CONST':
                tokens.append(('CONST1' if text == '1' else 'CONST0', text))
            else:
                tokens.append((ttype, text))
            break
        if not matched:
            raise BooleanParseError(
                f"Unexpected character {s[pos]!r} at position {pos}"
            )
    tokens.append(('EOF', ''))
    return tokens


# -- Parser -------------------------------------------------------------------
#
# Grammar (precedence low -> high):
#   expr     = or_expr
#   or_expr  = xor_expr (('OR'|'NOR') xor_expr)*
#   xor_expr = and_expr (('XOR'|'XNOR') and_expr)*
#   and_expr = unary    (('AND'|'NAND') unary)*
#   unary    = 'NOT' unary | primary postfix?
#   postfix  = "'"
#   primary  = IDENT | CONST0 | CONST1 | '(' expr ')'
#
# AST node = ('VAR', name) | ('CONST', 0|1) | ('NOT', child)
#          | ('AND'|'OR'|'XOR'|'NAND'|'NOR'|'XNOR', left, right)


class _Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.i    = 0

    def _peek(self):
        return self.toks[self.i][0]

    def _eat(self, *types):
        if self._peek() in types:
            tok = self.toks[self.i]
            self.i += 1
            return tok
        return None

    def _expect(self, t):
        tok = self._eat(t)
        if tok is None:
            raise BooleanParseError(
                f"Expected {t}, got {self._peek()} ({self.toks[self.i][1]!r})"
            )
        return tok

    def parse(self):
        node = self._or()
        self._expect('EOF')
        return node

    def _or(self):
        left = self._xor()
        while self._peek() in ('OR', 'NOR'):
            op = self._toks_pop()
            right = self._xor()
            left  = (op, left, right)
        return left

    def _xor(self):
        left = self._and()
        while self._peek() in ('XOR', 'XNOR'):
            op = self._toks_pop()
            right = self._and()
            left  = (op, left, right)
        return left

    def _and(self):
        left = self._unary()
        while self._peek() in ('AND', 'NAND'):
            op = self._toks_pop()
            right = self._unary()
            left  = (op, left, right)
        return left

    def _toks_pop(self):
        t = self.toks[self.i][0]
        self.i += 1
        return t

    def _unary(self):
        if self._peek() == 'NOT':
            self._toks_pop()
            return ('NOT', self._unary())
        node = self._primary()
        # postfix '  applies once
        while self._peek() == 'NOT_POST':
            self._toks_pop()
            node = ('NOT', node)
        return node

    def _primary(self):
        t = self._peek()
        if t == 'IDENT':
            name = self.toks[self.i][1]
            self.i += 1
            return ('VAR', name)
        if t == 'CONST0':
            self.i += 1
            return ('CONST', 0)
        if t == 'CONST1':
            self.i += 1
            return ('CONST', 1)
        if t == 'LP':
            self.i += 1
            n = self._or()
            self._expect('RP')
            return n
        raise BooleanParseError(
            f"Unexpected token {t} ({self.toks[self.i][1]!r})"
        )


def parse_expression(expr: str):
    return _Parser(_tokenize(expr)).parse()


# -- Variable extraction (for input labels in canonical order) ----------------

def _collect_vars(node, out):
    t = node[0]
    if t == 'VAR':
        if node[1] not in out:
            out.append(node[1])
    elif t == 'CONST':
        return
    elif t == 'NOT':
        _collect_vars(node[1], out)
    else:
        _collect_vars(node[1], out)
        _collect_vars(node[2], out)


# -- Rewriting to a target gate set -------------------------------------------
#
# Expand multi-input/exotic gates into a base of {AND, OR, NOT, XOR}, then
# rewrite to the requested target.

def _expand_to_basic(node):
    """Reduce NAND/NOR/XNOR to AND/OR/NOT/XOR equivalents."""
    t = node[0]
    if t in ('VAR', 'CONST'):
        return node
    if t == 'NOT':
        return ('NOT', _expand_to_basic(node[1]))
    L, R = _expand_to_basic(node[1]), _expand_to_basic(node[2])
    if t == 'NAND':
        return ('NOT', ('AND', L, R))
    if t == 'NOR':
        return ('NOT', ('OR',  L, R))
    if t == 'XNOR':
        return ('NOT', ('XOR', L, R))
    return (t, L, R)


def _to_nand_only(node):
    """Rewrite to NAND-only. Assumes basic-gate input."""
    n = _expand_to_basic(node)
    return _nandify(n)


def _nandify(n):
    t = n[0]
    if t in ('VAR', 'CONST'):
        return n
    if t == 'NOT':
        x = _nandify(n[1])
        return ('NAND', x, x)
    if t == 'AND':
        a, b = _nandify(n[1]), _nandify(n[2])
        nand = ('NAND', a, b)
        return ('NAND', nand, nand)               # NOT(NAND(a,b))
    if t == 'OR':
        a, b = _nandify(n[1]), _nandify(n[2])
        na = ('NAND', a, a)
        nb = ('NAND', b, b)
        return ('NAND', na, nb)                   # De Morgan
    if t == 'XOR':
        a, b = _nandify(n[1]), _nandify(n[2])
        x   = ('NAND', a, b)
        a1  = ('NAND', a, x)
        b1  = ('NAND', b, x)
        return ('NAND', a1, b1)
    # NAND already
    return (t, _nandify(n[1]), _nandify(n[2]))


def _to_nor_only(node):
    n = _expand_to_basic(node)
    return _norify(n)


def _norify(n):
    t = n[0]
    if t in ('VAR', 'CONST'):
        return n
    if t == 'NOT':
        x = _norify(n[1])
        return ('NOR', x, x)
    if t == 'OR':
        a, b = _norify(n[1]), _norify(n[2])
        nor = ('NOR', a, b)
        return ('NOR', nor, nor)
    if t == 'AND':
        a, b = _norify(n[1]), _norify(n[2])
        na = ('NOR', a, a)
        nb = ('NOR', b, b)
        return ('NOR', na, nb)
    if t == 'XOR':
        # XOR(a,b) = (a NOR b) NOR (a NOR a NOR (b NOR b))  -  derive via basic
        a, b = _norify(n[1]), _norify(n[2])
        not_a = ('NOR', a, a)
        not_b = ('NOR', b, b)
        t1 = ('NOR', a, not_b)        # a · b'  (via De Morgan over NOR)
        t1 = ('NOR', t1, t1)
        t2 = ('NOR', not_a, b)
        t2 = ('NOR', t2, t2)
        return ('NOR', ('NOR', t1, t2), ('NOR', t1, t2))
    return (t, _norify(n[1]), _norify(n[2]))


# -- Macro building blocks -----------------------------------------------------
#
# Macro AST node: ('MPIN', macro_type, out_pin, (child, child, ...))
# One macro *instance* is shared by all MPIN nodes with the same children,
# so HA Sum and HA Carry of the same operands come out of one HA box.

COMB_MACROS = {'HA', 'FA', 'MUX2'}
SEQ_MACROS  = {'DFF', 'TFF', 'JKFF', 'SRLATCH'}
MACRO_GATES = COMB_MACROS | SEQ_MACROS


def split_target(target_gates):
    """Split a target_gates list into (combinational_part, sequential_macros)."""
    if not target_gates:
        return None, []
    up   = [g.upper() for g in target_gates]
    seq  = [g for g in up if g in SEQ_MACROS]
    comb = [g for g in up if g not in SEQ_MACROS]
    return (comb or None), seq


def _macroify_adders(n, macros):
    """
    Rewrite XOR/AND (and OR, for FA) sub-trees into adder-macro output pins.
    Anything the macro can't express stays as a primitive glue gate — the
    user explicitly allows mixing, which is what makes this universal.
    """
    t = n[0]
    if t in ('VAR', 'CONST'):
        return n
    if t == 'NOT':
        return ('NOT', _macroify_adders(n[1], macros))
    L = _macroify_adders(n[1], macros)
    R = _macroify_adders(n[2], macros)
    use_ha = 'HA' in macros
    if t == 'XOR':
        return (('MPIN', 'HA', 0, (L, R)) if use_ha
                else ('MPIN', 'FA', 0, (L, R, ('CONST', 0))))
    if t == 'AND':
        return (('MPIN', 'HA', 1, (L, R)) if use_ha
                else ('MPIN', 'FA', 1, (L, R, ('CONST', 0))))
    if t == 'OR' and not use_ha and 'FA' in macros:
        # majority(a, b, 1) = a | b  ->  FA carry-out with Cin tied to 1
        return ('MPIN', 'FA', 1, (L, R, ('CONST', 1)))
    return (t, L, R)


def _cofactor(n, var, val):
    """Substitute var := val (0/1) into the AST."""
    t = n[0]
    if t == 'VAR':
        return ('CONST', val) if n[1] == var else n
    if t == 'CONST':
        return n
    if t == 'NOT':
        return ('NOT', _cofactor(n[1], var, val))
    return (t, _cofactor(n[1], var, val), _cofactor(n[2], var, val))


def _const_fold(n):
    """Fold constants in a basic-gate AST (AND/OR/XOR/NOT/VAR/CONST)."""
    t = n[0]
    if t in ('VAR', 'CONST'):
        return n
    if t == 'NOT':
        c = _const_fold(n[1])
        if c[0] == 'CONST':
            return ('CONST', 1 - c[1])
        if c[0] == 'NOT':
            return c[1]
        return ('NOT', c)
    L, R = _const_fold(n[1]), _const_fold(n[2])
    for a, b in ((L, R), (R, L)):
        if a[0] == 'CONST':
            v = a[1]
            if t == 'AND':
                return b if v else ('CONST', 0)
            if t == 'OR':
                return ('CONST', 1) if v else b
            if t == 'XOR':
                return _const_fold(('NOT', b)) if v else b
    return (t, L, R)


def _to_mux_tree(n):
    """
    Shannon expansion: f = MUX2(f|v=0, f|v=1, sel=v). A 2:1 mux with
    constants is functionally complete, so ANY truth table reduces to a
    tree of MUX2 blocks — no other gate needed.
    """
    variables = []
    _collect_vars(n, variables)

    def rec(node, vs):
        node = _const_fold(node)
        if node[0] in ('CONST', 'VAR'):
            return node
        # Skip variables the node no longer depends on.
        while vs:
            v = vs[0]
            f0 = _const_fold(_cofactor(node, v, 0))
            f1 = _const_fold(_cofactor(node, v, 1))
            if f0 == f1:
                node = f0
                vs = vs[1:]
                if node[0] in ('CONST', 'VAR'):
                    return node
                continue
            return ('MPIN', 'MUX2', 0,
                    (rec(f0, vs[1:]), rec(f1, vs[1:]), ('VAR', v)))
        return node
    return rec(n, variables)


def _restrict_to(node, allowed):
    """Generic restriction. If a gate type is not allowed, expand it."""
    allowed = {g.upper() for g in allowed}

    # Macro building blocks first. Sequential macros are handled as an
    # output register stage by the caller — strip them here.
    comb_macros = allowed & COMB_MACROS
    allowed -= MACRO_GATES
    if comb_macros:
        n = _expand_to_basic(node)
        if {'HA', 'FA'} & comb_macros:
            return _macroify_adders(n, comb_macros)
        return _to_mux_tree(n)
    if not allowed:
        # Only sequential macros were selected: the combinational core is
        # unrestricted (default gates); the caller adds the register stage.
        return node

    if 'NAND' in allowed and len(allowed) == 1:
        return _to_nand_only(node)
    if 'NOR' in allowed and len(allowed) == 1:
        return _to_nor_only(node)

    # Reduce things outside the allowed set to AND/OR/NOT first.
    n = _expand_to_basic(node)

    # If the allowed set lacks AND but has NAND, rewrite AND->NAND->NOT.
    # If lacks OR but has NOR, similarly.
    def rewrite(n):
        t = n[0]
        if t in ('VAR', 'CONST'):
            return n
        if t == 'NOT':
            child = rewrite(n[1])
            if 'NOT' in allowed:
                return ('NOT', child)
            if 'NAND' in allowed:
                return ('NAND', child, child)
            if 'NOR' in allowed:
                return ('NOR',  child, child)
            raise BooleanParseError("Allowed gate set cannot represent NOT")
        L, R = rewrite(n[1]), rewrite(n[2])
        if t in allowed:
            return (t, L, R)
        if t == 'AND':
            if 'NAND' in allowed:
                nand = ('NAND', L, R)
                if 'NOT' in allowed:
                    return ('NOT', nand)
                return ('NAND', nand, nand)
            if {'OR', 'NOT'} <= allowed:
                return ('NOT', ('OR', ('NOT', L), ('NOT', R)))
            raise BooleanParseError("Allowed gate set cannot represent AND")
        if t == 'OR':
            if 'NOR' in allowed:
                nor = ('NOR', L, R)
                if 'NOT' in allowed:
                    return ('NOT', nor)
                return ('NOR', nor, nor)
            if {'AND', 'NOT'} <= allowed:
                return ('NOT', ('AND', ('NOT', L), ('NOT', R)))
            raise BooleanParseError("Allowed gate set cannot represent OR")
        if t == 'XOR':
            if {'AND', 'OR', 'NOT'} <= allowed:
                # XOR = (A & ~B) | (~A & B)
                return ('OR',
                        ('AND', L, ('NOT', R)),
                        ('AND', ('NOT', L), R))
            # Else expand via basic and re-rewrite
            return rewrite(('OR',
                            ('AND', L, ('NOT', R)),
                            ('AND', ('NOT', L), R)))
        return (t, L, R)

    return rewrite(n)


# -- AST -> gate/wire JSON -----------------------------------------------------

class _Builder:
    def __init__(self):
        self.gates       = []
        self.wires       = []
        self.var_to_gate = {}   # name -> input gate id
        self.const_gate  = {}   # value -> input gate id
        self._gid        = count(1)
        self._wid        = count(1)
        self._depth      = 0
        # Structural cache: keyed by the AST tuple itself (which is hashable
        # because parse_expression returns plain tuples of str/int/tuple).
        # Using id(node) here is unsafe  -  CPython recycles ids of dead
        # tuples, so the next parse_expression call can produce a tuple
        # whose id matches a stale cache entry and the wrong gate gets
        # returned (this broke multi-output circuits like the 2-to-4
        # decoder, where outputs Y2/Y3 were silently wired to Y0/Y1's
        # AND gates).
        self._cache      = {}   # node tuple -> gate_id

    def _new_gate(self, gtype, label=None, value=None):
        gid = f"g{next(self._gid)}"
        g = {'id': gid, 'type': gtype, 'x': 0, 'y': 0, 'output': None}
        if label is not None:
            g['label'] = label
        if value is not None:
            g['value'] = int(value)
        self.gates.append(g)
        return gid

    def _wire(self, src, dst, to_pin, from_pin=0):
        wid = f"w{next(self._wid)}"
        self.wires.append({
            'id': wid,
            'from_gate': src, 'from_pin': from_pin,
            'to_gate':   dst, 'to_pin':   to_pin,
        })

    def emit(self, node):
        """Emit gates/wires for `node`. Returns (gate_id, output_pin)."""
        key = node
        if key in self._cache:
            return self._cache[key]

        t = node[0]
        if t == 'VAR':
            name = node[1]
            if name not in self.var_to_gate:
                gid = self._new_gate('INPUT', label=name, value=0)
                self.var_to_gate[name] = gid
            self._cache[key] = (self.var_to_gate[name], 0)
            return self._cache[key]
        if t == 'CONST':
            v = node[1]
            if v not in self.const_gate:
                # VCC/GND, not INPUT: constants must not show up as K-map /
                # truth-table variables or be toggleable by the user.
                gid = self._new_gate('VCC' if v else 'GND',
                                     label='1' if v else '0')
                self.const_gate[v] = gid
            self._cache[key] = (self.const_gate[v], 0)
            return self._cache[key]

        if t == 'NOT':
            src = self.emit(node[1])
            gid = self._new_gate('NOT')
            self._wire(src[0], gid, 0, src[1])
            self._cache[key] = (gid, 0)
            return self._cache[key]

        if t == 'MPIN':
            # ('MPIN', macro_type, out_pin, (children...)) — one shared
            # macro instance per (macro_type, children) so e.g. the HA Sum
            # and HA Carry of the same operands come from the same box.
            _, mtype, out_pin, children = node
            inst_key = ('MINST', mtype, children)
            if inst_key in self._cache:
                gid = self._cache[inst_key]
            else:
                srcs = [self.emit(c) for c in children]
                gid  = self._new_gate(mtype)
                for pin, src in enumerate(srcs):
                    self._wire(src[0], gid, pin, src[1])
                self._cache[inst_key] = gid
            self._cache[key] = (gid, out_pin)
            return self._cache[key]

        # binary
        a = self.emit(node[1])
        b = self.emit(node[2])
        gid = self._new_gate(t)
        self._wire(a[0], gid, 0, a[1])
        self._wire(b[0], gid, 1, b[1])
        self._cache[key] = (gid, 0)
        return self._cache[key]


def attach_seq_stage(b, src, macro, clk_gid):
    """
    Register the combinational signal `src` = (gate_id, pin) through a
    storage macro before it reaches the OUTPUT gate.
      DFF: D=f, CLK         TFF: T=f, CLK
      JKFF: J=f, K=~f, CLK  SRLATCH: S=f, R=~f
    Returns the macro's Q as (gate_id, 0).
    """
    gid = b._new_gate(macro)
    b._wire(src[0], gid, 0, src[1])
    if macro in ('JKFF', 'SRLATCH'):
        inv = b._new_gate('NOT')
        b._wire(src[0], inv, 0, src[1])
        b._wire(inv, gid, 1)
    if macro == 'JKFF':
        b._wire(clk_gid, gid, 2)
    elif macro in ('DFF', 'TFF'):
        b._wire(clk_gid, gid, 1)
    return (gid, 0)


def _layout(circuit):
    """Light layered layout: inputs left, depth columns right, outputs far right."""
    gates    = circuit['gates']
    wires    = circuit['wires']
    by_id    = {g['id']: g for g in gates}
    incoming = {g['id']: [] for g in gates}
    for w in wires:
        incoming[w['to_gate']].append(w['from_gate'])

    depth = {}
    def d(gid, stack=None):
        if gid in depth:
            return depth[gid]
        stack = stack or set()
        if gid in stack:
            return 0
        if not incoming[gid]:
            depth[gid] = 0
            return 0
        depth[gid] = 1 + max(d(p, stack | {gid}) for p in incoming[gid])
        return depth[gid]
    for g in gates:
        d(g['id'])

    by_col = {}
    for g in gates:
        by_col.setdefault(depth[g['id']], []).append(g)
    col_w, row_h, x0, y0 = 160, 90, 80, 80
    for col, items in by_col.items():
        for i, g in enumerate(items):
            g['x'] = x0 + col * col_w
            g['y'] = y0 + i  * row_h
    return circuit


# -- Public API ---------------------------------------------------------------

class BooleanSynthesizer:
    """
    Parses a boolean expression into a circuit JSON that the frontend renders.
    `target_gates` optionally restricts the gate set (e.g. ['NAND']).
    """

    DEFAULT_GATES = ['AND', 'OR', 'NOT', 'XOR', 'NAND', 'NOR', 'XNOR']

    def build(self, expression: str, target_gates=None, output_label='Y'):
        ast = parse_expression(expression)

        used_target = None
        seq = []
        if target_gates:
            used_target = [g.upper() for g in target_gates]
            comb, seq = split_target(target_gates)
            if comb:
                ast = _restrict_to(ast, comb)

        b = _Builder()
        root = b.emit(ast)

        # Sequential macro selected: register the output through it.
        if seq:
            clk = None
            if seq[0] in ('DFF', 'TFF', 'JKFF'):
                clk = b._new_gate('CLOCK', label='CLK')
            root = attach_seq_stage(b, root, seq[0], clk)

        # Ensure there's at least one OUTPUT gate driven by the root.
        out_id = b._new_gate('OUTPUT', label=output_label)
        b._wire(root[0], out_id, 0, root[1])

        circuit = {'gates': b.gates, 'wires': b.wires}
        _layout(circuit)

        info = {
            'expression':   expression,
            'gate_count':   sum(1 for g in b.gates if g['type'] not in
                                ('INPUT', 'OUTPUT', 'CLOCK', 'VCC', 'GND')),
            'wire_count':   len(b.wires),
            'input_vars':   [g['label'] for g in b.gates if g['type'] == 'INPUT'
                             and not g.get('label', '').startswith('const_')],
            'target_gates': used_target,
        }

        # Boolean-algebra simplification + truth table (best-effort; never
        # let analysis failure break the build itself).
        try:
            simplified = simplify_expression(expression)
            info['simplified'] = simplified
            info['is_simplest'] = (
                _normalize_expr_str(simplified) == _normalize_expr_str(expression))
        except Exception:
            info['simplified'] = expression
            info['is_simplest'] = True
        try:
            info['truth_table'] = truth_table(expression)
        except Exception:
            info['truth_table'] = None

        return circuit, info

    def simplify(self, expression: str):
        """Return the minimal sum-of-products form of `expression`."""
        return simplify_expression(expression)


# -- Boolean evaluation / truth table / simplification ------------------------
#
# These power the "simplify boolean algebra" feature: parse -> truth table ->
# Quine-McCluskey minimal sum-of-products. Pure Python, no dependencies.

def _eval_ast(node, env):
    """Evaluate a parsed AST node to 0/1 given env = {var_name: 0/1}."""
    t = node[0]
    if t == 'VAR':
        return 1 if env.get(node[1], 0) else 0
    if t == 'CONST':
        return 1 if node[1] else 0
    if t == 'NOT':
        return 0 if _eval_ast(node[1], env) else 1
    a = _eval_ast(node[1], env)
    b = _eval_ast(node[2], env)
    if t == 'AND':
        return a & b
    if t == 'OR':
        return a | b
    if t == 'XOR':
        return a ^ b
    if t == 'NAND':
        return 0 if (a & b) else 1
    if t == 'NOR':
        return 0 if (a | b) else 1
    if t == 'XNOR':
        return 1 if a == b else 0
    raise BooleanParseError(f"Cannot evaluate node type {t!r}")


def _ordered_vars(ast):
    vs = []
    _collect_vars(ast, vs)
    return vs


def truth_table(expression: str):
    """
    Return {'variables': [...], 'rows': [[in0, in1, ..., out], ...]}.
    Rows are in standard ascending order (000, 001, 010, ...).
    """
    ast = parse_expression(expression)
    variables = _ordered_vars(ast)
    n = len(variables)
    rows = []
    for i in range(1 << n):
        env = {}
        bits = []
        for b, name in enumerate(variables):
            val = (i >> (n - 1 - b)) & 1
            env[name] = val
            bits.append(val)
        bits.append(_eval_ast(ast, env))
        rows.append(bits)
    return {'variables': variables, 'rows': rows}


def _minterms(expression):
    """Return (variables, list_of_minterm_indices_where_output_is_1)."""
    tt = truth_table(expression)
    variables = tt['variables']
    n = len(variables)
    minterms = [i for i, row in enumerate(tt['rows']) if row[-1] == 1]
    return variables, n, minterms


def _combine(a, b):
    """Combine two QM terms differing in exactly one bit; '-' = don't-care."""
    diff = 0
    out = []
    for x, y in zip(a, b):
        if x != y:
            diff += 1
            out.append('-')
        else:
            out.append(x)
    return ''.join(out) if diff == 1 else None


def _prime_implicants(minterms, n):
    """Quine-McCluskey: reduce minterms to prime implicants (bit patterns)."""
    if not minterms:
        return []
    groups = {format(m, f'0{n}b'): {m} for m in minterms}
    primes = {}
    current = groups
    while current:
        used = set()
        nxt = {}
        items = list(current.items())
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                t1, c1 = items[i]
                t2, c2 = items[j]
                comb = _combine(t1, t2)
                if comb is not None:
                    used.add(t1)
                    used.add(t2)
                    nxt.setdefault(comb, set()).update(c1 | c2)
        for term, cover in current.items():
            if term not in used:
                primes.setdefault(term, set()).update(cover)
        current = nxt
    return primes


def _cover(primes, minterms):
    """Pick a small set of prime implicants covering all minterms (greedy +
    essential-implicant selection). Returns list of bit-pattern terms."""
    minterms = set(minterms)
    chart = {term: (cover & minterms) for term, cover in primes.items()}
    chosen = []
    remaining = set(minterms)

    # Essential prime implicants: any minterm covered by exactly one term.
    while remaining:
        # find essentials
        essential = None
        for m in remaining:
            covering = [t for t, c in chart.items() if m in c and t not in chosen]
            if len(covering) == 1:
                essential = covering[0]
                break
        if essential is not None:
            chosen.append(essential)
            remaining -= chart[essential]
            continue
        # otherwise greedily take the term covering the most remaining minterms
        best = max(chart, key=lambda t: len(chart[t] & remaining))
        if not (chart[best] & remaining):
            break
        chosen.append(best)
        remaining -= chart[best]
    return chosen


def _term_to_str(term, variables):
    """Convert a QM bit pattern to a product term like 'A & ~C'."""
    lits = []
    for bit, name in zip(term, variables):
        if bit == '1':
            lits.append(name)
        elif bit == '0':
            lits.append(f'~{name}')
    if not lits:
        return '1'
    return ' & '.join(lits)


def simplify_expression(expression: str) -> str:
    """
    Return the minimal sum-of-products form of `expression` via
    Quine-McCluskey. Returns '0' / '1' for constant functions.
    """
    variables, n, minterms = _minterms(expression)
    if n == 0:
        # constant expression
        return '1' if minterms else '0'
    if not minterms:
        return '0'
    if len(minterms) == (1 << n):
        return '1'
    primes = _prime_implicants(minterms, n)
    chosen = _cover(primes, minterms)
    # Order terms for stable, readable output.
    terms = sorted(_term_to_str(t, variables) for t in chosen)
    if len(terms) == 1:
        return terms[0]
    return ' | '.join(f'({t})' if '&' in t else t for t in terms)


def _normalize_expr_str(s: str) -> str:
    """Loose normalisation so 'A&B' and 'A & B' compare equal."""
    import re as _re
    return _re.sub(r'\s+', '', s or '').replace('(', '').replace(')', '')
