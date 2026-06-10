"""
QuestionSolver  -  ML-powered circuit question answering.

Answers questions like:
- "What is the output of this circuit when A=1, B=0?"
- "How many gates does this circuit use?"
- "What gate type is most used?"
- "Is this a valid circuit?"
- "What would happen if I change gate X to NAND?"

Uses:
- Trained ML model (same as fault_detector) for output prediction
- Pattern matching to understand question intent
- Circuit analysis for structural questions
"""

import re
import os
import numpy as np
from .data_parser import row_to_features, MAX_GATES, GATE_TYPES
from .boolean_synth import BooleanParseError


# All gate-name tokens the restriction parser will recognise. Mapped to the
# canonical type name the synth uses. Note OR/AND/XOR alone are NOT universal
#  -  _restrict_to will raise BooleanParseError, which we catch and surface
# as a "this set can't represent that function" answer.
_GATE_TOKEN_MAP = {
    'and':  'AND',
    'or':   'OR',
    'not':  'NOT',
    'inv':  'NOT', 'inverter': 'NOT',
    'xor':  'XOR',
    'nand': 'NAND',
    'nor':  'NOR',
    'xnor': 'XNOR',
}
_GATE_TOKEN_RE = (
    # Optional trailing " gate" / " gates" so "AND gate", "NOT gates" are
    # parsed as the gate token itself (not "AND" + filler word "gate"). Lets
    # phrases like "using not gate and gate" extract both NOT and AND.
    r'(?:nand|nor|xnor|xor|inverter|inv|and|or|not)(?:\s+gates?)?'
)
# A gate-list is one or more gate tokens joined by separators (and / , / / / +).
_GATE_LIST_RE = (
    rf'(?P<glist>{_GATE_TOKEN_RE}'
    rf'(?:\s*(?:and|,|/|\+|or)\s*{_GATE_TOKEN_RE})*)'
)

# "using only NAND", "with NAND and NOT", "from OR / NOT", "by NOR".
_RESTRICTION_PREFIX_RE = re.compile(
    rf'\b(?:using|with|in|via|from|by)'
    rf'(?:\s+(?:only|just|the|help|of))*'
    rf'\s+(?:aoi|and-or-not|{_GATE_LIST_RE})\b',
    re.IGNORECASE,
)
# "NAND only", "NAND-only"  -  only when the bare token is at the END
# AND there's nothing (or just punctuation/EOL) after "only". This avoids
# "and only if X" being mis-parsed as "AND only" gate restriction.
_RESTRICTION_SUFFIX_RE = re.compile(
    rf'\b(?:aoi|and-or-not|{_GATE_TOKEN_RE})[\s-]?only\b(?!\s+(?:if|when|the|a|an|that))',
    re.IGNORECASE,
)


def _parse_target(text: str):
    """
    Pull out a gate-set restriction phrase from `text`. Returns
    (target_list_or_None, text_with_phrase_stripped).
    """
    # First: collect *explicit* "X gate(s)" mentions anywhere in the text.
    # "build flipflop using not gate and gate both" → finds NOT + AND.
    # This is unambiguous because " gate" forces the gate-name reading
    # (vs "and" being a list separator).
    seen, explicit = set(), []
    for m_exp in re.finditer(
            r'\b(nand|nor|xnor|xor|inverter|inv|and|or|not)\s+gates?\b',
            text, re.IGNORECASE):
        g = _GATE_TOKEN_MAP.get(m_exp.group(1).lower())
        if g and g not in seen:
            seen.add(g)
            explicit.append(g)

    m = _RESTRICTION_PREFIX_RE.search(text)
    if not m:
        m = _RESTRICTION_SUFFIX_RE.search(text)

    if m:
        phrase_orig = m.group(0)            # original case for heuristics
        phrase = phrase_orig.lower()
        if 'aoi' in phrase or 'and-or-not' in phrase:
            for g in ('AND', 'OR', 'NOT'):
                if g not in seen:
                    seen.add(g)
                    explicit.append(g)
        else:
            tokens = re.findall(_GATE_TOKEN_RE, phrase_orig, flags=re.IGNORECASE)
            # "and" / "or" can be either a gate name OR a list separator.
            # Heuristic: if written in UPPERCASE the user means the gate;
            # lowercase between two gates is a separator. Edge: if dropping
            # middle "and"/"or" would shrink the target list to nothing,
            # keep it.
            filtered = []
            for i, tok in enumerate(tokens):
                low = tok.lower().strip()
                # Strip trailing " gate(s)" before classifying.
                bare = re.sub(r'\s+gates?$', '', low).strip()
                if (bare in ('and', 'or')
                        and 0 < i < len(tokens) - 1
                        and not tok.isupper()
                        and ' gate' not in low):
                    continue   # separator
                filtered.append(tok)
            for tok in filtered:
                key = re.sub(r'\s+gates?$', '', tok.lower()).strip()
                g = _GATE_TOKEN_MAP.get(key)
                if g and g not in seen:
                    seen.add(g)
                    explicit.append(g)
        stripped = text[:m.start()] + text[m.end():]
        return (explicit or None), stripped.strip()

    # No explicit prefix/suffix. If the text mentions gates as "X gate" AND
    # a using/with-style introducer exists, treat it as a restriction.
    if explicit and re.search(r'\b(?:using|with|via|from|by)\b', text, re.I):
        return explicit, text
    return None, text

KNOWN_CIRCUITS = {
    # canonical_name -> boolean expression (one output)
    'half adder sum':   'A ^ B',
    'half adder carry': 'A & B',
    'and gate':         'A & B',
    'or gate':          'A | B',
    'not gate':         '~A',
    'xor gate':         'A ^ B',
    'nand gate':        '~(A & B)',
    'nor gate':         '~(A | B)',
    'xnor gate':        '~(A ^ B)',
    'inverter':         '~A',
    'buffer':           'A',
    'majority':         '(A & B) | (B & C) | (A & C)',
    'parity':           'A ^ B ^ C',
    '2-to-1 mux':       '(SEL & D1) | (~SEL & D0)',
    '2 to 1 mux':       '(SEL & D1) | (~SEL & D0)',
    'multiplexer':      '(SEL & D1) | (~SEL & D0)',
    'mux':              '(SEL & D1) | (~SEL & D0)',
    'full adder sum':   'A ^ B ^ Cin',
    'full adder carry': '(A & B) | (Cin & (A ^ B))',
}

# Maps a bare gate-name token to its canonical two-/one-input expression.
# Used when the user types just "XOR" / "XOR using NAND" / "build NAND".
BARE_GATE_EXPR = {
    'AND':  ('A & B',     'AND'),
    'OR':   ('A | B',     'OR'),
    'NOT':  ('~A',        'NOT'),
    'XOR':  ('A ^ B',     'XOR'),
    'NAND': ('~(A & B)',  'NAND'),
    'NOR':  ('~(A | B)',  'NOR'),
    'XNOR': ('~(A ^ B)',  'XNOR'),
    'INV':       ('~A', 'NOT'),
    'INVERTER':  ('~A', 'NOT'),
    'BUFFER':    ('A',  'BUF'),
    'BUF':       ('A',  'BUF'),
}

# Circuits whose result is naturally multiple outputs in one design.
# Each value is a list of (label, expression) pairs that share inputs.
MULTI_OUTPUT_CIRCUITS = {
    'half adder': [('Sum',   'A ^ B'),
                   ('Carry', 'A & B')],
    'half-adder': [('Sum',   'A ^ B'),
                   ('Carry', 'A & B')],
    'full adder': [('Sum',   'A ^ B ^ Cin'),
                   ('Cout',  '(A & B) | (Cin & (A ^ B))')],
    'full-adder': [('Sum',   'A ^ B ^ Cin'),
                   ('Cout',  '(A & B) | (Cin & (A ^ B))')],
    # 1-bit magnitude comparator
    'comparator': [('A_lt_B', '~A & B'),
                   ('A_eq_B', '~(A ^ B)'),
                   ('A_gt_B', 'A & ~B')],
    '1 bit comparator': [('A_lt_B', '~A & B'),
                         ('A_eq_B', '~(A ^ B)'),
                         ('A_gt_B', 'A & ~B')],
    # 2-to-4 line decoder, inputs A (MSB) and B (LSB)
    '2 to 4 decoder': [('Y0', '~A & ~B'),
                       ('Y1', '~A &  B'),
                       ('Y2', ' A & ~B'),
                       ('Y3', ' A &  B')],
    '2-to-4 decoder': [('Y0', '~A & ~B'),
                       ('Y1', '~A &  B'),
                       ('Y2', ' A & ~B'),
                       ('Y3', ' A &  B')],
    'decoder':        [('Y0', '~A & ~B'),
                       ('Y1', '~A &  B'),
                       ('Y2', ' A & ~B'),
                       ('Y3', ' A &  B')],
    # 4-to-2 priority encoder (inputs I0..I3, I3 highest priority)
    '4 to 2 encoder': [('Y1', 'I2 | I3'),
                       ('Y0', 'I1 | I3')],
    '4-to-2 encoder': [('Y1', 'I2 | I3'),
                       ('Y0', 'I1 | I3')],
    'encoder':        [('Y1', 'I2 | I3'),
                       ('Y0', 'I1 | I3')],
    # 4-to-1 multiplexer (S1 MSB, S0 LSB; inputs D0..D3)
    '4 to 1 mux': [('Y', '(~S1 & ~S0 & D0) | (~S1 & S0 & D1) | '
                          '( S1 & ~S0 & D2) | ( S1 & S0 & D3)')],
    '4-to-1 mux': [('Y', '(~S1 & ~S0 & D0) | (~S1 & S0 & D1) | '
                          '( S1 & ~S0 & D2) | ( S1 & S0 & D3)')],
    # 1-bit full subtractor: D = A^B^Bin,  Bout = (~A & B) | (~(A^B) & Bin)
    'full subtractor': [('D',    'A ^ B ^ Bin'),
                        ('Bout', '(~A & B) | (~(A ^ B) & Bin)')],
    'half subtractor': [('D',    'A ^ B'),
                        ('Bout', '~A & B')],
    # 8-to-1 multiplexer (3 select bits S2 S1 S0, 8 data D0..D7)
    '8 to 1 mux': [('Y',
        '(~S2 & ~S1 & ~S0 & D0) | (~S2 & ~S1 & S0 & D1) | '
        '(~S2 &  S1 & ~S0 & D2) | (~S2 &  S1 & S0 & D3) | '
        '( S2 & ~S1 & ~S0 & D4) | ( S2 & ~S1 & S0 & D5) | '
        '( S2 &  S1 & ~S0 & D6) | ( S2 &  S1 & S0 & D7)')],
    '8-to-1 mux': [('Y',
        '(~S2 & ~S1 & ~S0 & D0) | (~S2 & ~S1 & S0 & D1) | '
        '(~S2 &  S1 & ~S0 & D2) | (~S2 &  S1 & S0 & D3) | '
        '( S2 & ~S1 & ~S0 & D4) | ( S2 & ~S1 & S0 & D5) | '
        '( S2 &  S1 & ~S0 & D6) | ( S2 &  S1 & S0 & D7)')],
    # 3-to-8 line decoder (inputs A=MSB, B, C=LSB, outputs Y0..Y7)
    '3 to 8 decoder': [('Y0', '~A & ~B & ~C'), ('Y1', '~A & ~B &  C'),
                       ('Y2', '~A &  B & ~C'), ('Y3', '~A &  B &  C'),
                       ('Y4', ' A & ~B & ~C'), ('Y5', ' A & ~B &  C'),
                       ('Y6', ' A &  B & ~C'), ('Y7', ' A &  B &  C')],
    '3-to-8 decoder': [('Y0', '~A & ~B & ~C'), ('Y1', '~A & ~B &  C'),
                       ('Y2', '~A &  B & ~C'), ('Y3', '~A &  B &  C'),
                       ('Y4', ' A & ~B & ~C'), ('Y5', ' A & ~B &  C'),
                       ('Y6', ' A &  B & ~C'), ('Y7', ' A &  B &  C')],
    # 1-to-4 demultiplexer (data D, select S1 S0)
    '1 to 4 demux': [('Y0', 'D & ~S1 & ~S0'), ('Y1', 'D & ~S1 &  S0'),
                     ('Y2', 'D &  S1 & ~S0'), ('Y3', 'D &  S1 &  S0')],
    '1-to-4 demux': [('Y0', 'D & ~S1 & ~S0'), ('Y1', 'D & ~S1 &  S0'),
                     ('Y2', 'D &  S1 & ~S0'), ('Y3', 'D &  S1 &  S0')],
    'demultiplexer': [('Y0', 'D & ~S1 & ~S0'), ('Y1', 'D & ~S1 &  S0'),
                     ('Y2', 'D &  S1 & ~S0'), ('Y3', 'D &  S1 &  S0')],
    'demux':        [('Y0', 'D & ~S1 & ~S0'), ('Y1', 'D & ~S1 &  S0'),
                     ('Y2', 'D &  S1 & ~S0'), ('Y3', 'D &  S1 &  S0')],
    # 8-to-3 priority encoder (I7 highest); standard reduced equations
    '8 to 3 encoder': [('Y2', 'I4 | I5 | I6 | I7'),
                       ('Y1', 'I2 | I3 | I6 | I7'),
                       ('Y0', 'I1 | I3 | I5 | I7')],
    '8-to-3 encoder': [('Y2', 'I4 | I5 | I6 | I7'),
                       ('Y1', 'I2 | I3 | I6 | I7'),
                       ('Y0', 'I1 | I3 | I5 | I7')],
    # BCD-to-7-segment decoder (digits 0-9, common-cathode); inputs A=MSB..D=LSB
    'bcd to 7 segment': [
        ('a', 'A | C | (B & D) | (~B & ~D)'),
        ('b', '~B | (~C & ~D) | (C & D)'),
        ('c', 'B | ~C | D'),
        ('d', '(~B & ~D) | (C & ~D) | (~B & C) | (B & ~C & D) | A'),
        ('e', '(~B & ~D) | (C & ~D)'),
        ('f', 'A | (B & ~C) | (B & ~D) | (~C & ~D)'),
        ('g', 'A | (B & ~C) | (~B & C) | (C & ~D)'),
    ],
    'bcd-to-7-segment': [
        ('a', 'A | C | (B & D) | (~B & ~D)'),
        ('b', '~B | (~C & ~D) | (C & D)'),
        ('c', 'B | ~C | D'),
        ('d', '(~B & ~D) | (C & ~D) | (~B & C) | (B & ~C & D) | A'),
        ('e', '(~B & ~D) | (C & ~D)'),
        ('f', 'A | (B & ~C) | (B & ~D) | (~C & ~D)'),
        ('g', 'A | (B & ~C) | (~B & C) | (C & ~D)'),
    ],
    'seven segment': [
        ('a', 'A | C | (B & D) | (~B & ~D)'),
        ('b', '~B | (~C & ~D) | (C & D)'),
        ('c', 'B | ~C | D'),
        ('d', '(~B & ~D) | (C & ~D) | (~B & C) | (B & ~C & D) | A'),
        ('e', '(~B & ~D) | (C & ~D)'),
        ('f', 'A | (B & ~C) | (B & ~D) | (~C & ~D)'),
        ('g', 'A | (B & ~C) | (~B & C) | (C & ~D)'),
    ],
    # === Code converters ============================================
    # 4-bit Binary -> Gray:  G3=B3, G2=B3⊕B2, G1=B2⊕B1, G0=B1⊕B0
    'binary to gray': [('G3', 'B3'), ('G2', 'B3 ^ B2'),
                       ('G1', 'B2 ^ B1'), ('G0', 'B1 ^ B0')],
    'bin to gray':    [('G3', 'B3'), ('G2', 'B3 ^ B2'),
                       ('G1', 'B2 ^ B1'), ('G0', 'B1 ^ B0')],
    # 4-bit Gray -> Binary: B3=G3, B2=B3⊕G2, B1=B2⊕G1, B0=B1⊕G0
    'gray to binary': [('B3', 'G3'), ('B2', 'G3 ^ G2'),
                       ('B1', 'G3 ^ G2 ^ G1'),
                       ('B0', 'G3 ^ G2 ^ G1 ^ G0')],
    'gray to bin':    [('B3', 'G3'), ('B2', 'G3 ^ G2'),
                       ('B1', 'G3 ^ G2 ^ G1'),
                       ('B0', 'G3 ^ G2 ^ G1 ^ G0')],
    # 2-bit magnitude comparator (inputs A1 A0 vs B1 B0)
    '2 bit comparator': [
        ('A_gt_B', '(A1 & ~B1) | ((~(A1 ^ B1)) & (A0 & ~B0))'),
        ('A_eq_B', '(~(A1 ^ B1)) & (~(A0 ^ B0))'),
        ('A_lt_B', '(~A1 & B1) | ((~(A1 ^ B1)) & (~A0 & B0))'),
    ],
    '2-bit comparator': [
        ('A_gt_B', '(A1 & ~B1) | ((~(A1 ^ B1)) & (A0 & ~B0))'),
        ('A_eq_B', '(~(A1 ^ B1)) & (~(A0 ^ B0))'),
        ('A_lt_B', '(~A1 & B1) | ((~(A1 ^ B1)) & (~A0 & B0))'),
    ],
    'magnitude comparator': [
        ('A_gt_B', '(A1 & ~B1) | ((~(A1 ^ B1)) & (A0 & ~B0))'),
        ('A_eq_B', '(~(A1 ^ B1)) & (~(A0 ^ B0))'),
        ('A_lt_B', '(~A1 & B1) | ((~(A1 ^ B1)) & (~A0 & B0))'),
    ],
    # === Parity ======================================================
    # 4-bit even parity generator (output 1 when count of 1s is even)
    'even parity generator': [('P', '~(A ^ B ^ C ^ D)')],
    'even parity':           [('P', '~(A ^ B ^ C ^ D)')],
    # 4-bit odd parity generator
    'odd parity generator':  [('P', 'A ^ B ^ C ^ D')],
    'odd parity':            [('P', 'A ^ B ^ C ^ D')],
    # 5-input parity checker (4 data + parity bit; output 1 = error)
    'parity checker':        [('Err', 'A ^ B ^ C ^ D ^ P')],
    # === BCD code conversions ========================================
    # BCD (A B C D, A=MSB) -> Excess-3:  E = BCD + 3
    'bcd to excess-3': [
        ('E3', 'A | (B & (C | D))'),
        ('E2', '(~B & (C | D)) | (B & ~C & ~D)'),
        ('E1', '(~C & ~D) | (C & D)'),
        ('E0', '~D'),
    ],
    'bcd to excess 3': [
        ('E3', 'A | (B & (C | D))'),
        ('E2', '(~B & (C | D)) | (B & ~C & ~D)'),
        ('E1', '(~C & ~D) | (C & D)'),
        ('E0', '~D'),
    ],
    'excess-3 to bcd': [
        ('B3', '(A & B) | (A & C & D)'),
        ('B2', '(B & ~C & ~D) | (~B & (C | D))'),
        ('B1', '(~C & ~D) | (C & D)'),
        ('B0', '~D'),
    ],
    # === Half-bit / 2's complement ===================================
    # 4-bit 1's complement (bitwise NOT)
    "1's complement": [('Y3', '~A'), ('Y2', '~B'),
                       ('Y1', '~C'), ('Y0', '~D')],
    'ones complement': [('Y3', '~A'), ('Y2', '~B'),
                        ('Y1', '~C'), ('Y0', '~D')],
    # === Priority encoder (4-input, with valid bit) ===================
    'priority encoder valid': [
        ('V', 'I0 | I1 | I2 | I3'),
        ('Y1', 'I2 | I3'),
        ('Y0', 'I1 | I3'),
    ],
    # 1-bit ALU: S1 S0 select among AND, OR, ADD, XOR (Cin used for ADD)
    '1 bit alu': [
        ('Result',
         '(~S1 & ~S0 & (A & B)) | (~S1 & S0 & (A | B)) | '
         '( S1 & ~S0 & (A ^ B ^ Cin)) | ( S1 & S0 & (A ^ B))'),
        ('Cout',
         'S1 & ~S0 & ((A & B) | (Cin & (A ^ B)))'),
    ],
    'alu': [
        ('Result',
         '(~S1 & ~S0 & (A & B)) | (~S1 & S0 & (A | B)) | '
         '( S1 & ~S0 & (A ^ B ^ Cin)) | ( S1 & S0 & (A ^ B))'),
        ('Cout',
         'S1 & ~S0 & ((A & B) | (Cin & (A ^ B)))'),
    ],

    # === 2's complement (4-bit) ==========================================
    # 2's complement = 1's complement + 1  (carry-chain adder)
    # Bit-level: Y0=~D, Y1=~C^~D, Y2=~B^~(C|D), Y3=~A^~(B|C|D)
    "2's complement": [
        ('Y0', '~D'),
        ('Y1', '~C ^ ~D'),
        ('Y2', '~B ^ (~C & ~D)'),
        ('Y3', '~A ^ (~B & ~C & ~D)'),
    ],
    'twos complement': [
        ('Y0', '~D'),
        ('Y1', '~C ^ ~D'),
        ('Y2', '~B ^ (~C & ~D)'),
        ('Y3', '~A ^ (~B & ~C & ~D)'),
    ],

    # === 4-bit equality comparator =======================================
    '4 bit equality comparator': [
        ('Equal',
         '(~(A3 ^ B3)) & (~(A2 ^ B2)) & (~(A1 ^ B1)) & (~(A0 ^ B0))')
    ],
    'equality comparator': [
        ('Equal',
         '(~(A3 ^ B3)) & (~(A2 ^ B2)) & (~(A1 ^ B1)) & (~(A0 ^ B0))')
    ],

    # === Booth recoder (1-bit: P = X & ~Y, M = ~X & Y) ==================
    'sign detector': [
        ('Positive', '~S'),
        ('Negative', 'S'),
    ],

    # === 2-to-1 multiplexer (explicit naming) ============================
    '2 to 1 multiplexer': [('Y', '(SEL & D1) | (~SEL & D0)')],

    # === Carry lookahead (1-bit) ==========================================
    # Generate G=A&B, Propagate P=A^B, Carry-out Cout = G | (P & Cin)
    'carry lookahead': [
        ('G',    'A & B'),
        ('P',    'A ^ B'),
        ('Cout', '(A & B) | ((A ^ B) & Cin)'),
        ('Sum',  'A ^ B ^ Cin'),
    ],
    'carry lookahead adder': [
        ('G',    'A & B'),
        ('P',    'A ^ B'),
        ('Cout', '(A & B) | ((A ^ B) & Cin)'),
        ('Sum',  'A ^ B ^ Cin'),
    ],

    # === Tri-state buffer (active-high enable) ============================
    'tri state buffer': [('Y', 'EN & A')],
    'tristate buffer':  [('Y', 'EN & A')],

    # === 4-bit shift register (parallel-in serial-out combinational) =====
    # This is the combinational output for each bit after one shift
    '4 bit shift register': [
        ('Q0', 'D3'),
        ('Q1', 'D0'),
        ('Q2', 'D1'),
        ('Q3', 'D2'),
    ],

    # === Barrel shifter (2-bit data, 1-bit shift control) ================
    'barrel shifter': [
        ('Y0', '(~S & D0) | (S & D1)'),
        ('Y1', '(~S & D1) | (S & D0)'),
    ],

    # === Wallace tree multiplier (2x2 bit) ================================
    '2 bit multiplier': [
        ('P0', 'A0 & B0'),
        ('P1', '(A1 & B0) ^ (A0 & B1)'),
        ('P2', '(A1 & B1) ^ ((A1 & B0) & (A0 & B1))'),
        ('P3', '(A1 & B1) & ((A1 & B0) | (A0 & B1))'),
    ],

    # === Schmitt trigger (hysteresis model — digital approximation) =======
    # Cannot be accurately represented in static boolean; emit OR approximation
    'schmitt trigger': [('Y', 'A | B')],

    # === Common SR latch aliases ==========================================
    'sr latch using nor':  [('Q',     '~(R | Q_bar)'), ('Q_bar', '~(S | Q)')],

    # === Clocked D latch (combinational equations for output) =============
    'clocked d latch': [
        ('Q',     'E & D | ~E & Q'),
        ('Q_bar', '~(E & D | ~E & Q)'),
    ],

    # === 4-bit ripple counter (mod-16) — combinational transition ==========
    # Each bit toggles when all lower bits are 1
    '4 bit counter': [
        ('Q0', '~Q0'),
        ('Q1', 'Q0 ^ Q1'),
        ('Q2', '(Q0 & Q1) ^ Q2'),
        ('Q3', '(Q0 & Q1 & Q2) ^ Q3'),
    ],

    # === Multiplexer-based function generator =============================
    '2 to 1 mux function': [('Y', '(S & F1) | (~S & F0)')],
}


# --- Synonyms / aliases / typo fixes ----------------------------------------
#
# These run BEFORE pattern matching so the user can type natural-sounding
# variations and still hit a known circuit. The mapping is a regex ->
# replacement applied case-insensitively as a substring (not whole-word).
#
# Order matters: longer/more-specific phrases come first so they don't get
# eaten by shorter ones.

_ALIAS_RULES = [
    # Typo fixes  -  apply first.
    (r'\bgatye\b',            'gate'),
    (r'\bgte\b',              'gate'),
    (r'\bgaet\b',             'gate'),
    (r'\baddder\b',           'adder'),
    (r'\baddr\b',             'adder'),
    (r'\baddee?r\b',          'adder'),
    (r'\badwer\b',            'adder'),
    (r'\badedr\b',            'adder'),
    (r'\baddar\b',             'adder'),
    (r'\bfll\b',              'full'),
    (r'\bfulll\b',            'full'),
    (r'\bfullll\b',           'full'),
    (r'\bful\b',              'full'),
    (r'\bbiuld\b',            'build'),
    (r'\bbuld\b',             'build'),
    (r'\bbiuid\b',            'build'),
    (r'\bbuiild\b',           'build'),
    (r'\bbbuild\b',           'build'),
    (r'\bbuilld\b',           'build'),
    (r'\bbuilt\b',            'build'),
    (r'\bmaek\b',             'make'),
    (r'\bcrete\b',            'create'),
    (r'\bdsign\b',            'design'),
    (r'\bflp\s*flop\b',       'flip flop'),
    (r'\bflipflop\b',         'flip flop'),
    (r'\bflip\s*-\s*flop\b',  'flip flop'),
    (r'\bff\b',               'flip flop'),
    (r'\bd\s*ff\b',           'd flip flop'),
    (r'\bsr\s*ff\b',          'sr flip flop'),
    (r'\bjk\s*ff\b',          'jk flip flop'),
    (r'\bt\s*ff\b',           't flip flop'),
    # Conversational gate-set phrasings that the restriction regex misses.
    (r'\busing\s+both\b',                            'using'),
    (r'\busing\s+(\w+)\s+and\s+(\w+)\s+both\b',      r'using \1 and \2'),
    (r'\bwith\s+both\s+(\w+)\s+and\s+(\w+)\b',       r'using \1 and \2'),
    (r'\bmultipxer\b',        'multiplexer'),
    (r'\bmultipler\b',        'multiplexer'),
    (r'\bmlutiplexer\b',      'multiplexer'),
    (r'\bdecodr\b',           'decoder'),
    (r'\bencodr\b',           'encoder'),
    (r'\bwithh\b',            'with'),
    (r'\busng\b',             'using'),
    (r'\bonly\s+nadn\b',      'only nand'),
    (r'\bnadn\b',             'nand'),
    (r'\bnro\b',              'nor'),
    (r'\bxnro\b',             'xnor'),
    (r'\bhalfadder\b',        'half adder'),
    (r'\bfulladder\b',        'full adder'),
    (r'\bhalfsubtractor\b',   'half subtractor'),
    (r'\bfullsubtractor\b',   'full subtractor'),
    (r'\bsubtracter\b',       'subtractor'),
    (r'\bsubstractor\b',      'subtractor'),
    (r'\bsubstracter\b',      'subtractor'),
    # Mux synonyms: "1-of-N selector" / "N-input selector" / "N:1 selector" → "N to 1 mux"
    (r'\b1[-\s]?of[-\s]?(\d+)\s+selector\b',  r'\1 to 1 mux'),
    (r'\b(\d+)[-:\s]?(?:input|to)?[-:\s]?1\s+selector\b', r'\1 to 1 mux'),
    (r'\bdata\s+selector\b',              'multiplexer'),
    # Threshold patterns: "K of N inputs are 1" → "at least K of N inputs are 1"
    # (bare "K of N" is ambiguous; default to "at least" for usability)
    (r'\b(\d+)\s+of\s+(\d+)\s+inputs?\s+(?:are|is)\s+(?:1|high|on)\b',
     r'at least \1 of \2 inputs are 1'),
    # "outputs 1 when N of M ..." normalizer
    (r'\boutputs?\s+1\s+when\s+(\d+)\s+of\s+(\d+)\b',
     r'output is 1 when at least \1 of \2'),
    # Bare "subtractor" / "adder"  -  assume the full (3-input) variant.
    (r'^(?:please\s+)?(?:build|make|design|create|generate|give\s+me|i\s+(?:want|need))?\s*(?:a|an|the)?\s*subtractor\b',
     'full subtractor'),
    (r'^(?:please\s+)?(?:build|make|design|create|generate|give\s+me|i\s+(?:want|need))?\s*(?:a|an|the)?\s*adder\b',
     'full adder'),
    (r'\bmultplxer\b',        'multiplexer'),
    (r'\bmultiplxer\b',       'multiplexer'),
    (r'\bcompare?ator\b',     'comparator'),
    (r'\bcomperator\b',       'comparator'),
    (r'\bdecoda?er\b',        'decoder'),
    (r'\bencoda?er\b',        'encoder'),
    (r'\bflipflop\b',         'flip flop'),
    (r'\bflip-flop\b',        'flip flop'),
    (r'\blatche?s?\b',        'latch'),
    # British/American
    (r'\borganise\b',         'organize'),
    (r'\bminimise\b',         'minimize'),
    # Synonyms collapsed to canonical names
    (r'\b1\s*bit\s+adder\b',       'full adder'),
    (r'\b1\s*bit\s+subtractor\b',  'full subtractor'),
    (r'\b1\s*bit\s+comparator\b',  '1 bit comparator'),
    (r'\badder\s+circuit\b',       'full adder'),
    (r'\bsubtractor\s+circuit\b',  'full subtractor'),
    (r'\bm[au]ltiplexor\b',        'multiplexer'),
    (r'\bm[au]ltiplexer\b',        'multiplexer'),
    (r'\b2\s*to\s*1\s+mu[xX]\b',   '2 to 1 mux'),
    (r'\b4\s*to\s*1\s+mu[xX]\b',   '4 to 1 mux'),
    (r'\b8\s*to\s*1\s+mu[xX]\b',   '8 to 1 mux'),
    (r'\b2\s*to\s*4\s+decoder\b',  '2 to 4 decoder'),
    (r'\b3\s*to\s*8\s+decoder\b',  '3 to 8 decoder'),
    (r'\b1\s*to\s*4\s+demux\b',    '1 to 4 demux'),
    (r'\b1\s*to\s*8\s+demux\b',    '1 to 8 demux'),
    (r'\b4\s*to\s*2\s+(?:priority\s+)?encoder\b', '4 to 2 encoder'),
    (r'\b8\s*to\s*3\s+(?:priority\s+)?encoder\b', '8 to 3 encoder'),
    (r'\b(?:seg(?:ment)?\s*display|7\s*seg(?:ment)?|seven\s*segment)\b',
     'bcd to 7 segment'),
    (r'\bsr\s+ff\b',                'sr flip flop'),
    (r'\bd\s+ff\b',                 'd flip flop'),
    (r'\bjk\s+ff\b',                'jk flip flop'),
    (r'\bt\s+ff\b',                 't flip flop'),
    (r'\barithmetic\s+logic\s+unit\b', '1 bit alu'),
    # New: code converters
    (r'\bbinary[-\s]+to[-\s]+gray\s*(?:code)?\s*converter\b', 'binary to gray'),
    (r'\bgray[-\s]+to[-\s]+binary\s*(?:code)?\s*converter\b', 'gray to binary'),
    (r'\bbcd[-\s]+to[-\s]+excess[-\s]*3\b', 'bcd to excess-3'),
    (r'\bexcess[-\s]*3[-\s]+to[-\s]+bcd\b', 'excess-3 to bcd'),
    (r'\bgray\s+code\s+generator\b', 'binary to gray'),
    # Parity
    (r'\beven[-\s]+parity\s+(?:generator|circuit)\b', 'even parity generator'),
    (r'\bodd[-\s]+parity\s+(?:generator|circuit)\b', 'odd parity generator'),
    (r'\bparity\s+(?:checker|detector|error\s+detector)\b', 'parity checker'),
    # Comparator alias  -  keep "magnitude" so parametric n-bit doesn't grab it
    (r'\b2[-\s]+bit\s+magnitude\s+comparator\b', 'magnitude comparator'),
    (r'\b4[-\s]+bit\s+magnitude\s+comparator\b', 'magnitude comparator'),
    # Complement
    (r"\b(?:ones?|1's)\s+complement\b", "1's complement"),
    (r"\bbitwise\s+(?:not|inverter|invert)\b", "1's complement"),
    # Priority encoder with valid
    (r'\bpriority\s+encoder\s+with\s+valid\b', 'priority encoder valid'),
    # 2's complement
    (r"\b(?:two'?s?|2'?s?)\s+complement\b", "2's complement"),
    (r"\b2's\s+comp\b",                     "2's complement"),
    # Carry lookahead
    (r'\bcarry[-\s]+lookahead\b',           'carry lookahead'),
    (r'\bcla\s+adder\b',                    'carry lookahead adder'),
    (r'\bcla\b',                            'carry lookahead'),
    # Barrel shifter
    (r'\bbarrel[-\s]+shift(?:er)?\b',       'barrel shifter'),
    # Tri-state
    (r'\btri[-\s]+state\b',                 'tri state buffer'),
    (r'\b3[-\s]+state\b',                   'tri state buffer'),
    # Counter
    (r'\b4[-\s]+bit\s+(?:ripple\s+)?counter\b', '4 bit counter'),
    (r'\bmod[-\s]*16\s+counter\b',          '4 bit counter'),
    # 2-bit multiplier
    (r'\b2[-\s]+bit\s+multiplier\b',        '2 bit multiplier'),
    (r'\b2x2\s+multiplier\b',               '2 bit multiplier'),
    # Equality
    (r'\b(?:equality|equal)\s+comparator\b', 'equality comparator'),
    (r'\b4[-\s]+bit\s+equality\b',           '4 bit equality comparator'),
    # Mux aliases
    (r'\b2\s*to\s*1\s+multiplexer\b',       '2 to 1 multiplexer'),
    (r'\b2x1\s+mux\b',                      '2 to 1 mux'),
    (r'\b4x1\s+mux\b',                      '4 to 1 mux'),
    (r'\b8x1\s+mux\b',                      '8 to 1 mux'),
]


def _normalize_request_text(text: str) -> str:
    """
    Apply alias / typo rules to the user's request so subsequent matchers
    see a canonical phrasing. Case-insensitive replacement that preserves
    the surrounding text.
    """
    out = text

    # Strip pure-conversational openers that defeat the matchers.
    # "can't this be done with NOR only" -> "full adder with NOR only" if a
    # circuit name follows; otherwise drop the whole rhetorical opener so the
    # restriction phrase ("with NOR only") still parses cleanly.
    out = re.sub(
        r"^\s*(can(?:'?t|not)|won'?t|don'?t|cannot|will\s+not|"
        r"is\s+it|isn'?t\s+it)\s+"
        r"(?:you|u|this|that|we|i|it)?\s*"
        r"(?:please\s+)?"
        # Verb chain: handles both single verbs ("build") and passive
        # constructions ("be done", "be built"). Consumes up to two verbs.
        r"(?:be\s+)?"
        r"(?:made|make|done|do|built|build|created|create|"
        r"designed|design|get|gotten)?\s*",
        '',
        out, flags=re.IGNORECASE,
    )
    # Re-insert "with" if we just stripped it but a gate-set restriction
    # token follows (so "this be done with NOR only" -> "NOR only" still
    # gets picked up by the suffix-only restriction matcher).
    # Generic polite/question openers that add no semantic content.
    out = re.sub(
        r"^\s*(?:please|pls|plz|kindly|hey|hi|hello|"
        r"can\s+(?:you|u)|could\s+(?:you|u)|would\s+(?:you|u)|"
        r"will\s+(?:you|u)|how\s+(?:do|to)\s+i|how\s+can\s+i|"
        r"what\s+is|what\'s|i\s+want\s+(?:to\s+)?(?:see\s+)?|"
        r"i\s+(?:would\s+like|need|wanna|wish)|i'd\s+like|"
        r"gimme|give\s+me|show\s+me|tell\s+me|teach\s+me|"
        r"help\s+me)\s+",
        '',
        out, flags=re.IGNORECASE,
    )

    # Build verbs that ALSO need to be stripped so the boolean parser sees
    # the bare expression: "make A AND NOT B" → "A AND NOT B".
    # Step 1 (case-insensitive): strip the leading verb itself.
    for _ in range(3):
        new = re.sub(
            r"^\s*(?:build|make|design|create|construct|generate|draw|"
            r"wire\s+up|synthesize|synthesise|implement|assemble|sketch|"
            r"put\s+together|render|produce|set\s+up|"
            r"i\s+(?:want|need|wanna|wish)|let\'?s)\s+"
            r"(?:to\s+(?:build|make|design|create|construct|"
            r"generate|draw|implement|do|get)\s+)?",
            '',
            out, flags=re.IGNORECASE,
        )
        if new == out: break
        out = new

    # Step 2 (case-SENSITIVE): strip lowercase articles/fillers ONLY. This
    # protects single-letter variables like "A" / "B" that share spelling
    # with the article "a". A user typing "design A xor B" keeps A intact.
    out = re.sub(
        r"^\s*(?:me|us|a|an|the|some|this|that)\s+",
        '', out)
    # Repeat once for "build me a circuit" → "circuit"
    out = re.sub(
        r"^\s*(?:me|us|a|an|the|some|this|that)\s+",
        '', out)

    # Strip a leading "Y = " / "Z = " / "output = " preamble that some users
    # type before the actual expression — keeps the boolean parser happy.
    out = re.sub(r"^\s*(?:[yYzZ]\s*=\s*|output\s*=\s*)", "", out)
    # Trim trailing "circuit/gate/thing/function" filler word that doesn't
    # carry semantic content for the synthesizer.
    out = re.sub(r"^\s*(?:circuit\s+for|circuit\s+where\s+)", "", out, flags=re.IGNORECASE)

    for pattern, repl in _ALIAS_RULES:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)

    # ── Range collapse: "3-5 input" / "3 to 5 inputs" / "3 or 4 input" ──────
    # The parser only handles a single input count, so a range like "3-5 input"
    # gets collapsed to the upper bound — that's what users typically mean
    # ("make a circuit with somewhere around 3-5 inputs" → use 5).
    def _collapse_range(m):
        hi = m.group('hi')
        unit = m.group('unit')
        return f"{hi} {unit}"
    out = re.sub(
        r"(?P<lo>\d+)\s*(?:-|to|or)\s*(?P<hi>\d+)\s+(?P<unit>inputs?|bit|bits)\b",
        _collapse_range, out, flags=re.IGNORECASE,
    )
    # "input are 1" → "inputs are 1" (subject-verb agreement fix the user often skips)
    out = re.sub(r"\binput\s+are\b", "inputs are", out, flags=re.IGNORECASE)
    out = re.sub(r"\binput\s+is\s+1\s+then\s+out", "inputs are 1 then output", out, flags=re.IGNORECASE)
    # "then out is" → "then output is"
    out = re.sub(r"\bthen\s+out\s+is\b", "then output is", out, flags=re.IGNORECASE)
    # "when inputs are 1" with no explicit quantifier → "when all inputs are 1"
    # (most natural reading — "when ANY input is 1" requires explicit "any/at least").
    out = re.sub(r"\bwhen\s+inputs\s+are\s+([01])\b",
                 r"when all inputs are \1", out, flags=re.IGNORECASE)
    out = re.sub(r"\bwhen\s+all\s+all\s+inputs", "when all inputs", out, flags=re.IGNORECASE)
    # "from N input(s)" / "with N input(s)" → "N-input circuit"
    out = re.sub(r"\b(?:from|with)\s+(\d+)\s+inputs?\b",
                 r"with \1 inputs", out, flags=re.IGNORECASE)

    # Discourse-marker rewrites  -  convert conjunctions that defeat the boolean
    # parser into ones it understands. Examples:
    #   "A and B but not C"   -> "A and B and not C"
    #   "A while B"           -> "A and B"
    #   "A together with B"   -> "A and B"
    out = re.sub(r'\bbut\s+not\b', 'and not', out, flags=re.IGNORECASE)
    out = re.sub(r'\bbut\b(?=\s+\w)',  'and', out, flags=re.IGNORECASE)
    out = re.sub(r'\b(?:while|together\s+with|along\s+with|alongside|plus)\b',
                 'and', out, flags=re.IGNORECASE)

    # "Y is the AND of A B C" / "the OR of all inputs" / "XOR of A and B"  -  turn
    # the verbose "X of <vars>" prefix into the corresponding operator and let
    # the boolean parser take it from there.
    op_word = {'and':'&', 'or':'|', 'xor':'^', 'nand':'~&', 'nor':'~|', 'xnor':'~^'}
    def _of_replace(m):
        op = op_word.get(m.group(1).lower())
        if not op: return m.group(0)
        rest = m.group(2)
        # Split vars on commas, "and", whitespace
        tokens = re.findall(r'\b[A-Za-z]\w*\b', rest)
        # Skip stopwords / outputs
        STOP = {'all','inputs','of','the','them','these','those','my','our'}
        vars_ = [t for t in tokens if t.lower() not in STOP]
        if len(vars_) < 2:                # default to A, B
            vars_ = ['A','B']
        if op.startswith('~'):
            joined = (' '+op[1]+' ').join(vars_)
            return '~(' + joined + ')'
        return (' '+op+' ').join(vars_)
    out = re.sub(
        r'\b(?:[YQZFY]\s*(?:is|=|equals?)\s*)?(?:the\s+)?'
        r'(AND|OR|XOR|NAND|NOR|XNOR)\s+of\s+(.+?)(?=\.|\?|$)',
        _of_replace, out, flags=re.IGNORECASE)

    # Assignment-form strip  -  "Y = expr" / "F is expr" / "Q equals expr".
    # We only strip when what follows is a SHORT expression (≤ 60 chars and
    # no "when/if/for/while")  -  otherwise "Y is 1 when A=1 and B=0" would
    # lose its truth-table semantics.
    m = re.match(
        r'^\s*(?:please\s+)?(?:[YFQZ]|out|output|result|y_out|out_y)'
        r'\s*(?:=|is|equals?|:=)\s*(.+)$',
        out, flags=re.IGNORECASE)
    if m:
        rest = m.group(1).strip()
        # Don't strip if it's actually "Y is 1 when ..."  -  that needs the
        # row-spec parser, not the boolean parser.
        if (len(rest) <= 60
                and not re.search(r'\b(?:when|if|for|while|unless)\b', rest)
                and not re.match(r'^\s*[01]\b', rest)):
            out = rest

    # Collapse repeated whitespace.
    out = re.sub(r'\s+', ' ', out).strip()
    return out


# --- Sequential / feedback circuit templates --------------------------------
#
# These can't be expressed as a pure boolean function (they require feedback
# wires), so we emit the gate/wire JSON directly. The simulator only does a
# topological pass so gates in a feedback loop will read 0 in static
# simulation  -  we still emit them because users want to see the structure.

def _raw_template_sr_latch_nor():
    return {
        'gates': [
            {'id': 'g1', 'type': 'INPUT',  'label': 'S', 'value': 0,
             'x': 80,  'y': 80},
            {'id': 'g2', 'type': 'INPUT',  'label': 'R', 'value': 0,
             'x': 80,  'y': 240},
            {'id': 'g3', 'type': 'NOR',   'x': 280, 'y': 80},   # -> Q_bar
            {'id': 'g4', 'type': 'NOR',   'x': 280, 'y': 240},  # -> Q
            {'id': 'g5', 'type': 'OUTPUT','label': 'Q_bar', 'x': 480, 'y': 80},
            {'id': 'g6', 'type': 'OUTPUT','label': 'Q',     'x': 480, 'y': 240},
        ],
        'wires': [
            {'id': 'w1', 'from_gate': 'g1', 'from_pin': 0,
             'to_gate':   'g3', 'to_pin': 0},   # S -> NOR1.in0
            {'id': 'w2', 'from_gate': 'g4', 'from_pin': 0,
             'to_gate':   'g3', 'to_pin': 1},   # Q -> NOR1.in1  (feedback)
            {'id': 'w3', 'from_gate': 'g2', 'from_pin': 0,
             'to_gate':   'g4', 'to_pin': 0},   # R -> NOR2.in0
            {'id': 'w4', 'from_gate': 'g3', 'from_pin': 0,
             'to_gate':   'g4', 'to_pin': 1},   # Q_bar -> NOR2.in1 (feedback)
            {'id': 'w5', 'from_gate': 'g3', 'from_pin': 0,
             'to_gate':   'g5', 'to_pin': 0},
            {'id': 'w6', 'from_gate': 'g4', 'from_pin': 0,
             'to_gate':   'g6', 'to_pin': 0},
        ],
    }


def _raw_template_sr_latch_nand():
    """Active-low S' R' latch (NAND cross-coupled)."""
    return {
        'gates': [
            {'id': 'g1', 'type': 'INPUT',  'label': 'S_bar', 'value': 1,
             'x': 80,  'y': 80},
            {'id': 'g2', 'type': 'INPUT',  'label': 'R_bar', 'value': 1,
             'x': 80,  'y': 240},
            {'id': 'g3', 'type': 'NAND',  'x': 280, 'y': 80},
            {'id': 'g4', 'type': 'NAND',  'x': 280, 'y': 240},
            {'id': 'g5', 'type': 'OUTPUT','label': 'Q',     'x': 480, 'y': 80},
            {'id': 'g6', 'type': 'OUTPUT','label': 'Q_bar', 'x': 480, 'y': 240},
        ],
        'wires': [
            {'id': 'w1', 'from_gate': 'g1', 'from_pin': 0,
             'to_gate':   'g3', 'to_pin': 0},
            {'id': 'w2', 'from_gate': 'g4', 'from_pin': 0,
             'to_gate':   'g3', 'to_pin': 1},
            {'id': 'w3', 'from_gate': 'g2', 'from_pin': 0,
             'to_gate':   'g4', 'to_pin': 0},
            {'id': 'w4', 'from_gate': 'g3', 'from_pin': 0,
             'to_gate':   'g4', 'to_pin': 1},
            {'id': 'w5', 'from_gate': 'g3', 'from_pin': 0,
             'to_gate':   'g5', 'to_pin': 0},
            {'id': 'w6', 'from_gate': 'g4', 'from_pin': 0,
             'to_gate':   'g6', 'to_pin': 0},
        ],
    }


def _raw_template_d_latch():
    """Gated D latch: S = D & E,  R = ~D & E, then NOR-based SR core."""
    return {
        'gates': [
            {'id': 'g1', 'type': 'INPUT',  'label': 'D', 'value': 0,
             'x':  80, 'y':  80},
            {'id': 'g2', 'type': 'INPUT',  'label': 'E', 'value': 0,
             'x':  80, 'y': 240},
            {'id': 'g3', 'type': 'NOT',   'x': 240, 'y':  80},  # ~D
            {'id': 'g4', 'type': 'AND',   'x': 400, 'y':  80},  # S = D & E
            {'id': 'g5', 'type': 'AND',   'x': 400, 'y': 240},  # R = ~D & E
            {'id': 'g6', 'type': 'NOR',   'x': 580, 'y':  80},  # -> Q_bar
            {'id': 'g7', 'type': 'NOR',   'x': 580, 'y': 240},  # -> Q
            {'id': 'g8', 'type': 'OUTPUT','label': 'Q_bar', 'x': 760, 'y':  80},
            {'id': 'g9', 'type': 'OUTPUT','label': 'Q',     'x': 760, 'y': 240},
        ],
        'wires': [
            {'id': 'w1', 'from_gate': 'g1', 'from_pin': 0, 'to_gate': 'g3', 'to_pin': 0},  # D->NOT
            {'id': 'w2', 'from_gate': 'g1', 'from_pin': 0, 'to_gate': 'g4', 'to_pin': 0},  # D->AND_S
            {'id': 'w3', 'from_gate': 'g2', 'from_pin': 0, 'to_gate': 'g4', 'to_pin': 1},  # E->AND_S
            {'id': 'w4', 'from_gate': 'g3', 'from_pin': 0, 'to_gate': 'g5', 'to_pin': 0},  # ~D->AND_R
            {'id': 'w5', 'from_gate': 'g2', 'from_pin': 0, 'to_gate': 'g5', 'to_pin': 1},  # E->AND_R
            {'id': 'w6', 'from_gate': 'g4', 'from_pin': 0, 'to_gate': 'g6', 'to_pin': 0},  # S->NOR1
            {'id': 'w7', 'from_gate': 'g7', 'from_pin': 0, 'to_gate': 'g6', 'to_pin': 1},  # Q->NOR1 (feedback)
            {'id': 'w8', 'from_gate': 'g5', 'from_pin': 0, 'to_gate': 'g7', 'to_pin': 0},  # R->NOR2
            {'id': 'w9', 'from_gate': 'g6', 'from_pin': 0, 'to_gate': 'g7', 'to_pin': 1},  # Q_bar->NOR2 (feedback)
            {'id': 'w10', 'from_gate': 'g6', 'from_pin': 0, 'to_gate': 'g8', 'to_pin': 0},
            {'id': 'w11', 'from_gate': 'g7', 'from_pin': 0, 'to_gate': 'g9', 'to_pin': 0},
        ],
    }


def _raw_template_d_flipflop():
    """Master-slave D flip-flop: master D latch on ~CLK, slave on CLK."""
    return {
        'gates': [
            {'id': 'g1',  'type': 'INPUT',  'label': 'D',   'value': 0, 'x':  80, 'y':  80},
            {'id': 'g2',  'type': 'INPUT',  'label': 'CLK', 'value': 0, 'x':  80, 'y': 320},
            {'id': 'g3',  'type': 'NOT',   'x': 220, 'y': 320},   # ~CLK for master
            # Master latch (clocked on ~CLK)
            {'id': 'g4',  'type': 'NOT',   'x': 220, 'y':  80},   # ~D
            {'id': 'g5',  'type': 'AND',   'x': 360, 'y':  80},   # S_m
            {'id': 'g6',  'type': 'AND',   'x': 360, 'y': 200},   # R_m
            {'id': 'g7',  'type': 'NOR',   'x': 500, 'y':  80},   # Qm_bar
            {'id': 'g8',  'type': 'NOR',   'x': 500, 'y': 200},   # Qm
            # Slave latch (clocked on CLK)
            {'id': 'g9',  'type': 'NOT',   'x': 640, 'y':  80},   # ~Qm
            {'id': 'g10', 'type': 'AND',   'x': 780, 'y':  80},   # S_s
            {'id': 'g11', 'type': 'AND',   'x': 780, 'y': 200},   # R_s
            {'id': 'g12', 'type': 'NOR',   'x': 920, 'y':  80},   # Q_bar
            {'id': 'g13', 'type': 'NOR',   'x': 920, 'y': 200},   # Q
            {'id': 'g14', 'type': 'OUTPUT','label': 'Q_bar', 'x': 1080, 'y':  80},
            {'id': 'g15', 'type': 'OUTPUT','label': 'Q',     'x': 1080, 'y': 200},
        ],
        'wires': [
            {'id': 'w1',  'from_gate': 'g2',  'from_pin': 0, 'to_gate': 'g3',  'to_pin': 0},  # CLK->NOT
            {'id': 'w2',  'from_gate': 'g1',  'from_pin': 0, 'to_gate': 'g4',  'to_pin': 0},  # D->NOT
            {'id': 'w3',  'from_gate': 'g1',  'from_pin': 0, 'to_gate': 'g5',  'to_pin': 0},  # D->AND
            {'id': 'w4',  'from_gate': 'g3',  'from_pin': 0, 'to_gate': 'g5',  'to_pin': 1},  # ~CLK->AND
            {'id': 'w5',  'from_gate': 'g4',  'from_pin': 0, 'to_gate': 'g6',  'to_pin': 0},  # ~D->AND
            {'id': 'w6',  'from_gate': 'g3',  'from_pin': 0, 'to_gate': 'g6',  'to_pin': 1},  # ~CLK->AND
            {'id': 'w7',  'from_gate': 'g5',  'from_pin': 0, 'to_gate': 'g7',  'to_pin': 0},  # S_m->NOR
            {'id': 'w8',  'from_gate': 'g8',  'from_pin': 0, 'to_gate': 'g7',  'to_pin': 1},  # Qm->NOR (fb)
            {'id': 'w9',  'from_gate': 'g6',  'from_pin': 0, 'to_gate': 'g8',  'to_pin': 0},  # R_m->NOR
            {'id': 'w10', 'from_gate': 'g7',  'from_pin': 0, 'to_gate': 'g8',  'to_pin': 1},  # Qm_bar->NOR (fb)
            {'id': 'w11', 'from_gate': 'g8',  'from_pin': 0, 'to_gate': 'g9',  'to_pin': 0},  # Qm->NOT
            {'id': 'w12', 'from_gate': 'g8',  'from_pin': 0, 'to_gate': 'g10', 'to_pin': 0},  # Qm->AND
            {'id': 'w13', 'from_gate': 'g2',  'from_pin': 0, 'to_gate': 'g10', 'to_pin': 1},  # CLK->AND
            {'id': 'w14', 'from_gate': 'g9',  'from_pin': 0, 'to_gate': 'g11', 'to_pin': 0},  # ~Qm->AND
            {'id': 'w15', 'from_gate': 'g2',  'from_pin': 0, 'to_gate': 'g11', 'to_pin': 1},  # CLK->AND
            {'id': 'w16', 'from_gate': 'g10', 'from_pin': 0, 'to_gate': 'g12', 'to_pin': 0},
            {'id': 'w17', 'from_gate': 'g13', 'from_pin': 0, 'to_gate': 'g12', 'to_pin': 1},  # fb
            {'id': 'w18', 'from_gate': 'g11', 'from_pin': 0, 'to_gate': 'g13', 'to_pin': 0},
            {'id': 'w19', 'from_gate': 'g12', 'from_pin': 0, 'to_gate': 'g13', 'to_pin': 1},  # fb
            {'id': 'w20', 'from_gate': 'g12', 'from_pin': 0, 'to_gate': 'g14', 'to_pin': 0},
            {'id': 'w21', 'from_gate': 'g13', 'from_pin': 0, 'to_gate': 'g15', 'to_pin': 0},
        ],
    }


def _raw_template_jk_flipflop():
    """JK FF (level-sensitive). J,K,CLK inputs feed AND->NAND SR core."""
    # S = J & CLK & ~Q ; R = K & CLK & Q. Use staged ANDs (2-input).
    return {
        'gates': [
            {'id': 'g1',  'type': 'INPUT',  'label': 'J',   'value': 0, 'x':  80, 'y':  80},
            {'id': 'g2',  'type': 'INPUT',  'label': 'CLK', 'value': 0, 'x':  80, 'y': 240},
            {'id': 'g3',  'type': 'INPUT',  'label': 'K',   'value': 0, 'x':  80, 'y': 400},
            {'id': 'g4',  'type': 'AND',   'x': 260, 'y':  80},   # J & CLK
            {'id': 'g5',  'type': 'AND',   'x': 260, 'y': 400},   # K & CLK
            {'id': 'g6',  'type': 'AND',   'x': 440, 'y':  80},   # (J&CLK) & ~Q  -> S
            {'id': 'g7',  'type': 'AND',   'x': 440, 'y': 400},   # (K&CLK) & Q   -> R
            {'id': 'g8',  'type': 'NOR',   'x': 640, 'y':  80},   # Q_bar
            {'id': 'g9',  'type': 'NOR',   'x': 640, 'y': 400},   # Q
            {'id': 'g10', 'type': 'OUTPUT','label': 'Q_bar', 'x': 820, 'y':  80},
            {'id': 'g11', 'type': 'OUTPUT','label': 'Q',     'x': 820, 'y': 400},
        ],
        'wires': [
            {'id': 'w1', 'from_gate': 'g1', 'from_pin': 0, 'to_gate': 'g4', 'to_pin': 0},
            {'id': 'w2', 'from_gate': 'g2', 'from_pin': 0, 'to_gate': 'g4', 'to_pin': 1},
            {'id': 'w3', 'from_gate': 'g3', 'from_pin': 0, 'to_gate': 'g5', 'to_pin': 0},
            {'id': 'w4', 'from_gate': 'g2', 'from_pin': 0, 'to_gate': 'g5', 'to_pin': 1},
            {'id': 'w5', 'from_gate': 'g4', 'from_pin': 0, 'to_gate': 'g6', 'to_pin': 0},
            {'id': 'w6', 'from_gate': 'g8', 'from_pin': 0, 'to_gate': 'g6', 'to_pin': 1},   # ~Q (Q_bar)
            {'id': 'w7', 'from_gate': 'g5', 'from_pin': 0, 'to_gate': 'g7', 'to_pin': 0},
            {'id': 'w8', 'from_gate': 'g9', 'from_pin': 0, 'to_gate': 'g7', 'to_pin': 1},   # Q
            {'id': 'w9',  'from_gate': 'g6', 'from_pin': 0, 'to_gate': 'g8', 'to_pin': 0},  # S->NOR
            {'id': 'w10', 'from_gate': 'g9', 'from_pin': 0, 'to_gate': 'g8', 'to_pin': 1},  # Q->NOR (fb)
            {'id': 'w11', 'from_gate': 'g7', 'from_pin': 0, 'to_gate': 'g9', 'to_pin': 0},  # R->NOR
            {'id': 'w12', 'from_gate': 'g8', 'from_pin': 0, 'to_gate': 'g9', 'to_pin': 1},  # Q_bar->NOR (fb)
            {'id': 'w13', 'from_gate': 'g8', 'from_pin': 0, 'to_gate': 'g10', 'to_pin': 0},
            {'id': 'w14', 'from_gate': 'g9', 'from_pin': 0, 'to_gate': 'g11', 'to_pin': 0},
        ],
    }


def _raw_template_t_flipflop():
    """T FF = JK with J=K=T. Wire one INPUT T to both J and K inputs of a JK."""
    return {
        'gates': [
            {'id': 'g1',  'type': 'INPUT',  'label': 'T',   'value': 0, 'x':  80, 'y': 160},
            {'id': 'g2',  'type': 'INPUT',  'label': 'CLK', 'value': 0, 'x':  80, 'y': 320},
            {'id': 'g3',  'type': 'AND',   'x': 260, 'y':  80},   # T & CLK (= J&CLK)
            {'id': 'g4',  'type': 'AND',   'x': 260, 'y': 400},   # T & CLK (= K&CLK)
            {'id': 'g5',  'type': 'AND',   'x': 440, 'y':  80},   # S = (T&CLK)&~Q
            {'id': 'g6',  'type': 'AND',   'x': 440, 'y': 400},   # R = (T&CLK)& Q
            {'id': 'g7',  'type': 'NOR',   'x': 640, 'y':  80},   # Q_bar
            {'id': 'g8',  'type': 'NOR',   'x': 640, 'y': 400},   # Q
            {'id': 'g9',  'type': 'OUTPUT','label': 'Q_bar', 'x': 820, 'y':  80},
            {'id': 'g10', 'type': 'OUTPUT','label': 'Q',     'x': 820, 'y': 400},
        ],
        'wires': [
            {'id': 'w1', 'from_gate': 'g1', 'from_pin': 0, 'to_gate': 'g3', 'to_pin': 0},
            {'id': 'w2', 'from_gate': 'g2', 'from_pin': 0, 'to_gate': 'g3', 'to_pin': 1},
            {'id': 'w3', 'from_gate': 'g1', 'from_pin': 0, 'to_gate': 'g4', 'to_pin': 0},
            {'id': 'w4', 'from_gate': 'g2', 'from_pin': 0, 'to_gate': 'g4', 'to_pin': 1},
            {'id': 'w5', 'from_gate': 'g3', 'from_pin': 0, 'to_gate': 'g5', 'to_pin': 0},
            {'id': 'w6', 'from_gate': 'g7', 'from_pin': 0, 'to_gate': 'g5', 'to_pin': 1},
            {'id': 'w7', 'from_gate': 'g4', 'from_pin': 0, 'to_gate': 'g6', 'to_pin': 0},
            {'id': 'w8', 'from_gate': 'g8', 'from_pin': 0, 'to_gate': 'g6', 'to_pin': 1},
            {'id': 'w9',  'from_gate': 'g5', 'from_pin': 0, 'to_gate': 'g7', 'to_pin': 0},
            {'id': 'w10', 'from_gate': 'g8', 'from_pin': 0, 'to_gate': 'g7', 'to_pin': 1},
            {'id': 'w11', 'from_gate': 'g6', 'from_pin': 0, 'to_gate': 'g8', 'to_pin': 0},
            {'id': 'w12', 'from_gate': 'g7', 'from_pin': 0, 'to_gate': 'g8', 'to_pin': 1},
            {'id': 'w13', 'from_gate': 'g7', 'from_pin': 0, 'to_gate': 'g9',  'to_pin': 0},
            {'id': 'w14', 'from_gate': 'g8', 'from_pin': 0, 'to_gate': 'g10', 'to_pin': 0},
        ],
    }


def _raw_template_full_adder_from_half():
    """Full adder built from two HALF-ADDER MACRO BLOCKS + OR.

    Shows the actual sub-block composition (HA macros visible on canvas)
    rather than expanding to primitives. Pin layout:
      HA1: in0=A, in1=B  ->  out0=S1, out1=C1
      HA2: in0=S1, in1=Cin -> out0=Sum, out1=C2
      OR(C1, C2) = Cout
    """
    return {
        'gates': [
            {'id': 'g1', 'type': 'INPUT',  'label': 'A',   'value': 0, 'x':  80, 'y':  80},
            {'id': 'g2', 'type': 'INPUT',  'label': 'B',   'value': 0, 'x':  80, 'y': 180},
            {'id': 'g3', 'type': 'INPUT',  'label': 'Cin', 'value': 0, 'x':  80, 'y': 320},
            # Half-adder macro #1 (sub-block, NOT expanded)
            {'id': 'g4', 'type': 'HA',                                  'x': 280, 'y': 130},
            # Half-adder macro #2 (sub-block, NOT expanded)
            {'id': 'g5', 'type': 'HA',                                  'x': 500, 'y': 240},
            # OR to combine the two carries
            {'id': 'g6', 'type': 'OR',                                  'x': 720, 'y': 340},
            {'id': 'g7', 'type': 'OUTPUT','label': 'Sum',               'x': 920, 'y': 240},
            {'id': 'g8', 'type': 'OUTPUT','label': 'Cout',              'x': 920, 'y': 340},
        ],
        'wires': [
            # Layer 1: inputs into HA1
            {'id': 'w1', 'from_gate': 'g1', 'from_pin': 0, 'to_gate': 'g4', 'to_pin': 0},  # A   -> HA1.in0
            {'id': 'w2', 'from_gate': 'g2', 'from_pin': 0, 'to_gate': 'g4', 'to_pin': 1},  # B   -> HA1.in1
            # Layer 2: HA1 outputs feed HA2
            {'id': 'w3', 'from_gate': 'g4', 'from_pin': 0, 'to_gate': 'g5', 'to_pin': 0},  # S1  -> HA2.in0
            {'id': 'w4', 'from_gate': 'g3', 'from_pin': 0, 'to_gate': 'g5', 'to_pin': 1},  # Cin -> HA2.in1
            # Carry combine
            {'id': 'w5', 'from_gate': 'g4', 'from_pin': 1, 'to_gate': 'g6', 'to_pin': 0},  # C1  -> OR.in0
            {'id': 'w6', 'from_gate': 'g5', 'from_pin': 1, 'to_gate': 'g6', 'to_pin': 1},  # C2  -> OR.in1
            # Outputs
            {'id': 'w7', 'from_gate': 'g5', 'from_pin': 0, 'to_gate': 'g7', 'to_pin': 0},  # HA2.S -> Sum
            {'id': 'w8', 'from_gate': 'g6', 'from_pin': 0, 'to_gate': 'g8', 'to_pin': 0},  # OR    -> Cout
        ],
    }


def _raw_template_4to1_mux():
    """4-to-1 multiplexer with 4 data inputs (D0-D3) and 2 select lines (S0,S1)."""
    return {
        'gates': [
            {'id': 'g1', 'type': 'INPUT', 'label': 'D0', 'value': 0, 'x':  80, 'y':  40},
            {'id': 'g2', 'type': 'INPUT', 'label': 'D1', 'value': 0, 'x':  80, 'y': 110},
            {'id': 'g3', 'type': 'INPUT', 'label': 'D2', 'value': 0, 'x':  80, 'y': 180},
            {'id': 'g4', 'type': 'INPUT', 'label': 'D3', 'value': 0, 'x':  80, 'y': 250},
            {'id': 'g5', 'type': 'INPUT', 'label': 'S0', 'value': 0, 'x':  80, 'y': 330},
            {'id': 'g6', 'type': 'INPUT', 'label': 'S1', 'value': 0, 'x':  80, 'y': 400},
            {'id': 'n1', 'type': 'NOT',                              'x': 220, 'y': 330},  # ~S0
            {'id': 'n2', 'type': 'NOT',                              'x': 220, 'y': 400},  # ~S1
            {'id': 'a1', 'type': 'AND',                              'x': 380, 'y':  40},  # D0 & ~S0 & ~S1
            {'id': 'a2', 'type': 'AND',                              'x': 380, 'y': 110},  # D1 &  S0 & ~S1
            {'id': 'a3', 'type': 'AND',                              'x': 380, 'y': 180},  # D2 & ~S0 &  S1
            {'id': 'a4', 'type': 'AND',                              'x': 380, 'y': 250},  # D3 &  S0 &  S1
            {'id': 'o1', 'type': 'OR',                               'x': 580, 'y': 140},
            {'id': 'o2', 'type': 'OR',                               'x': 580, 'y': 220},
            {'id': 'o3', 'type': 'OR',                               'x': 760, 'y': 180},
            {'id': 'gO', 'type': 'OUTPUT','label': 'Y',              'x': 940, 'y': 180},
        ],
        'wires': [
            {'id':'w1','from_gate':'g5','from_pin':0,'to_gate':'n1','to_pin':0},
            {'id':'w2','from_gate':'g6','from_pin':0,'to_gate':'n2','to_pin':0},
            # AND fan-in is 2, so each AND only takes Dx & one select-product.
            # Build select products externally is heavier — use 3-input collapse
            # by stacking ANDs in pairs.
            {'id':'w3','from_gate':'g1','from_pin':0,'to_gate':'a1','to_pin':0},
            {'id':'w4','from_gate':'n1','from_pin':0,'to_gate':'a1','to_pin':1},
            {'id':'w5','from_gate':'g2','from_pin':0,'to_gate':'a2','to_pin':0},
            {'id':'w6','from_gate':'g5','from_pin':0,'to_gate':'a2','to_pin':1},
            {'id':'w7','from_gate':'g3','from_pin':0,'to_gate':'a3','to_pin':0},
            {'id':'w8','from_gate':'g6','from_pin':0,'to_gate':'a3','to_pin':1},
            {'id':'w9','from_gate':'g4','from_pin':0,'to_gate':'a4','to_pin':0},
            {'id':'w10','from_gate':'g5','from_pin':0,'to_gate':'a4','to_pin':1},
            {'id':'w11','from_gate':'a1','from_pin':0,'to_gate':'o1','to_pin':0},
            {'id':'w12','from_gate':'a2','from_pin':0,'to_gate':'o1','to_pin':1},
            {'id':'w13','from_gate':'a3','from_pin':0,'to_gate':'o2','to_pin':0},
            {'id':'w14','from_gate':'a4','from_pin':0,'to_gate':'o2','to_pin':1},
            {'id':'w15','from_gate':'o1','from_pin':0,'to_gate':'o3','to_pin':0},
            {'id':'w16','from_gate':'o2','from_pin':0,'to_gate':'o3','to_pin':1},
            {'id':'w17','from_gate':'o3','from_pin':0,'to_gate':'gO','to_pin':0},
        ],
    }


# ─── Compose-from-macro-block templates ─────────────────────────────────────
# These produce circuits where the building blocks remain visible as MACRO
# GATES (HA, FA, DFF, etc.), rather than being expanded to AND/OR/NOT/XOR.
# Lets the user "build X using HA / FA / DFF" and actually see sub-blocks.

def _raw_template_4bit_adder_from_fa():
    """4-bit ripple-carry adder built from 4 visible FA macro blocks.
       FA pin layout: in0=A, in1=B, in2=Cin → out0=S, out1=Cout"""
    gates, wires = [], []
    # Inputs
    for i in range(4):
        gates.append({'id': f'A{i}', 'type': 'INPUT', 'label': f'A{i}', 'value': 0,
                      'x': 60, 'y': 60 + i * 90})
        gates.append({'id': f'B{i}', 'type': 'INPUT', 'label': f'B{i}', 'value': 0,
                      'x': 60, 'y': 100 + i * 90})
    gates.append({'id': 'Cin', 'type': 'INPUT', 'label': 'Cin', 'value': 0,
                  'x': 60, 'y': 470})
    # 4 Full Adder macro blocks
    for i in range(4):
        gates.append({'id': f'FA{i}', 'type': 'FA',
                      'x': 260 + i * 160, 'y': 80 + i * 70})
    # Outputs
    for i in range(4):
        gates.append({'id': f'S{i}', 'type': 'OUTPUT', 'label': f'S{i}',
                      'x': 260 + i * 160, 'y': 30 + i * 70})
    gates.append({'id': 'Cout', 'type': 'OUTPUT', 'label': 'Cout',
                  'x': 860, 'y': 380})
    # Wires
    wid = 0
    def w(fg, fp, tg, tp):
        nonlocal wid
        wid += 1
        wires.append({'id': f'w{wid}', 'from_gate': fg, 'from_pin': fp,
                      'to_gate': tg, 'to_pin': tp})
    prev_carry = 'Cin'
    prev_carry_pin = 0
    for i in range(4):
        w(f'A{i}', 0, f'FA{i}', 0)             # Ai -> FA.in0
        w(f'B{i}', 0, f'FA{i}', 1)             # Bi -> FA.in1
        w(prev_carry, prev_carry_pin, f'FA{i}', 2)  # carry chain
        w(f'FA{i}', 0, f'S{i}', 0)             # Sum out
        prev_carry, prev_carry_pin = f'FA{i}', 1
    w('FA3', 1, 'Cout', 0)
    return {'gates': gates, 'wires': wires}


def _raw_template_8bit_adder_from_fa():
    """8-bit ripple-carry adder built from 8 visible FA macro blocks."""
    gates, wires = [], []
    for i in range(8):
        gates.append({'id': f'A{i}', 'type': 'INPUT', 'label': f'A{i}', 'value': 0,
                      'x': 40, 'y': 30 + i * 90})
        gates.append({'id': f'B{i}', 'type': 'INPUT', 'label': f'B{i}', 'value': 0,
                      'x': 40, 'y': 65 + i * 90})
    gates.append({'id': 'Cin', 'type': 'INPUT', 'label': 'Cin', 'value': 0,
                  'x': 40, 'y': 770})
    for i in range(8):
        gates.append({'id': f'FA{i}', 'type': 'FA',
                      'x': 230 + i * 130, 'y': 50 + i * 60})
    for i in range(8):
        gates.append({'id': f'S{i}', 'type': 'OUTPUT', 'label': f'S{i}',
                      'x': 230 + i * 130, 'y': 10 + i * 60})
    gates.append({'id': 'Cout', 'type': 'OUTPUT', 'label': 'Cout',
                  'x': 1300, 'y': 530})
    wid = 0
    def w(fg, fp, tg, tp):
        nonlocal wid
        wid += 1
        wires.append({'id': f'w{wid}', 'from_gate': fg, 'from_pin': fp,
                      'to_gate': tg, 'to_pin': tp})
    prev_carry, prev_pin = 'Cin', 0
    for i in range(8):
        w(f'A{i}', 0, f'FA{i}', 0)
        w(f'B{i}', 0, f'FA{i}', 1)
        w(prev_carry, prev_pin, f'FA{i}', 2)
        w(f'FA{i}', 0, f'S{i}', 0)
        prev_carry, prev_pin = f'FA{i}', 1
    w('FA7', 1, 'Cout', 0)
    return {'gates': gates, 'wires': wires}


def _raw_template_4bit_register_from_dff():
    """4-bit parallel register built from 4 visible D-FF macro blocks sharing
       one CLK input. Pin layout for DFF: in0=D, in1=CLK → out0=Q, out1=Qbar."""
    gates, wires = [], []
    for i in range(4):
        gates.append({'id': f'D{i}', 'type': 'INPUT', 'label': f'D{i}', 'value': 0,
                      'x': 80, 'y': 60 + i * 110})
    gates.append({'id': 'CLK', 'type': 'CLOCK', 'label': 'CLK',
                  'x': 80, 'y': 500})
    for i in range(4):
        gates.append({'id': f'DFF{i}', 'type': 'DFF',
                      'x': 280, 'y': 80 + i * 110})
    for i in range(4):
        gates.append({'id': f'Q{i}', 'type': 'OUTPUT', 'label': f'Q{i}',
                      'x': 500, 'y': 80 + i * 110})
    wid = 0
    def w(fg, fp, tg, tp):
        nonlocal wid; wid += 1
        wires.append({'id': f'w{wid}', 'from_gate': fg, 'from_pin': fp,
                      'to_gate': tg, 'to_pin': tp})
    for i in range(4):
        w(f'D{i}', 0, f'DFF{i}', 0)
        w('CLK',   0, f'DFF{i}', 1)
        w(f'DFF{i}', 0, f'Q{i}', 0)
    return {'gates': gates, 'wires': wires}


def _raw_template_8bit_register_from_dff():
    """8-bit parallel register built from 8 visible D-FF macro blocks."""
    gates, wires = [], []
    for i in range(8):
        gates.append({'id': f'D{i}', 'type': 'INPUT', 'label': f'D{i}', 'value': 0,
                      'x': 60, 'y': 40 + i * 90})
    gates.append({'id': 'CLK', 'type': 'CLOCK', 'label': 'CLK',
                  'x': 60, 'y': 770})
    for i in range(8):
        gates.append({'id': f'DFF{i}', 'type': 'DFF',
                      'x': 260, 'y': 60 + i * 90})
        gates.append({'id': f'Q{i}', 'type': 'OUTPUT', 'label': f'Q{i}',
                      'x': 460, 'y': 60 + i * 90})
    wid = 0
    def w(fg, fp, tg, tp):
        nonlocal wid; wid += 1
        wires.append({'id': f'w{wid}', 'from_gate': fg, 'from_pin': fp,
                      'to_gate': tg, 'to_pin': tp})
    for i in range(8):
        w(f'D{i}', 0, f'DFF{i}', 0)
        w('CLK',   0, f'DFF{i}', 1)
        w(f'DFF{i}', 0, f'Q{i}', 0)
    return {'gates': gates, 'wires': wires}


def _raw_template_4bit_shift_reg_from_dff():
    """4-bit serial-in / parallel-out shift register: 4 D-FF macros chained,
       each FF's Q feeds the next FF's D. Shared CLK."""
    gates, wires = [], []
    gates.append({'id': 'SIN', 'type': 'INPUT', 'label': 'SerIn', 'value': 0,
                  'x': 60, 'y': 80})
    gates.append({'id': 'CLK', 'type': 'CLOCK', 'label': 'CLK',
                  'x': 60, 'y': 280})
    for i in range(4):
        gates.append({'id': f'DFF{i}', 'type': 'DFF',
                      'x': 240 + i * 180, 'y': 100})
        gates.append({'id': f'Q{i}', 'type': 'OUTPUT', 'label': f'Q{i}',
                      'x': 280 + i * 180, 'y': 40})
    wid = 0
    def w(fg, fp, tg, tp):
        nonlocal wid; wid += 1
        wires.append({'id': f'w{wid}', 'from_gate': fg, 'from_pin': fp,
                      'to_gate': tg, 'to_pin': tp})
    prev_out, prev_pin = 'SIN', 0
    for i in range(4):
        w(prev_out, prev_pin, f'DFF{i}', 0)
        w('CLK',    0,        f'DFF{i}', 1)
        w(f'DFF{i}', 0, f'Q{i}', 0)
        prev_out, prev_pin = f'DFF{i}', 0
    return {'gates': gates, 'wires': wires}


def _raw_template_ring_counter_4bit():
    """4-bit ring counter built from 4 DFF macros in a ring: each FF's Q
       feeds the next, and the last FF's Q feeds back to the first."""
    gates, wires = [], []
    gates.append({'id': 'CLK', 'type': 'CLOCK', 'label': 'CLK',
                  'x': 60, 'y': 320})
    for i in range(4):
        gates.append({'id': f'DFF{i}', 'type': 'DFF',
                      'x': 200 + i * 180, 'y': 120})
        gates.append({'id': f'Q{i}', 'type': 'OUTPUT', 'label': f'Q{i}',
                      'x': 240 + i * 180, 'y': 60})
    wid = 0
    def w(fg, fp, tg, tp):
        nonlocal wid; wid += 1
        wires.append({'id': f'w{wid}', 'from_gate': fg, 'from_pin': fp,
                      'to_gate': tg, 'to_pin': tp})
    for i in range(4):
        prev = f'DFF{(i - 1) % 4}'
        w(prev, 0, f'DFF{i}', 0)        # Q[i-1] -> D[i]
        w('CLK', 0, f'DFF{i}', 1)
        w(f'DFF{i}', 0, f'Q{i}', 0)
    return {'gates': gates, 'wires': wires}


def _raw_template_4bit_counter_from_tff():
    """4-bit ripple counter built from 4 visible T-FF macros chained.
       Each TFF's Q feeds the next TFF's CLK. First TFF's T is tied HIGH."""
    gates, wires = [], []
    gates.append({'id': 'VCC', 'type': 'VCC', 'label': 'HIGH',
                  'x': 60, 'y': 80})
    gates.append({'id': 'CLK', 'type': 'CLOCK', 'label': 'CLK',
                  'x': 60, 'y': 220})
    for i in range(4):
        gates.append({'id': f'TFF{i}', 'type': 'TFF',
                      'x': 240 + i * 180, 'y': 140})
        gates.append({'id': f'Q{i}', 'type': 'OUTPUT', 'label': f'Q{i}',
                      'x': 280 + i * 180, 'y': 60})
    wid = 0
    def w(fg, fp, tg, tp):
        nonlocal wid; wid += 1
        wires.append({'id': f'w{wid}', 'from_gate': fg, 'from_pin': fp,
                      'to_gate': tg, 'to_pin': tp})
    for i in range(4):
        w('VCC', 0, f'TFF{i}', 0)   # T tied high
        if i == 0:
            w('CLK', 0, f'TFF{0}', 1)
        else:
            w(f'TFF{i-1}', 0, f'TFF{i}', 1)  # previous Q drives next CLK
        w(f'TFF{i}', 0, f'Q{i}', 0)
    return {'gates': gates, 'wires': wires}


def _raw_template_4to1_mux_from_mux2():
    """4-to-1 multiplexer built from 3 visible 2:1 MUX macros (tree of MUX2).
       MUX2 pin layout: in0=A, in1=B, in2=SEL → out0=Y."""
    gates, wires = [], []
    for i in range(4):
        gates.append({'id': f'D{i}', 'type': 'INPUT', 'label': f'D{i}', 'value': 0,
                      'x': 60, 'y': 40 + i * 80})
    gates.append({'id': 'S0', 'type': 'INPUT', 'label': 'S0', 'value': 0,
                  'x': 60, 'y': 380})
    gates.append({'id': 'S1', 'type': 'INPUT', 'label': 'S1', 'value': 0,
                  'x': 60, 'y': 450})
    gates.append({'id': 'M1', 'type': 'MUX2', 'x': 280, 'y':  60})  # D0, D1, S0
    gates.append({'id': 'M2', 'type': 'MUX2', 'x': 280, 'y': 220})  # D2, D3, S0
    gates.append({'id': 'M3', 'type': 'MUX2', 'x': 500, 'y': 140})  # M1, M2, S1
    gates.append({'id': 'Y',  'type': 'OUTPUT', 'label': 'Y', 'x': 700, 'y': 160})
    wid = 0
    def w(fg, fp, tg, tp):
        nonlocal wid; wid += 1
        wires.append({'id': f'w{wid}', 'from_gate': fg, 'from_pin': fp,
                      'to_gate': tg, 'to_pin': tp})
    w('D0', 0, 'M1', 0); w('D1', 0, 'M1', 1); w('S0', 0, 'M1', 2)
    w('D2', 0, 'M2', 0); w('D3', 0, 'M2', 1); w('S0', 0, 'M2', 2)
    w('M1', 0, 'M3', 0); w('M2', 0, 'M3', 1); w('S1', 0, 'M3', 2)
    w('M3', 0, 'Y',  0)
    return {'gates': gates, 'wires': wires}


def _raw_template_subtractor_from_fa():
    """4-bit subtractor: A - B  via FA macros with B inverted + Cin=1.
       (Standard 2's-complement subtraction implementation.)"""
    gates, wires = [], []
    for i in range(4):
        gates.append({'id': f'A{i}', 'type': 'INPUT', 'label': f'A{i}', 'value': 0,
                      'x': 40, 'y': 40 + i * 90})
        gates.append({'id': f'B{i}', 'type': 'INPUT', 'label': f'B{i}', 'value': 0,
                      'x': 40, 'y': 75 + i * 90})
        gates.append({'id': f'NB{i}', 'type': 'NOT',
                      'x': 180, 'y': 75 + i * 90})  # ~B inverters
    gates.append({'id': 'VCC', 'type': 'VCC', 'label': 'HIGH',
                  'x': 40, 'y': 440})  # Cin = 1 for 2's complement
    for i in range(4):
        gates.append({'id': f'FA{i}', 'type': 'FA',
                      'x': 340 + i * 160, 'y': 90 + i * 70})
        gates.append({'id': f'D{i}', 'type': 'OUTPUT', 'label': f'D{i}',
                      'x': 340 + i * 160, 'y': 40 + i * 70})
    gates.append({'id': 'Borrow', 'type': 'OUTPUT', 'label': 'Bout',
                  'x': 940, 'y': 420})
    wid = 0
    def w(fg, fp, tg, tp):
        nonlocal wid; wid += 1
        wires.append({'id': f'w{wid}', 'from_gate': fg, 'from_pin': fp,
                      'to_gate': tg, 'to_pin': tp})
    prev_c, prev_p = 'VCC', 0
    for i in range(4):
        w(f'B{i}', 0, f'NB{i}', 0)
        w(f'A{i}', 0, f'FA{i}', 0)
        w(f'NB{i}', 0, f'FA{i}', 1)
        w(prev_c, prev_p, f'FA{i}', 2)
        w(f'FA{i}', 0, f'D{i}', 0)
        prev_c, prev_p = f'FA{i}', 1
    w('FA3', 1, 'Borrow', 0)
    return {'gates': gates, 'wires': wires}


RAW_TEMPLATES = {
    'sr latch':       _raw_template_sr_latch_nor,
    'sr latch nor':   _raw_template_sr_latch_nor,
    'sr latch nand':  _raw_template_sr_latch_nand,
    'set reset latch': _raw_template_sr_latch_nor,
    'd latch':        _raw_template_d_latch,
    'gated d latch':  _raw_template_d_latch,
    'd flip flop':    _raw_template_d_flipflop,
    'd-type flip flop': _raw_template_d_flipflop,
    'master slave flip flop': _raw_template_d_flipflop,
    'jk flip flop':   _raw_template_jk_flipflop,
    'sr flip flop':   _raw_template_jk_flipflop,   # JK is the SR-without-undefined variant
    't flip flop':    _raw_template_t_flipflop,
    'toggle flip flop': _raw_template_t_flipflop,
    # Compositional builds (matched by RAW_TEMPLATES loop in build_from_text)
    'full adder from half adder':      _raw_template_full_adder_from_half,
    'full adder using half adder':     _raw_template_full_adder_from_half,
    'full adder using half adders':    _raw_template_full_adder_from_half,
    'full adder from half adders':     _raw_template_full_adder_from_half,
    'full adder with half adder':      _raw_template_full_adder_from_half,
    'full adder with half adders':     _raw_template_full_adder_from_half,
    'full adder via half adder':       _raw_template_full_adder_from_half,
    'fa from ha':                      _raw_template_full_adder_from_half,
    'fa using ha':                     _raw_template_full_adder_from_half,
    '4 to 1 mux':                      _raw_template_4to1_mux,
    '4-to-1 mux':                      _raw_template_4to1_mux,
    '4 to 1 multiplexer':              _raw_template_4to1_mux,
    '4to1 mux':                        _raw_template_4to1_mux,
    # NEW: composed from macro blocks (sub-circuits stay visible on canvas)
    '4 bit adder using full adder':    _raw_template_4bit_adder_from_fa,
    '4 bit adder using fa':            _raw_template_4bit_adder_from_fa,
    '4-bit adder using full adder':    _raw_template_4bit_adder_from_fa,
    '4 bit adder from full adder':     _raw_template_4bit_adder_from_fa,
    '8 bit adder using full adder':    _raw_template_8bit_adder_from_fa,
    '8 bit adder using fa':            _raw_template_8bit_adder_from_fa,
    '8-bit adder using full adder':    _raw_template_8bit_adder_from_fa,
    '4 bit register using d flip flop': _raw_template_4bit_register_from_dff,
    '4 bit register using dff':         _raw_template_4bit_register_from_dff,
    '4-bit register using d flip flop': _raw_template_4bit_register_from_dff,
    '8 bit register using d flip flop': _raw_template_8bit_register_from_dff,
    '8 bit register using dff':         _raw_template_8bit_register_from_dff,
    '4 bit shift register using d flip flop': _raw_template_4bit_shift_reg_from_dff,
    '4 bit shift register using dff':         _raw_template_4bit_shift_reg_from_dff,
    'serial in parallel out shift register':  _raw_template_4bit_shift_reg_from_dff,
    '4 bit counter using t flip flop':  _raw_template_4bit_counter_from_tff,
    '4 bit counter using tff':          _raw_template_4bit_counter_from_tff,
    '4-bit counter using t flip flop':  _raw_template_4bit_counter_from_tff,
    'ripple counter using t flip flop': _raw_template_4bit_counter_from_tff,
    '4 bit ring counter':               _raw_template_ring_counter_4bit,
    'ring counter using d flip flop':   _raw_template_ring_counter_4bit,
    'ring counter using dff':           _raw_template_ring_counter_4bit,
    '4 to 1 mux using 2 to 1 mux':      _raw_template_4to1_mux_from_mux2,
    '4 to 1 mux using mux2':            _raw_template_4to1_mux_from_mux2,
    '4-to-1 mux using 2-to-1 mux':      _raw_template_4to1_mux_from_mux2,
    '4 to 1 multiplexer using 2 to 1 multiplexer': _raw_template_4to1_mux_from_mux2,
    '4 bit subtractor using full adder':   _raw_template_subtractor_from_fa,
    '4 bit subtractor using fa':           _raw_template_subtractor_from_fa,
    '4-bit subtractor using full adder':   _raw_template_subtractor_from_fa,
}


# --- Parametric N-bit synthesis ---------------------------------------------

_NBIT_RE = re.compile(
    r'\b(\d{1,3})\s*[-\s]?\s*bit\s+(adder|ripple\s*carry\s*adder|'
    r'subtractor|comparator|equality\s+comparator)\b',
    re.IGNORECASE,
)


def _build_nbit_adder(n: int):
    """Ripple-carry adder for N-bit operands A and B with carry-in Cin."""
    parts = []
    expr_carry = 'Cin'
    for i in range(n):
        a, b = f'A{i}', f'B{i}'
        # Sum_i = Ai ^ Bi ^ C_in_i
        parts.append((f'S{i}', f'{a} ^ {b} ^ ({expr_carry})'))
        # C_out_i = (Ai & Bi) | (C_in_i & (Ai ^ Bi))
        expr_carry = f'({a} & {b}) | (({expr_carry}) & ({a} ^ {b}))'
    parts.append(('Cout', expr_carry))
    return parts


def _build_nbit_equality_comparator(n: int):
    """N-bit A == B comparator: A_eq_B = AND_i ~(A_i ^ B_i)."""
    if n == 1:
        return [('A_eq_B', '~(A0 ^ B0)')]
    inner = ' & '.join(f'~(A{i} ^ B{i})' for i in range(n))
    return [('A_eq_B', inner)]


# --- Natural-language behaviour -> boolean expression -------------------------
#
# Turns plain-English descriptions of a circuit's behaviour into a boolean
# expression (or several, for multi-output specs) that the synthesiser can
# build and simplify. This is what lets the solver answer questions like
# "output is high when both A and B are 1", or
# "3 inputs, 2 outputs; when all are 1 both outputs are 1, when all are 0
#  the first output is 1".

_NL_STOPWORDS = {
    # Note: 'A' deliberately not listed  -  the regex below only matches
    # capital-letter starts, so a capital 'A' is virtually always a
    # signal name (the article 'a' is lowercase).
    'I', 'AND', 'OR', 'NOT', 'THE', 'IS', 'IF', 'WHEN', 'IT', 'AN',
    'TRUE', 'FALSE', 'HIGH', 'LOW', 'OUTPUT', 'OUTPUTS', 'INPUT', 'INPUTS',
    'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'ZERO', 'BOTH', 'ALL', 'ANY',
    'OF', 'ARE', 'BE', 'TO', 'IN', 'ON', 'EXACTLY', 'ONLY', 'EITHER',
    'NEITHER', 'NOR', 'XOR', 'XNOR', 'NAND', 'EQUAL', 'SAME', 'ELSE',
    'THAN', 'THAT', 'THIS', 'WITH', 'FOR', 'BUT', 'WE', 'GOT', 'TAKE',
    'GIVE', 'GIVES', 'GET', 'GETS', 'WHY', 'CANNOT', 'CAN', 'WILL',
    'WHERE', 'MAKE', 'BUILD', 'CIRCUIT', 'GATE', 'GATES', 'CONNECTION',
    'FIRST', 'SECOND', 'THIRD', 'LAST', 'OTHER', 'OTHERS', 'THEN', 'EACH',
    'EVERY', 'SAY', 'SAYS', 'LIKE', 'BEING', 'BEEN', 'HAS', 'HAVE',
}
_NL_VAR_RE = re.compile(r'\b([A-Z][A-Za-z]*\d?)\b')

# Ordinal-to-variable mapping for "first input is on" -> A=1
_ORDINAL_MAP = {
    'first': 'A', 'second': 'B', 'third': 'C',
    'fourth': 'D', 'fifth': 'E',
    '1st': 'A', '2nd': 'B', '3rd': 'C', '4th': 'D', '5th': 'E',
}
_HI_SYNONYMS = {'on', 'high', '1', 'hot', 'active', 'up', 'asserted', 'set'}
_LO_SYNONYMS = {'off', 'low', '0', 'quiet', 'inactive', 'down', 'deasserted',
                'cleared', 'silent'}


def _ordinal_row_spec(text):
    """
    Parse specs like "first input is on but second is off" -> {A:1, B:0}.
    Returns (expression, name, desc) or None.
    """
    assigns = {}
    for m in re.finditer(
            r'\b(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)\b'
            r'\s*(?:input|line|signal)?\s*'
            r'\b(?:is|=|equals?|goes?|becomes?)\b\s*'
            r'\b(\w+)\b',
            text, re.IGNORECASE):
        ordinal = m.group(1).lower()
        val_word = m.group(2).lower()
        var = _ORDINAL_MAP.get(ordinal)
        if var is None:
            continue
        if val_word in _HI_SYNONYMS:
            assigns[var] = 1
        elif val_word in _LO_SYNONYMS:
            assigns[var] = 0
    if not assigns:
        return None
    n = max({'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5}[v] for v in assigns)
    vs = ['A', 'B', 'C', 'D', 'E'][:n]
    lits = []
    for v in vs:
        val = assigns.get(v)
        if val == 1:
            lits.append(v)
        elif val == 0:
            lits.append(f'~{v}')
        # unspecified -> ignore (don't add to expression)
    if not lits:
        return None
    expr = ' & '.join(lits)
    specified = {v: assigns[v] for v in assigns}
    desc = f"Output is high when: {', '.join(f'{v}={specified[v]}' for v in sorted(specified))}."
    return (expr, 'ordinal spec', desc)

# Names that are conventionally output labels, never inputs.
_OUTPUT_LIKE_NAMES = {f'Y{i}' for i in range(10)} | {
    'Y', 'OUT', 'OUT1', 'OUT2', 'OUT3', 'OUT4',
    'F', 'F1', 'F2', 'F3', 'F4',
}


def _nl_detect_vars(text):
    """Pull likely signal names (A, B, Cin, S0, ...) out of free text, in order."""
    found = []
    for tok in _NL_VAR_RE.findall(text):
        u = tok.upper()
        if u in _NL_STOPWORDS:
            continue
        if u in _OUTPUT_LIKE_NAMES:
            continue
        if tok not in found:
            found.append(tok)
    return found


def _nl_join(op, vs):
    return (' ' + op + ' ').join(vs)


def _logic_from_phrasing(text):
    """English description -> (expression, name, description) or None.

    Public entry point. Handles output-polarity (if the user wrote
    "then output is 0", the result of the inner matcher is inverted) then
    delegates to the raw matcher.
    """
    flip = False
    m = re.search(
        r"\bthen\s+(?:output|out|y\d*|z\d*)\s+(?:is|=|equals?|gives?|becomes?)?\s*"
        r"(?P<val>0|zero|low|false|off)\b",
        text, re.IGNORECASE)
    inner_text = text
    if m:
        flip = m.group('val').lower() in ('0', 'zero', 'low', 'false', 'off')
        inner_text = (text[:m.start()] + ' ' + text[m.end():]).strip()

    res = _logic_from_phrasing_raw(inner_text)
    if not flip or res is None:
        return res
    expr, name, desc = res
    if expr.startswith('~(') and expr.endswith(')'):
        new_expr = expr[2:-1]
    else:
        new_expr = f'~({expr})'
    new_name = name[4:] if name.startswith('not ') else f'not {name}'
    new_desc = (desc.replace('Output is high', 'Output is LOW')
                    .replace('Output is the inverse', 'Output is')
                + ' (Inverted — spec says "output is 0".)')
    return (new_expr, new_name, new_desc)


def _logic_from_phrasing_raw(text):
    """Inner matcher — does NOT handle output polarity; see _logic_from_phrasing."""
    t = ' ' + text.lower().strip() + ' '

    # If the text says "three inputs"/"four lines", expand vs to that size.
    n_explicit = _count_inputs_in_text(text)
    detected = _nl_detect_vars(text)
    if n_explicit and n_explicit > len(detected):
        vs = (['A', 'B', 'C', 'D', 'E'])[:n_explicit]
    else:
        vs = detected or ['A', 'B']

    # ── Generic threshold: "at least K of N inputs are 1" ────────────────────
    # Enumerate all minterms with popcount in [K, N] and build the SOP.
    m_thr = re.search(
        r'\b(?:at\s+least|>=)\s+(?P<k>\d+)\s+(?:of\s+(?P<n>\d+)\s+)?(?:inputs?|of\s+them|of\s+the\s+inputs?)\s+(?:are|is)\s+(?:1|high|on)\b',
        t, re.IGNORECASE)
    if m_thr:
        k = int(m_thr.group('k'))
        n = int(m_thr.group('n')) if m_thr.group('n') else (n_explicit or len(vs))
        n = max(n, k, 2)
        vs_use = (['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'])[:n]
        # Build the SOP: every minterm with popcount >= k.
        terms = []
        for mask in range(1 << n):
            if bin(mask).count('1') < k:
                continue
            term_lits = []
            for i, v in enumerate(vs_use):
                bit = (mask >> (n - 1 - i)) & 1
                term_lits.append(v if bit else f'~{v}')
            terms.append('(' + ' & '.join(term_lits) + ')')
        if terms:
            return (' | '.join(terms),
                    f'at least {k} of {n}',
                    f'Output is high when at least {k} of {n} inputs are 1.')

    # ── Generic threshold: "exactly K of N inputs are 1" ─────────────────────
    m_exact = re.search(
        r'\bexactly\s+(?P<k>\d+)\s+(?:of\s+(?P<n>\d+)\s+)?(?:inputs?|of\s+them)\s+(?:are|is)\s+(?:1|high|on)\b',
        t, re.IGNORECASE)
    if m_exact:
        k = int(m_exact.group('k'))
        n = int(m_exact.group('n')) if m_exact.group('n') else (n_explicit or len(vs))
        n = max(n, k, 2)
        vs_use = (['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'])[:n]
        terms = []
        for mask in range(1 << n):
            if bin(mask).count('1') != k:
                continue
            term_lits = []
            for i, v in enumerate(vs_use):
                bit = (mask >> (n - 1 - i)) & 1
                term_lits.append(v if bit else f'~{v}')
            terms.append('(' + ' & '.join(term_lits) + ')')
        if terms:
            return (' | '.join(terms),
                    f'exactly {k} of {n}',
                    f'Output is high when exactly {k} of {n} inputs are 1.')

    # Normalise variable-laden phrases so substring matches work:
    #   "both A and B are 0" -> "both are 0"
    #   "A and B are both high" -> "are both high"
    #   "all of A B C are low" -> "all are low"
    # Use a generic single-letter/short-name strip so it works on both
    # original case AND recursive lowercased calls.
    t_norm = t
    # Strip "X and Y", "X, Y, Z" sequences of single letters or short tokens
    t_norm = re.sub(
        r'\b([a-z]\w{0,2})\b(\s*(?:,|and|or)\s*\b[a-z]\w{0,2}\b)+',
        ' ', t_norm)
    if detected:
        var_re = '|'.join(re.escape(v.lower()) for v in detected)
        t_norm = re.sub(
            rf'\b(?:{var_re})\b(?:\s*(?:,|and|or)\s*\b(?:{var_re})\b)*',
            ' ', t_norm)
    t_norm = re.sub(r'\s+', ' ', t_norm)

    def has(*words):
        return any(w in t or w in t_norm for w in words)

    # -- "X is HIGH/LOW and Y is HIGH/LOW"  -  literal conjunction spec -----
    # Detect a sequence of "var is state" pairs joined by and/or/commas;
    # build the AND of their literals as the expression. SKIP this if the
    # text contains an inversion context  -  those need to recurse first so
    # the outer inversion wraps the result with ~().
    state_re = (r'(?:high|low|on|off|set|cleared|1|0|hot|quiet|active|'
                r'inactive|asserted|deasserted|true|false|up|down)')
    has_inversion_context = any(_is_inversion_context(text))
    word_pairs = re.findall(
        rf'\b([A-Za-z]\w*)\s+(?:is|=|equals?|goes?|becomes?)\s+({state_re})\b',
        text, re.IGNORECASE)
    if len(word_pairs) >= 2 and not has_inversion_context:
        hi_set = {'high', 'on', 'set', '1', 'hot', 'active', 'asserted',
                  'true', 'up'}
        valid = []
        for vname, state in word_pairs:
            u = vname.upper()
            if u in _NL_STOPWORDS or u in _OUTPUT_LIKE_NAMES:
                continue
            valid.append((u, 1 if state.lower() in hi_set else 0))
        seen = set()
        unique = []
        for v, s in valid:
            if v in seen: continue
            seen.add(v)
            unique.append((v, s))
        if len(unique) >= 2:
            lits = [v if s == 1 else f'~{v}' for v, s in unique]
            expr = ' & '.join(lits)
            desc = ('Output is high when ' +
                    ', '.join(f'{v}={s}' for v, s in unique) + '.')
            return (expr, 'word-style row', desc)

    # -- "Opposite of X" / "inverse of X" ---------------------------------
    for base_name, base_expr_fn in [
        ('and',  lambda v: _nl_join('&', v)),
        ('or',   lambda v: _nl_join('|', v)),
        ('xor',  lambda v: _nl_join('^', v)),
    ]:
        if re.search(rf'\b(opposite|inverse|invert|complement|negate|not|negation)'
                     rf'\s+of\s+{base_name}\b', t):
            expr = '~(' + base_expr_fn(vs) + ')'
            name = f'N{base_name.upper()}'
            return (expr, name,
                    f'Output is the opposite of {base_name.upper()}  -  '
                    f'high when {base_name.upper()} would be low.')

    # -- Negated output / "except when" / "unless"  -  flip the condition --
    # "output is 0 only when X" / "output stays low when X" / "NOT output 1 when X"
    # "output is 1 except when X" / "output is 1 unless X"
    # All mean: output = ~(condition).
    inversion_patterns = [
        (r'\b(?:not\s+output|never\s+(?:output|give|produce))\b\s*1?\b'
         r'.{0,15}?(?:when|if)\b(.+)', 'inverted condition (NOT output)'),
        (r'\b(?:output|give|produce|emit|return)s?\s+(?:is\s+|a\s+)?0\b'
         r'.{0,15}?(?:only\s+)?(?:when|if)\b(.+)', 'gives 0 when'),
        (r'\boutput\s+(?:stays?|remains?|goes)\s+(?:low|0|off)\b.{0,15}?'
         r'(?:only\s+)?(?:when|if)\b(.+)', 'output stays low when'),
        (r'\bthe\s+output\s+(?:stays?|is)\s+(?:low|0|off)\b.{0,15}?'
         r'(?:only\s+)?(?:when|if)\b(.+)', 'the output stays low when'),
        (r'\bexcept\s+(?:when|if)\b(.+)', 'except when'),
        (r'\bunless\b(.+)', 'unless'),
        (r'\bresult\s+is\s+0\b.{0,15}?(?:when|if|unless)\b(.+)', 'result 0 when'),
    ]
    for pat, label in inversion_patterns:
        # Search in original-case text so the recursive call still sees
        # uppercase variable names (otherwise "P Q R" gets lowercased and
        # never matches _nl_detect_vars).
        nm = re.search(pat, text, re.IGNORECASE)
        if nm:
            cond_text = nm.group(1)
            inner = _logic_from_phrasing(cond_text)
            if inner:
                inner_expr = inner[0]
                return (f'~({inner_expr})', f'inverted ({label})',
                        f'Output is 1 EXCEPT when {inner[2].lower()}')

    # -- "Regardless of X" / "independent of X" -> remove X ---------------
    regardless = re.search(
        r'\b(?:regardless|independent)\s+of\s+(\w+)', t, re.IGNORECASE)
    if regardless:
        ignore = regardless.group(1).upper()
        reduced_vs = [v for v in vs if v.upper() != ignore]
        if reduced_vs:
            inner_text = re.sub(
                r'\b(?:regardless|independent)\s+of\s+\w+', '',
                text, flags=re.IGNORECASE).strip()
            # Re-detect vars in the stripped text
            vs = reduced_vs  # noqa: F841  -  used by has() closures
            inner = _logic_from_phrasing(inner_text)
            if inner:
                return inner

    # -- "A implies B" / "only if A then B" -> ~A | B ---------------------
    if has('implies', 'implication', 'if and only if', 'iff ', ' iff$'):
        # "if and only if" -> XNOR (biconditional)
        if has('if and only if', 'iff ', ' iff$'):
            a, b = (vs + ['A', 'B'])[:2]
            return (f'({a} & {b}) | (~{a} & ~{b})', 'xnor',
                    f'Output is high when {a} and {b} are the same (biconditional).')
        # "A implies B" -> ~A | B
        a, b = (vs + ['A', 'B'])[:2]
        return (f'~{a} | {b}', 'implication',
                f'Output is high unless {a} is 1 and {b} is 0.')

    # -- Hot / quiet / active / up / down synonyms for 1/0 ---------------
    # Apply to both t and the var-stripped t_norm without overwriting either.
    for warm in ('hot', 'active', 'up', 'asserted', 'set', 'enabled'):
        t      = t.replace(f' {warm} ', ' high ')
        t_norm = t_norm.replace(f' {warm} ', ' high ')
    for cold in ('quiet', 'silent', 'inactive', 'down', 'deasserted',
                 'cleared', 'disabled'):
        t      = t.replace(f' {cold} ', ' low ')
        t_norm = t_norm.replace(f' {cold} ', ' low ')

    # -- "left half matches right half" (4-input pairwise equality) ------
    if (has('left', 'first half', 'first two', 'first pair')
            and has('right', 'second half', 'last two', 'second pair', 'other two')
            and has('match', 'equal', 'same', 'agree', 'identical')):
        n_in = max(4, len(vs))
        if n_in % 2 == 0:
            vs_eff = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'][:n_in]
            half = n_in // 2
            left  = vs_eff[:half]
            right = vs_eff[half:]
            # Build (L0 XNOR R0) AND (L1 XNOR R1) AND ...
            xnor_terms = []
            for l, r in zip(left, right):
                xnor_terms.append(f'(({l} & {r}) | (~{l} & ~{r}))')
            expr = ' & '.join(xnor_terms)
            return (expr, 'halves match',
                    f'Output is high when the left half '
                    f'({", ".join(left)}) matches the right half '
                    f'({", ".join(right)}).')

    # -- "all N inputs match" / "all are the same" (3+ inputs) -----------
    if has('all match', 'all are the same', 'all equal', 'all the same',
           'every input matches', 'all inputs match'):
        n_in = max(3, len(vs))
        vs_eff = ['A', 'B', 'C', 'D', 'E'][:n_in]
        # All same = all 1 OR all 0
        all_hi = ' & '.join(vs_eff)
        all_lo = ' & '.join(f'~{v}' for v in vs_eff)
        return (f'({all_hi}) | ({all_lo})', 'all match',
                f'Output is high when all {n_in} inputs share the same value.')

    # -- "bigger/larger of A and B" / "max of A,B" -----------------------
    # For 1-bit inputs, max(A,B) = A | B  (and min(A,B) = A & B).
    if has('bigger of', 'larger of', 'greater of', 'maximum of',
           ' max of ', 'whichever is larger', 'whichever is bigger'):
        a, b = (vs + ['A', 'B'])[:2]
        return (f'{a} | {b}', 'max',
                f'For 1-bit inputs, the larger of {a} and {b} equals {a} OR {b}.')
    if has('smaller of', 'lesser of', 'minimum of', ' min of ',
           'whichever is smaller', 'whichever is lesser'):
        a, b = (vs + ['A', 'B'])[:2]
        return (f'{a} & {b}', 'min',
                f'For 1-bit inputs, the smaller of {a} and {b} equals {a} AND {b}.')

    # -- "more than half" / "strict majority" (3+ inputs) ----------------
    if has('more than half', 'strict majority', 'most of', 'majority of'):
        n_in = max(3, len(vs))
        vs_eff = (['A', 'B', 'C', 'D', 'E'])[:n_in]
        threshold = n_in // 2 + 1
        # Enumerate every combination of `threshold` or more high inputs.
        from itertools import combinations
        terms = []
        for k in range(threshold, n_in + 1):
            for combo in combinations(range(n_in), k):
                lits = [vs_eff[i] if i in combo else f'~{vs_eff[i]}'
                        for i in range(n_in)]
                terms.append('(' + ' & '.join(lits) + ')')
        return (' | '.join(terms), 'majority',
                f'Output high when more than half ({threshold}+) of '
                f'{n_in} inputs are 1.')

    # -- XNOR / equality (2-input default) --------------------------------
    if has(' equal', ' same ', ' match', ' equivalent', ' identical',
           ' xnor', 'agree', 'both same', 'both equal'):
        a, b = (vs + ['A', 'B'])[:2]
        return (f'({a} & {b}) | (~{a} & ~{b})', 'equality',
                f'Output is high when {a} and {b} are equal.')

    # -- Special: "ORDINAL input differs from the others" -----------------
    # E.g. "middle input differs from the other two" (3-input)
    #      "first input differs from the rest" (N-input)
    ordinal_differ = re.search(
        r'\b(first|second|third|fourth|middle|last)\s+input\b'
        r'.{0,30}?\b(?:differs?|different|differ|distinct)\b'
        r'.{0,30}?\b(?:other|others|rest)\b', t)
    if ordinal_differ:
        ord_word = ordinal_differ.group(1)
        n_in = max(3, len(vs)) if len(vs) >= 3 else 3
        vs_eff = ['A', 'B', 'C', 'D', 'E'][:n_in]
        idx_map = {'first': 0, 'second': 1, 'third': 2, 'fourth': 3,
                   'last': n_in - 1, 'middle': n_in // 2}
        target_idx = idx_map.get(ord_word, n_in // 2)
        # Target input differs from EVERY other input.
        # That means all others share one value, target has the opposite.
        # Two minterms: all others=0 target=1, all others=1 target=0.
        minterms = []
        for tv in (0, 1):
            bits = [tv if i == target_idx else (1 - tv) for i in range(n_in)]
            minterms.append(int(''.join(str(b) for b in bits), 2))
        terms = []
        for mt in minterms:
            bits = format(mt, f'0{n_in}b')
            lits = [v if b == '1' else f'~{v}' for v, b in zip(vs_eff, bits)]
            terms.append('(' + ' & '.join(lits) + ')')
        return (' | '.join(terms), f'{ord_word} differs',
                f'Output is high when the {ord_word} input differs from all '
                f'others ({n_in} inputs total).')

    # -- XOR / difference / "exactly one" ---------------------------------
    if has('exactly one', 'only one', ' differ', 'different', 'not equal',
           'one but not both', ' xor ', 'odd number', ' parity', 'odd one',
           'disagree', 'mismatch'):
        # "exactly one of three/N lines" -> need N variables
        n_explicit = _count_inputs_in_text(text)
        if n_explicit and n_explicit > len(vs):
            vs = (['A','B','C','D','E'])[:n_explicit]
        # For "exactly one of N" where N>2 we need a counting SOP,
        # not XOR (XOR is only correct for 2 inputs).
        if len(vs) > 2 and has('exactly one', 'only one'):
            n_in = len(vs)
            terms = []
            for i in range(n_in):
                lits = [vs[j] if j==i else f'~{vs[j]}' for j in range(n_in)]
                terms.append('(' + ' & '.join(lits) + ')')
            expr = ' | '.join(terms)
            return (expr, 'exactly one',
                    f'Output is high when exactly one of {n_in} inputs is high.')
        return (_nl_join('^', vs), 'xor',
                f'Output is high when inputs differ.')

    # -- EVEN parity -------------------------------------------------------
    if has('even number', 'even parity'):
        return ('~(' + _nl_join('^', vs) + ')', 'even parity',
                'Output is high when an even number of inputs are high.')

    # -- Majority ---------------------------------------------------------
    if has('majority', 'most of', 'at least two', 'two of three', '2 of 3',
           'two or more', ' vote', ' voting'):
        a, b, c = (vs + ['A', 'B', 'C'])[:3]
        return (f'({a} & {b}) | ({a} & {c}) | ({b} & {c})', 'majority',
                f'Output is high when at least two of {a}, {b}, {c} are high.')

    # -- More than one (= majority for 3 inputs, or ≥2) -------------------
    if has('more than one', 'more than 1', 'at least two are'):
        if len(vs) >= 3:
            a, b, c = vs[:3]
            return (f'({a} & {b}) | ({a} & {c}) | ({b} & {c})', '>1 high',
                    'Output is high when more than one input is high.')
        a, b = (vs + ['A', 'B'])[:2]
        return (f'{a} & {b}', 'and',
                f'Output is high when more than one (both) of {a}, {b} are high.')

    # -- NAND -------------------------------------------------------------
    if has('not both', ' nand ', 'not all', 'cannot both'):
        return ('~(' + _nl_join('&', vs) + ')', 'nand',
                'Output is high unless all inputs are high.')

    # -- NOR / "all quiet/low/off/zero" -----------------------------------
    if has('neither', ' nor ', 'none of', 'all are low', 'all low',
           'all are 0', 'all zero', 'both are low', 'both are off',
           'both are quiet', 'both quiet', 'both off', 'both low',
           'both are 0', 'both 0', 'all 0', 'all are zero',
           'all quiet', 'all off', 'both silent', 'all silent',
           'signals are quiet', 'signals are low', 'signals are off',
           'inputs are quiet', 'inputs are low', 'inputs are off'):
        return ('~(' + _nl_join('|', vs) + ')', 'nor',
                'Output is high only when every input is low.')

    # -- AND / all-high ---------------------------------------------------
    # Put this AFTER NOR so "both are low" doesn't match "both"->AND
    if (has('both are high', 'both are on', 'both are 1', 'both are hot',
            'all are high', 'all high', 'all are 1', 'all 1',
            'every input is high', 'all inputs are high',
            'if and only if every', 'both inputs are on',
            'both inputs are high', 'both inputs are 1',
            'all inputs are on', 'all are hot', 'both 1', 'all are on')
            or re.search(r'\bboth\b.{0,20}\b(1|high|on|hot)\b', t)
            or re.search(r'\bboth\b.{0,20}\b(1|high|on|hot)\b', t_norm)
            # "all N inputs/lines/signals are high/1/on"
            or re.search(
                r'\ball\b.{0,15}\b(?:inputs?|signals?|lines?|bits?)\s+'
                r'are\s+(?:high|on|1|hot|active)\b', t)):
        return (_nl_join('&', vs), 'and',
                f'Output is high only when all of {", ".join(vs)} are high.')

    # -- OR / at-least-one ------------------------------------------------
    if has('at least one', 'either', 'any of', 'one or more', 'any input',
           'at least 1'):
        return (_nl_join('|', vs), 'or',
                f'Output is high when at least one input is high.')

    # -- NOT / invert -----------------------------------------------------
    # The comment promised "only match when there is exactly one variable"
    # but the code didn't enforce it — phrasings like "A AND NOT B" or
    # "(A or B) and (not C)" matched here and produced `~A`, dropping the
    # other operands. Now: only short-circuit to NOT when there is exactly
    # one detected variable AND no binary operators ("and"/"or"/"xor") in
    # the text. Otherwise fall through and let the boolean expression
    # parser (further down) handle multi-operand expressions correctly.
    explicit_invert = ('invert' in t or 'inverse' in t or 'complement' in t
                       or 'negate' in t or 'negation' in t)
    has_not_word    = bool(re.search(r'\bnot\s+\w+\b', t))
    has_other_op    = bool(re.search(r'\b(and|or|xor|xnor|nand|nor|&|\||\^)\b', t))
    if (explicit_invert or has_not_word) and len(vs) == 1 and not has_other_op:
        a = vs[0]
        return (f'~{a}', 'not', f'Output is the inverse of {a}.')

    return None


_NL_BIN_GROUP_RE = re.compile(r'\b([01]{2,})\b')


def _count_constraint_from_text(text):
    """
    Recognise counting constraints:
        "exactly N inputs are high"
        "at least N inputs are 1"
        "at most N are on"
        "more than N are high"
        "fewer than N are 1" / "less than N are high"
    Returns (expression, name, description) or None.
    """
    t = text.lower()
    # Normalise synonyms first
    for w in ('hot', 'active', 'up', 'asserted', 'set', 'enabled'):
        t = re.sub(rf'\b{w}\b', 'high', t)
    # The body between the count word ("two") and the "are/is high" can be
    #   - empty:                "exactly one is 1"
    #   - a noun:               "exactly one input is 1"
    #   - "of them":            "exactly one of them is 1"
    #   - "of N nouns":         "at least two of three lines are high"
    #   - "of A B C":           "exactly one of A B C is 1"
    # so we allow any short non-greedy span before the "are/is/=" closer.
    m = re.search(
        r'\b(exactly|at\s+least|at\s+most|more\s+than|fewer\s+than|less\s+than|'
        r'no\s+more\s+than)\s+'
        r'(\d+|one|two|three|four|five|six)\b'
        r'(?:\s+.{0,50}?)?'
        r'\s*(?:are|is|=)\s*(?:1|high|on|true|active)\b', t)
    if not m:
        return None
    quant = re.sub(r'\s+', ' ', m.group(1))
    n_val = _word_count(m.group(2))
    if n_val is None or not (0 <= n_val <= 6):
        return None

    # Number of inputs: look for explicit "of N inputs/signals/lines"
    # ("at least three of four lines"), else detected vars, else default.
    of_n = re.search(
        r'\bof\s+(\d+|one|two|three|four|five|six|seven|eight)\s+'
        r'(?:inputs?|lines?|signals?|bits?|variables?)', t)
    if of_n:
        n_in = _word_count(of_n.group(1)) or (n_val + 1)
    else:
        vs = _nl_detect_vars(text)
        if vs:
            n_in = len(vs)
        else:
            n_in = max(n_val + 1, 3)
    n_in = max(1, min(5, n_in))
    vs = _nl_detect_vars(text)

    def keep(c):
        if quant == 'exactly':           return c == n_val
        if quant == 'at least':          return c >= n_val
        if quant == 'at most':           return c <= n_val
        if quant == 'no more than':      return c <= n_val
        if quant == 'more than':         return c >  n_val
        if quant in ('fewer than', 'less than'): return c < n_val
        return False

    minterms = [i for i in range(1 << n_in) if keep(bin(i).count('1'))]
    if not minterms:
        return None

    vs = (vs + ['A', 'B', 'C', 'D', 'E'])[:n_in]
    if len(minterms) == (1 << n_in):
        expr = '1'
    else:
        terms = []
        for mt in minterms:
            bits = format(mt, f'0{n_in}b')
            lits = [v if b == '1' else f'~{v}' for v, b in zip(vs, bits)]
            terms.append('(' + ' & '.join(lits) + ')')
        expr = ' | '.join(terms)
    return (expr, f'{quant} {n_val}',
            f"Output is high when {quant} {n_val} of {n_in} inputs are 1.")


def _is_inversion_context(text):
    """Yield True if `text` contains inversion keywords that would flip
    the meaning of a row spec (so we shouldn't add it as output=1)."""
    t = text.lower()
    for kw in ('except when', 'except if', 'unless', 'stays low when',
               'stays low only when', 'output is 0 when',
               'output 0 when', 'never output', 'not output',
               'gives 0 when', 'give 0 when'):
        if kw in t:
            yield True
    yield False


def _consume_row(snippet, out_bit, rows):
    """Helper: extract assignment pairs from a snippet and append a row."""
    assigns = re.findall(r'\b([A-Za-z]\w*)\s*=\s*([01])', snippet)
    if not assigns:
        return
    names = list(dict.fromkeys(a[0].upper() for a in assigns))
    if not (1 <= len(names) <= 5):
        return
    names_sorted = sorted(names)
    values = {a[0].upper(): int(a[1]) for a in assigns}
    if set(values) != set(names_sorted):
        return
    bits = ''.join(str(values[v]) for v in names_sorted)
    rows.append((len(names_sorted), int(bits, 2), out_bit))


def _row_spec_from_text(text):
    """
    Parse explicit row-by-row truth-table specifications like:
        "input 1 gives 0 and input 0 gives 1"
        "when A=0 B=1 output is 1, when A=1 B=0 output is 1"
        "for input 11 the output is 1, for 00 it is 1"
    Returns (expression, name, desc) or None.

    Strategy: find every (input_pattern -> output_value) pair in the text and
    build the partial truth table. Unspecified rows default to 0.
    """
    # Skip if the text is plainly a counting constraint ("exactly one of",
    # "at least two", "more than 1")  -  those have their own dedicated
    # parser that produces correct one-hot/threshold expressions.
    # Without this guard, phrases like "exactly one of A B C is 1" hit our
    # "input N gives M" regex and return garbage like "(A)".
    if re.search(r'\b(?:exactly|at\s+least|at\s+most|more\s+than|'
                 r'fewer\s+than|less\s+than|no\s+more\s+than|'
                 r'all|none|any|some|every|majority|minority)\b'
                 r'.*?\b(?:of\b|input|inputs)',
                 text, re.IGNORECASE):
        return None

    # Skip if conditions look like a boolean expression (bare "A or B",
    # "A and B and C", "neither A nor B") with no explicit "var=value"
    # assignments. Those should go to the boolean parser / _logic_from_phrasing.
    has_assignment = bool(re.search(r'\b[A-Za-z]\w*\s*=\s*[01]\b', text))
    boolean_op_between_vars = bool(re.search(
        r'\b[A-Za-z]\w*\s+(?:and|or|xor|nand|nor|xnor)\s+[A-Za-z]\w*\b',
        text, re.IGNORECASE))
    if boolean_op_between_vars and not has_assignment:
        return None

    rows = []           # list of (n_inputs, minterm_index, output_bit)

    # Trim trailing "otherwise/else K" / ", else K" / "else output is 0"
    text = re.sub(
        r',?\s*(?:otherwise|else)\s+(?:output\s+is\s+)?[01]\b\.?',
        '', text, flags=re.IGNORECASE)
    # Trim "if and only if" header  -  it means the spec IS the truth table
    text = re.sub(r'\bif\s+and\s+only\s+if\b', '', text, flags=re.IGNORECASE)

    # 1) "input X gives Y" / "input X is Y" / "input X = Y"  -  single input.
    for m in re.finditer(
            r'\binput\b(?:\s*(?:is|equals?))?\s*([01])\b'
            r'.{0,20}?\b(?:gives?|is|equals?|outputs?|produces?|->|->)\s*'
            r'([01])\b', text, re.IGNORECASE):
        inp = int(m.group(1))
        out = int(m.group(2))
        rows.append((1, inp, out))

    # 2a) Assignment-first:  "A=0 B=1 ... output is 1"
    for m in re.finditer(
            r'(?:\b[A-Za-z]\w*\s*=\s*[01]\b(?:\s*[,]?\s*)?){1,5}'
            r'.{0,30}?\boutput\b\s*(?:is|=|equals?|gives?|becomes?)\s*([01])\b',
            text, re.IGNORECASE):
        _consume_row(m.group(0), int(m.group(1)), rows)

    # 2b) Output-first: "output is K when COND" with possibly OR-ed cond groups
    #     "output is 1 when A=0 B=0 or when A=1 B=1"
    #     "Y is 1 when A=1 and B=0"           <- single-letter output name
    #     "the output should be on only when A=0 B=1 C=0 or A=1 B=1 C=1"
    #
    #  Output-name alternation accepts both the literal words AND common
    #  single-letter / short output identifiers (Y, Q, Z, F, Out). We tested
    #  the case "Y is 1 when A=1 and B=0"  -  previously it was missed and we
    #  fell through to the ML truth-table model which guessed wrong.
    for m in re.finditer(
            r'\b(?:output|result|it|signal|out|y|q|z|f)\b'
            r'\s*(?:should\s+be\s+)?(?:is|=|equals?|gives?|becomes?|goes?\s+)'
            r'\s*(?:on|off|high|low|[01])\b'
            r'.{0,20}?(?:only\s+)?(?:when|if|for)\b\s*(.+?)(?=\.\s*$|\s*$)',
            text, re.IGNORECASE):
        match_text = m.group(0)
        ob = re.search(r'\b(on|high|1)\b', match_text.split('when')[0], re.IGNORECASE)
        out_bit = 1 if ob else 0
        body = m.group(1)
        for grp in re.split(r'\s+or\s+(?:when\s+)?', body, flags=re.IGNORECASE):
            _consume_row(grp, out_bit, rows)

    # 2b-extra) Bare "only when A=0 B=1 C=0 or A=1 B=1 C=1" with no explicit output word
    #   -  infer output=1 for each OR-group of assignments
    for m in re.finditer(
            r'\bonly\s+when\b\s*(.+?)(?=\.\s*$|\s*$)',
            text, re.IGNORECASE):
        body = m.group(1)
        for grp in re.split(r'\s+or\s+(?:when\s+)?', body, flags=re.IGNORECASE):
            _consume_row(grp, 1, rows)

    # 2c) Verb-first: "give 1 when A=0 and B=1" / "produce 1 when ..."
    for m in re.finditer(
            r'\b(?:give|produce|emit|fire|return|output)s?\b\s*([01])\b'
            r'.{0,15}?(?:when|if|for)\b\s*(.+?)(?=\.\s*$|\s*$)',
            text, re.IGNORECASE):
        out_bit = int(m.group(1))
        body = m.group(2)
        for grp in re.split(r'\s+or\s+(?:when\s+)?|\s*,\s*(?:when\s+)?',
                            body, flags=re.IGNORECASE):
            _consume_row(grp, out_bit, rows)

    # 3a) "for input 011 the output is 1" / "for 011 it is 1"
    for m in re.finditer(
            r'\b(?:for|input)\s*([01]{2,5})\b.{0,25}?'
            r'\b(?:is|gives?|outputs?|equals?|becomes?)\s*([01])\b',
            text, re.IGNORECASE):
        pat = m.group(1)
        out = int(m.group(2))
        rows.append((len(pat), int(pat, 2), out))

    # 3b) "output is K for input PAT" / "output is K for PAT"
    for m in re.finditer(
            r'\boutput\b\s*(?:is|=|equals?|gives?|becomes?)\s*([01])\b'
            r'\s*(?:for|when|on|at)\s+(?:input\s+)?([01]{2,5})\b',
            text, re.IGNORECASE):
        out = int(m.group(1))
        pat = m.group(2)
        rows.append((len(pat), int(pat, 2), out))

    # 4) Word-style assignments: "A is set and B is cleared", "X is high, Y is low"
    #    Extract var->state pairs using synonym words.
    state_re = (r'(?:high|low|on|off|set|cleared|1|0|hot|quiet|active|inactive|'
                r'asserted|deasserted|true|false|up|down)')
    word_rows = re.findall(
        rf'\b([A-Za-z]\w*)\s+(?:is|=|equals?|goes?|becomes?)\s+({state_re})\b',
        text, re.IGNORECASE)
    if word_rows:
        hi_set = {'high', 'on', 'set', '1', 'hot', 'active', 'asserted',
                  'true', 'up'}
        lo_set = {'low', 'off', 'cleared', '0', 'quiet', 'inactive',
                  'deasserted', 'false', 'down'}
        assigns = {}
        for vname, state in word_rows:
            u = vname.upper()
            if u in _NL_STOPWORDS or u in _OUTPUT_LIKE_NAMES:
                continue
            if state.lower() in hi_set:   assigns[u] = 1
            elif state.lower() in lo_set: assigns[u] = 0
        # Only build a row if we got at least 1 valid assignment AND the
        # output-bit is known. Output-1 unless inverted upstream.
        if assigns and not any(_is_inversion_context(text)):
            names = sorted(assigns)
            bits = ''.join(str(assigns[v]) for v in names)
            if 1 <= len(names) <= 5:
                rows.append((len(names), int(bits, 2), 1))

    if not rows:
        return None

    # All rows must agree on n_inputs.
    n_in_vals = {r[0] for r in rows}
    if len(n_in_vals) != 1:
        return None
    n_in = n_in_vals.pop()

    # Build a partial truth table  -  only the explicitly mentioned rows.
    on_rows = sorted({mt for (_, mt, out) in rows if out == 1})
    explicit = {(mt, out) for (_, mt, out) in rows}
    # Sanity: must have at least one "1" row, otherwise the answer is just
    # the constant 0 which is rarely what the user means.
    if not on_rows:
        return None

    vs = ['A', 'B', 'C', 'D', 'E'][:n_in]
    if not on_rows:
        expr = '0'
    elif len(on_rows) == (1 << n_in):
        expr = '1'
    else:
        terms = []
        for mt in on_rows:
            bits = format(mt, f'0{n_in}b')
            lits = [v if b == '1' else f'~{v}' for v, b in zip(vs, bits)]
            terms.append('(' + ' & '.join(lits) + ')')
        expr = ' | '.join(terms)

    n_explicit = len({mt for (_, mt, _) in rows})
    coverage = (f"({n_explicit} of {1 << n_in} input rows specified)"
                if n_explicit < (1 << n_in) else "(full truth table given)")
    desc = (f"Output is 1 for input rows: "
            f"{', '.join(format(mt, f'0{n_in}b') for mt in on_rows)} "
            f"{coverage}.")
    return (expr, 'custom truth table', desc)


def _value_set_from_text(text):
    """
    Parse phrases that name decimal values an input number takes, e.g.:
      "ABC reads as 5 or 6 in binary"
      "the input number is 3 or 5 or 7"
      "when ABCD equals 1, 4 or 9"
      "treat ABCD as 4 bit binary and output high when value is prime"
    Returns (expression, name, desc) or None.
    """
    t = text.lower()

    # Strip "<Y|output> (is|=) 1 when ..." prefix so the "1" doesn't get
    # treated as a value the input number takes.
    t = re.sub(
        r'\b(?:y|output|result|out)\s*(?:is|=|equals?)\s*1\b\s*(?:when|if)?\s*',
        '', t)

    # Decide input width and variable names.
    name_match = re.search(r'\b([A-D]{2,5})\b\s+(?:reads?|equals?|is|=)', text)
    if name_match:
        vs = list(name_match.group(1))         # 'ABC' -> ['A','B','C']
    else:
        # Look for "treat ABCD as 4 bit binary" / "ABCD as 4-bit binary"
        m2 = re.search(r'\b([A-D]{2,5})\b\s+as\s+\d?\s*[-]?bit\s+binary', text)
        if m2:
            vs = list(m2.group(1))
        else:
            return None
    width = len(vs)
    if not (2 <= width <= 5):
        return None
    max_val = (1 << width) - 1

    # Gather candidate values.
    values = set()
    label = None
    if re.search(r'\bprime\b', t):
        primes = [v for v in range(2, max_val + 1)
                  if all(v % d for d in range(2, int(v**0.5) + 1))]
        values.update(primes)
        label = 'prime values'
    if re.search(r'\b(?:even|divisible\s+by\s+2)\b', t):
        values.update(v for v in range(max_val + 1) if v % 2 == 0)
        label = 'even values'
    if re.search(r'\bodd\b', t):
        values.update(v for v in range(max_val + 1) if v % 2 == 1)
        label = 'odd values'

    # Explicit decimal numbers ("5 or 6", "1, 4 or 9").
    nums = [int(n) for n in re.findall(r'\b(\d{1,2})\b', t)
            if 0 <= int(n) <= max_val]
    # Strip the width number itself if it appears as "4 bit" / "4-bit".
    nums = [n for n in nums
            if not re.search(rf'\b{n}\s*[-]?\s*bit\b', t)]
    if nums and not label:
        values.update(nums)
        label = f'values {{{", ".join(str(n) for n in sorted(set(nums)))}}}'
    elif nums and label:
        values.update(nums)

    if not values:
        return None
    values = sorted(v for v in values if 0 <= v <= max_val)

    terms = []
    for v in values:
        bits = format(v, f'0{width}b')
        lits = [name if b == '1' else f'~{name}'
                for b, name in zip(bits, vs)]
        terms.append('(' + ' & '.join(lits) + ')')
    expr = ' | '.join(terms) if terms else '0'
    desc = (f'Output is high when {"".join(vs)} reads as '
            f'{label or ", ".join(str(v) for v in values)}.')
    return (expr, 'value-set', desc)


def _conditional_from_text(text):
    """
    Parse two-clause conditional specs of the form:
      "output equals A when SEL is 0 and equals NOT B when SEL is 1"
      "Y = A if SEL=0 else NOT B"
      "result is A when SEL=0, otherwise NOT B"
    Returns (expression, name, desc) or None.

    Builds (~SEL & A) | (SEL & B) style expressions so the user gets a real
    multiplexer-like circuit instead of just the first clause.
    """
    t = text.lower()
    if not re.search(r'\b(when|if)\b.+?\b(when|else|otherwise|if)\b', t):
        return None

    # Find "<value-expr> when <cond>" clauses. Capture two of them.
    clause_re = re.compile(
        r'(?:equals?|is|=|gives?|outputs?)\s+'
        r'(not\s+\w+|~\w+|\w+)\s+'
        r'(?:when|if)\s+'
        r'(\w+)\s*(?:is|=|equals?)\s*([01])',
        re.IGNORECASE,
    )
    matches = clause_re.findall(text)
    # Also handle "when SEL=1 output equals NOT B".
    if len(matches) < 2:
        rev_re = re.compile(
            r'(?:when|if)\s+(\w+)\s*(?:is|=|equals?)\s*([01])\b'
            r'.{0,40}?(?:equals?|is|=|gives?|outputs?)\s+(not\s+\w+|~\w+|\w+)',
            re.IGNORECASE,
        )
        matches = [(val, sel, st) for (sel, st, val) in rev_re.findall(text)]
    if len(matches) < 2:
        return None

    parsed = []
    sel_name = None
    for val, sel, state in matches[:2]:
        v = val.strip()
        v = re.sub(r'^not\s+', '~', v, flags=re.IGNORECASE)
        sel = sel.upper()
        if sel_name is None:
            sel_name = sel
        elif sel != sel_name:
            return None    # two different selectors -> not a 2-clause cond
        parsed.append((v, int(state)))
    if not sel_name or len(parsed) != 2:
        return None

    parts = []
    for v, st in parsed:
        lit = sel_name if st == 1 else f'~{sel_name}'
        parts.append(f'({lit} & ({v}))')
    expr = ' | '.join(parts)
    desc = (f'Output equals {parsed[0][0]} when {sel_name}={parsed[0][1]}, '
            f'else {parsed[1][0]} when {sel_name}={parsed[1][1]}.')
    return (expr, 'conditional', desc)


def _minterms_from_text(text):
    """
    Build an SOP from binary input rows the user says produce a 1, e.g.
    "output is 1 for 00 and 11". Returns (expression, name, desc) or None.
    """
    groups = _NL_BIN_GROUP_RE.findall(text)
    if not groups:
        return None
    width = len(groups[0])
    rows = [g for g in groups if len(g) == width]
    if not (1 <= width <= 5) or not rows:
        return None
    vs = _nl_detect_vars(text)
    if len(vs) != width:
        vs = ['A', 'B', 'C', 'D', 'E'][:width]
    terms = []
    for row in rows:
        lits = [name if bit == '1' else f'~{name}'
                for bit, name in zip(row, vs)]
        terms.append('(' + ' & '.join(lits) + ')')
    if not terms:
        return None
    return (' | '.join(terms), 'custom',
            'Output is high for input rows: ' + ', '.join(rows) + '.')


# --- Multi-output natural-language specs -------------------------------------
#
# Parses things like:
#   "3 inputs, 2 outputs; when all 3 inputs are 1 both outputs give 1;
#    when all are 0 the first output gives 1"
# Returns [(out_label, expression), ...] or None.

_WORD_TO_INT = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
    'seven': 7, 'eight': 8, 'a': 1, 'an': 1, 'single': 1, 'both': 2,
}


def _word_count(token):
    """'three' / '3' / 'both' -> int, or None."""
    if not token:
        return None
    s = token.lower().strip()
    if s.isdigit():
        return int(s)
    return _WORD_TO_INT.get(s)


_NUM_INPUTS_RE = re.compile(
    r'\b(\d+|one|two|three|four|five|six|seven|eight)[-\s]+'
    r'(?:inputs?|lines?|signals?|bits?|variables?|wires?)\b',
    re.IGNORECASE)
_NUM_OUTPUTS_RE = re.compile(
    r'\b(\d+|one|two|three|four|five|both)\s+outputs?\b',
    re.IGNORECASE)


def _count_inputs_in_text(text):
    m = _NUM_INPUTS_RE.search(text)
    return _word_count(m.group(1)) if m else None


def _count_outputs_in_text(text):
    m = _NUM_OUTPUTS_RE.search(text)
    return _word_count(m.group(1)) if m else None


def _outputs_described(phrase, n_out):
    """
    From a phrase like "both outputs", "the first output", "one output",
    "two outputs give 1", "Y1 and Y2", return the set of 0-based output
    indices that should be 1. Defaults to {0} ("output is 1") if ambiguous.
    """
    p = phrase.lower()
    chosen = set()
    # Explicit "Y0/Y1/Y2..." mentions.
    for m in re.finditer(r'\by(\d+)\b', p):
        idx = int(m.group(1))
        if 0 <= idx < n_out:
            chosen.add(idx)
    # Ordinals.
    if 'first' in p:
        chosen.add(0)
    if 'second' in p and n_out > 1:
        chosen.add(1)
    if 'third' in p and n_out > 2:
        chosen.add(2)
    if 'last' in p and n_out > 0:
        chosen.add(n_out - 1)
    if chosen:
        return chosen
    # "N outputs" / "both outputs" / "all outputs". The regex now includes
    # 'one' so "one output gives 1" maps to just the first output, not all.
    m = re.search(
        r'\b(\d+|one|two|three|four|five|six|seven|eight|all|both|every|each)'
        r'\s+outputs?\b', p)
    if m:
        word = m.group(1).lower()
        if word in ('all', 'both', 'every', 'each'):
            return set(range(n_out))
        n = _word_count(word) or 0
        return set(range(min(n, n_out)))
    # Standalone "both" / "all" / "every" with no following "output" word.
    if re.search(r'\b(both|all|every)\b', p) and 'output' in p:
        return set(range(n_out))
    # "the output(s)" / "output is 1" with no qualifier  -  assume all.
    if 'output' in p:
        return set(range(n_out))
    return set()


def _condition_to_minterms(cond, n_in):
    """
    Map a condition phrase ("all 3 inputs are 1", "all are zero", "101",
    "A=1 B=0 C=1", "three input is 1") to a list of n_in-bit minterm
    strings ('110', ...) the condition selects.
    """
    c = cond.lower()
    # Explicit binary patterns matching the input width.
    bins = re.findall(r'\b([01]{%d})\b' % n_in, c)
    if bins:
        return list(dict.fromkeys(bins))
    # "N inputs are 1" / "N input is 1"  -  interpreted as "all N inputs are 1"
    # when N equals the input count (very common natural phrasing).
    m = re.search(
        r'\b(\d+|one|two|three|four|five|six|seven|eight)\s+inputs?\b'
        r'.{0,12}\b(is|are)\b.{0,12}\b(1|one|high|on|true)\b', c)
    if m and (_word_count(m.group(1)) == n_in):
        return ['1' * n_in]
    m = re.search(
        r'\b(\d+|one|two|three|four|five|six|seven|eight)\s+inputs?\b'
        r'.{0,12}\b(is|are)\b.{0,12}\b(0|zero|low|off|false)\b', c)
    if m and (_word_count(m.group(1)) == n_in):
        return ['0' * n_in]
    # "all (are) 1/high/on"  -  covers "all inputs high", "all are 1", etc.
    if (re.search(r'\ball\b.*\b(1|one|high|on|true)\b', c)
            or 'all inputs are high' in c
            or re.search(r'\b(every|each)\b.*\b(1|high|on|true)\b', c)):
        return ['1' * n_in]
    # "all (are) 0/low/zero/off"
    if (re.search(r'\ball\b.*\b(0|zero|low|off|false)\b', c)
            or 'all inputs are low' in c
            or re.search(r'\b(every|each)\b.*\b(0|low|zero|off|false)\b', c)
            or re.search(r'\ball\s+zero\b', c)):
        return ['0' * n_in]
    # "both are 1" / "both are high"  -  for 2-input circuits.
    if n_in == 2 and re.search(
            r'\bboth\b.*\b(1|one|high|on|true)\b', c):
        return ['1' * n_in]
    if n_in == 2 and re.search(
            r'\bboth\b.*\b(0|zero|low|off|false)\b', c):
        return ['0' * n_in]

    # "A=1, B=0, C=1" style.
    assigns = re.findall(r'\b([A-Za-z]\w*)\s*=\s*([01])', c)
    if assigns and len(assigns) == n_in:
        names = [a[0].upper() for a in assigns]
        if len(set(names)) == n_in:
            ordered = sorted(set(names))
            mt = ''.join(dict(assigns)[v.lower()] for v in ordered)
            return [mt]
    return []


def _spec_from_text(text):
    """
    Parse a multi-output natural-language spec. Returns
    [(label, expression), ...] or None.

    Strategy: split the text on ';' / '.' / 'and when' / 'also', then for
    each clause classify whether it's a "when X then output(s) Y = 1"
    declaration. Build a truth table per output and SOP it.
    """
    n_in = _count_inputs_in_text(text)
    n_out = _count_outputs_in_text(text)
    if not n_in or not n_out:
        return None
    if not (1 <= n_in <= 5) or not (1 <= n_out <= 8):
        return None

    in_names = ['A', 'B', 'C', 'D', 'E'][:n_in]
    out_names = [f'Y{i+1}' for i in range(n_out)]

    # Per-output set of minterm rows that produce 1, and the per-output set
    # explicitly forced to 0 (used when the user wrote "then output is 0").
    on_rows  = [set() for _ in range(n_out)]
    off_rows = [set() for _ in range(n_out)]

    # Pull out every "when ..." segment. Splitting on "when" naturally
    # handles "and when" / ", when" / "; when" too. The preamble (text
    # before the first "when") is dropped.
    parts = re.split(r'\bwhen\b', text, flags=re.IGNORECASE)
    saw_clause = False
    for clause in parts[1:]:
        cond, cons = '', ''
        # Try several condition->consequence separators in priority order.
        for sep_re in (r'\bthen\b',
                       r'\bit\s+gives?\b',
                       r'\bgives?\b',
                       r'\boutputs?\s+(?:is|are|gives?|equals?)\b',
                       r'->'):
            m = re.search(sep_re, clause, re.IGNORECASE)
            if m:
                cond, cons = clause[:m.start()], clause[m.start():]
                break
        if not cond:
            # Fallback: split where "output" first appears.
            idx = clause.lower().find('output')
            if idx >= 0:
                cut = clause.rfind(',', 0, idx)
                if cut < 0:
                    cut = idx
                    while cut > 0 and clause[cut-1] not in ' ,;':
                        cut -= 1
                cond, cons = clause[:cut], clause[cut:]
            else:
                cond, cons = clause, ''

        mts = _condition_to_minterms(cond, n_in)
        # Prefer a more specific output match from the whole clause over a
        # generic "output is ..." that resolves to all outputs. Otherwise an
        # ordinal like "first" that landed before the separator gets lost.
        cons_outs   = _outputs_described(cons, n_out)
        clause_outs = _outputs_described(clause, n_out)
        outs = clause_outs if (clause_outs and len(clause_outs) < len(cons_outs or {None})) else (cons_outs or clause_outs)

        # Polarity: does the consequent say the output is HIGH or LOW?
        # "then output is 0", "then out is low", "then output is false" ⇒ LOW
        # If LOW, the listed minterms must be EXCLUDED (output is 1 elsewhere).
        cons_says_low = bool(re.search(
            r"\b(?:output|out|y\d*|z\d*)\s+(?:is|=|equals?|gives?|becomes?)?\s*"
            r"(?:0|zero|low|false|off)\b|"
            r"\b(?:then|so|thus)\s+(?:0|zero|low|false|off)\b",
            cons, re.IGNORECASE))

        if mts and outs:
            saw_clause = True
            for mt in mts:
                idx = int(mt, 2)
                for oi in outs:
                    if cons_says_low:
                        off_rows[oi].add(idx)
                    else:
                        on_rows[oi].add(idx)
    if not saw_clause:
        return None

    # If the user said "when X then output is 0" without any other clauses,
    # the result is the complement of the off-rows over the full minterm space.
    N = 1 << n_in
    for i in range(n_out):
        if not on_rows[i] and off_rows[i]:
            on_rows[i] = set(range(N)) - off_rows[i]
        elif off_rows[i]:
            # Both clauses present — drop any "off" rows from the "on" set.
            on_rows[i] -= off_rows[i]

    parts = []
    for label, ones in zip(out_names, on_rows):
        if not ones:
            parts.append((label, '0'))
            continue
        if len(ones) == (1 << n_in):
            parts.append((label, '1'))
            continue
        terms = []
        for i in sorted(ones):
            bits = format(i, f'0{n_in}b')
            lits = [name if b == '1' else f'~{name}'
                    for b, name in zip(bits, in_names)]
            terms.append('(' + ' & '.join(lits) + ')')
        parts.append((label, ' | '.join(terms)))
    return parts



def _try_parametric_nbit(t_body: str):
    """
    Detect "N-bit adder", "N-bit comparator", etc. and return
    (canonical_name, parts_list) or None.
    """
    # If the user explicitly asks to build the N-bit unit OUT OF macro
    # sub-blocks ("4 bit adder using full adder", "4 bit register using d
    # flip flop"), defer to the RAW_TEMPLATES compositional table so the FA /
    # DFF / etc. blocks remain visible instead of being expanded.
    if re.search(
        r'\busing\s+(?:full\s+adder|fa|d\s+flip\s+flop|dff|'
        r't\s+flip\s+flop|tff|jk\s+flip\s+flop|jkff|'
        r'half\s+adder|ha|sr\s+latch|d\s+latch|'
        r'2\s*[-\s]?to\s*[-\s]?1\s*(?:mux|multiplexer)|mux2)\b',
        t_body, re.IGNORECASE,
    ):
        return None
    m = _NBIT_RE.search(t_body)
    if not m:
        return None
    n = int(m.group(1))
    if not (1 <= n <= 16):
        return None  # Refuse extreme sizes  -  would blow up the canvas.
    kind = re.sub(r'\s+', ' ', m.group(2).lower())
    if 'adder' in kind:
        return (f'{n}-bit ripple-carry adder', _build_nbit_adder(n))
    if 'subtractor' in kind:
        # Two's-complement subtractor: A - B = A + ~B + 1
        # We just reuse the adder structure with B' = ~Bi and Cin = 1.
        parts = []
        expr_carry = '1'
        for i in range(n):
            a, b = f'A{i}', f'~B{i}'
            parts.append((f'D{i}', f'{a} ^ ({b}) ^ ({expr_carry})'))
            expr_carry = (f'({a} & ({b})) | '
                          f'(({expr_carry}) & ({a} ^ ({b})))')
        parts.append(('Bout', expr_carry))
        return (f'{n}-bit subtractor', parts)
    if 'comparator' in kind or 'equality' in kind:
        # "magnitude comparator" goes to the multi-output template (gt/eq/lt),
        # not the equality-only parametric build.
        if 'magnitude' in kind:
            return None
        return (f'{n}-bit equality comparator',
                _build_nbit_equality_comparator(n))
    return None


class QuestionSolver:
    def __init__(self, fault_detector=None, gate_minimizer=None,
                 boolean_synth=None):
        self.fault_detector = fault_detector
        self.gate_minimizer = gate_minimizer
        self.boolean_synth  = boolean_synth

        # Question intent patterns
        self.patterns = {
            'build': [
                r'\bbuild\b', r'\bmake\b', r'\bdesign\b', r'\bcreate\b',
                r'\bconstruct\b', r'\bgenerate\b', r'\bgive me\b',
                r'\bshow.*circuit\b', r'\bturn.*into.*gates?\b',
                r'\bconvert.*to.*gates?\b'
            ],
            'output_query': [
                r'what.*output', r'output.*when', r'result.*if',
                r'what.*produce', r'compute.*output', r'calculate.*result'
            ],
            'gate_count': [
                r'how many gates', r'number of gates', r'gate count',
                r'total gates', r'count.*gates'
            ],
            'gate_type': [
                r'what.*gate', r'which.*gate', r'type of gate',
                r'gate.*type', r'what kind'
            ],
            'minimize': [
                r'minimize', r'reduce.*gate', r'fewer gates',
                r'simplif', r'optim', r'minimum gates', r'least gates'
            ],
            'fault_check': [
                r'any.*fault', r'is.*correct', r'valid.*circuit',
                r'error.*circuit', r'problem.*circuit', r'fault.*detect',
                r'check.*circuit', r'verify'
            ],
            'what_if': [
                r'what if', r'if i change', r'replace.*with',
                r'swap.*gate', r'instead of'
            ],
            'explain': [
                r'explain', r'how does.*work', r'describe.*circuit',
                r'what does.*do', r'purpose of'
            ],
            'input_effect': [
                r'when.*input', r'if.*=\s*[01]', r'set.*to [01]',
                r'change.*input', r'input.*[01]'
            ]
        }

    def solve(self, question: str, circuit: dict) -> dict:
        """
        Main entry point.
        Returns {answer, confidence, details, suggestions, [circuit]}

        Intent classification is now two-stage:
          1. Trained TF-IDF + LogisticRegression model (99% test accuracy on
             3 412 labelled phrasings  -  see ml_models/intent_classifier.py).
          2. Hand-written regex rules as a fallback for low-confidence cases.
        """
        question_lower = question.lower().strip()

        # ─── Knowledge-base shortcut ─────────────────────────────────────────
        # Canonical digital-logic / SDE-interview questions ("what is propagation
        # delay", "explain NAND universality", "De Morgan's law", …) get a
        # polished textbook answer regardless of how the intent classifier
        # would have routed them. The intent classifier was trained mostly on
        # circuit-manipulation phrasings and tends to misroute these to
        # `output_query`, so we bypass it for concept questions.
        #
        # CRITICAL: skip the KB shortcut when the user explicitly asks to BUILD
        # something. Otherwise "build a half adder" would match the "Adders"
        # KB pattern and return a textbook paragraph instead of synthesizing
        # the circuit.
        _BUILD_VERBS = (
            r'^\s*(?:please\s+|pls\s+|plz\s+|hey\s+|hi\s+|yo\s+|um\s+|so\s+)?'
            r'(?:can\s+(?:you|u)\s+|could\s+(?:you|u)\s+|i\s+(?:want|need|wanna|wish)\s+(?:to\s+)?|'
            r'i\'?d\s+like\s+(?:to\s+)?|gimme\s+|give\s+me\s+(?:an?\s+)?|'
            r'show\s+me\s+(?:an?\s+)?|let\'?s\s+|'
            # "how to build", "how do you make", "how can we design" — i optional
            r'how\s+(?:do|to|can|would|should)\s+(?:i|you|u|we)?\s*)?'
            r'(?:build|make|design|create|construct|generate|draw|wire\s+up|'
            r'synthesize|synthesise|implement|assemble|sketch|put\s+together|'
            r'render|produce|set\s+up|i\s+want|i\s+need)\b'
        )
        is_build_request = bool(re.search(_BUILD_VERBS, question_lower))

        # Also skip if the question describes a behaviour to implement
        # ("output is 1 when …", "Y=1 when A=…", "when all inputs are 1 …").
        is_behaviour_spec = bool(re.search(
            r'\b(?:output|out|y\d*|z\d*)\s+(?:is|=|equals?)\s+[01]\b|'
            r'\b(?:y|z)\s*=\s*[01]\s+when\b|'
            r'\bwhen\s+(?:all|any|every|exactly|at\s+least|at\s+most|some)\b.*\b(?:then|gives?|outputs?|=)\b',
            question_lower))

        # Gate-set restriction ("full adder using NAND", "XOR with NOR only")
        # is a strong build signal even without a leading "build" verb.
        has_restriction = _parse_target(question)[0] is not None

        if not is_build_request and not is_behaviour_spec and not has_restriction:
            kb = self._try_knowledge_base(question_lower)
            if kb is not None:
                kb.setdefault('intent', 'concept')
                kb['intent_confidence'] = 0.95
                kb['ml_source']         = 'knowledge_base'
                return kb

        intent, conf, source = self._classify_intent_detailed(question_lower)

        # Extract any input values mentioned in question
        input_overrides = self._extract_inputs(question_lower)

        if intent == 'build':
            result = self.build_from_text(question)
        elif intent == 'output_query' or intent == 'input_effect':
            result = self._answer_output_query(question, circuit, input_overrides)
        elif intent == 'gate_count':
            result = self._answer_gate_count(circuit)
        elif intent == 'gate_type':
            result = self._answer_gate_type(question, circuit)
        elif intent == 'minimize':
            result = self._answer_minimize(circuit)
        elif intent == 'fault_check':
            result = self._answer_fault_check(circuit)
        elif intent == 'what_if':
            result = self._answer_what_if(question, circuit)
        elif intent == 'explain':
            result = self._answer_explain(circuit, question)
        else:
            result = self._answer_general(question, circuit)

        # Always expose ML metadata so the UI can show what model decided what.
        # If a handler already set 'confidence' (e.g. fault-detector probability),
        # keep it and surface the intent confidence separately.
        result.setdefault('intent', intent)
        result['intent_confidence'] = round(float(conf), 3)
        result['ml_source']         = source       # 'ml' | 'regex' | 'fallback'
        return result

    # -- Intent classifier -----------------------------------------------------
    #
    # Two-stage: the trained ML model is consulted first. If its confidence is
    # below LOW_CONF (≈30 %) we fall back to the legacy regex rules. The
    # IntentClassifier is loaded lazily so importing this module doesn't pay
    # the training cost when only build_from_text() is used (e.g. /api/build).

    _ml_intent = None

    @classmethod
    def _get_ml_intent(cls):
        if cls._ml_intent is None:
            try:
                from .intent_classifier import IntentClassifier
                cls._ml_intent = IntentClassifier()
            except Exception as e:
                print(f'[QuestionSolver] IntentClassifier unavailable ({e}); '
                      f'using regex-only.')
                cls._ml_intent = False    # remember the failure to avoid retry
        return cls._ml_intent or None

    def _classify_intent(self, q: str) -> str:
        intent, _, _ = self._classify_intent_detailed(q)
        return intent

    def _classify_intent_detailed(self, q: str):
        """
        Returns (intent, confidence, source).

        source ∈ {'ml', 'regex', 'fallback'} — tells the UI which model decided.
        """
        ml = self._get_ml_intent()
        if ml is not None:
            intent, conf = ml.classify(q)
            if conf >= getattr(ml, 'LOW_CONF', 0.30):
                return intent, conf, 'ml'

        # Regex fallback (legacy)
        scores = {}
        for intent, patterns in self.patterns.items():
            score = sum(1 for p in patterns if re.search(p, q))
            if score > 0:
                scores[intent] = score
        if not scores:
            return 'general', 0.0, 'fallback'
        winner = max(scores, key=scores.get)
        total  = sum(scores.values())
        return winner, scores[winner] / total, 'regex'

    def _extract_inputs(self, q: str) -> dict:
        """Extract A=1, B=0 etc from question text."""
        overrides = {}
        for match in re.finditer(r'([abcdABCD])\s*=\s*([01])', q):
            key = match.group(1).upper()
            val = int(match.group(2))
            overrides[key] = val
        return overrides

    # -- Answer generators -----------------------------------------------------

    def _answer_output_query(self, question: str, circuit: dict, overrides: dict) -> dict:
        gates  = circuit.get('gates', [])
        input_gates = [g for g in gates if g['type'].upper() in ('INPUT', 'CLOCK')]

        # Apply input overrides from question
        applied = []
        for g in input_gates:
            label = g.get('label', g.get('id', '')).upper()
            if label in overrides:
                g['value'] = overrides[label]
                applied.append(f"{label}={overrides[label]}")

        if self.fault_detector and self.fault_detector.model:
            row  = self.fault_detector._circuit_to_row(circuit)
            pred = self.fault_detector.predict_output(row)
            conf = self.fault_detector.predict_proba(row)

            input_desc = ', '.join([f"{g.get('label','?')}={g.get('value',0)}"
                                    for g in input_gates])

            return {
                'answer': f"With inputs [{input_desc}], the ML model predicts the circuit output is **{pred}**.",
                'confidence': conf if pred == 1 else 1 - conf,
                'details': {
                    'predicted_output': pred,
                    'model_confidence': f"{max(conf, 1-conf):.0%}",
                    'inputs_applied': applied or 'current values used'
                },
                'suggestions': [
                    f"Try toggling inputs to see how output changes.",
                    f"Use Fault Detection to verify the circuit is wired correctly."
                ]
            }
        else:
            return {
                'answer': "ML model not loaded. Please start the backend and ensure training data is present.",
                'confidence': 0,
                'details': {},
                'suggestions': ['Run: python app.py to start the backend']
            }

    def _answer_gate_count(self, circuit: dict) -> dict:
        gates = circuit.get('gates', [])
        logic = [g for g in gates if g['type'].upper() not in ('INPUT','CLOCK','OUTPUT')]
        inputs= [g for g in gates if g['type'].upper() in ('INPUT','CLOCK')]
        outputs=[g for g in gates if g['type'].upper() == 'OUTPUT']

        type_breakdown = {}
        for g in logic:
            t = g['type'].upper()
            type_breakdown[t] = type_breakdown.get(t, 0) + 1

        return {
            'answer': f"This circuit uses **{len(logic)} logic gates**, {len(inputs)} input(s), and {len(outputs)} output(s). Total components: {len(gates)}.",
            'confidence': 1.0,
            'details': {
                'logic_gates':   len(logic),
                'input_gates':   len(inputs),
                'output_gates':  len(outputs),
                'total':         len(gates),
                'breakdown':     type_breakdown
            },
            'suggestions': [
                'Use Gate Minimization to see if the gate count can be reduced.',
                f"Gate types used: {', '.join(type_breakdown.keys())}"
            ]
        }

    def _answer_gate_type(self, question: str, circuit: dict) -> dict:
        gates = circuit.get('gates', [])
        logic = [g for g in gates if g['type'].upper() not in ('INPUT','CLOCK','OUTPUT')]

        type_counts = {}
        for g in logic:
            t = g['type'].upper()
            type_counts[t] = type_counts.get(t, 0) + 1

        if not type_counts:
            return {'answer': 'No logic gates found in circuit.',
                    'confidence': 1.0, 'details': {}, 'suggestions': []}

        most_used = max(type_counts, key=type_counts.get)
        least_used = min(type_counts, key=type_counts.get)
        breakdown = ', '.join(f"{t}: {c}" for t, c in sorted(type_counts.items()))

        return {
            'answer': f"Gate type breakdown: **{breakdown}**. Most used: **{most_used}** ({type_counts[most_used]}x).",
            'confidence': 1.0,
            'details': {
                'type_counts':  type_counts,
                'most_used':    most_used,
                'least_used':   least_used,
                'unique_types': len(type_counts)
            },
            'suggestions': [
                f"{'NAND' if 'NAND' not in type_counts else 'NOR'} gates can replace any combination of AND/OR/NOT.",
                'Universal gate implementation can simplify manufacturing.'
            ]
        }

    def _answer_minimize(self, circuit: dict) -> dict:
        if self.gate_minimizer:
            result = self.gate_minimizer.minimize_circuit(circuit)
            current = result['current_gate_count']
            bench   = result['benchmark']
            score   = result['efficiency_score']

            top_suggestion = result['suggestions'][0] if result['suggestions'] else {}

            return {
                'answer': f"Your circuit uses **{current} gates**. "
                          f"ML analysis shows similar circuits can use as few as **{bench.get('min', current)} gates**. "
                          f"Efficiency score: **{score}/100**.",
                'confidence': 0.85,
                'details':     result,
                'suggestions': [s['description'] for s in result['suggestions'][:3]]
            }
        return {
            'answer': 'Gate minimizer not available.',
            'confidence': 0, 'details': {}, 'suggestions': []
        }

    def _answer_fault_check(self, circuit: dict) -> dict:
        if self.fault_detector:
            faults = self.fault_detector.detect_faults(circuit)
            if not faults:
                return {
                    'answer': '✅ No faults detected. Circuit structure looks correct.',
                    'confidence': 0.9,
                    'details': {'fault_count': 0, 'faults': []},
                    'suggestions': ['Run full analysis for optimization tips.']
                }
            critical = [f for f in faults if f['severity'] == 'CRITICAL']
            return {
                'answer': f"⚠️ Found **{len(faults)} fault(s)**"
                          + (f", including **{len(critical)} CRITICAL**" if critical else "")
                          + ". See details below.",
                'confidence': 0.95,
                'details': {'fault_count': len(faults), 'faults': faults},
                'suggestions': [f['message'] for f in faults[:3]]
            }
        return {'answer': 'Fault detector not available.', 'confidence': 0,
                'details': {}, 'suggestions': []}

    def _answer_what_if(self, question: str, circuit: dict) -> dict:
        # Extract gate type from question
        types_mentioned = []
        for gt in ['AND', 'OR', 'NOT', 'NAND', 'NOR', 'XOR', 'XNOR']:
            if gt.lower() in question.lower():
                types_mentioned.append(gt)

        if not types_mentioned or not self.fault_detector:
            return {
                'answer': 'Please specify which gate type you want to try (AND, OR, NOT, NAND, NOR, XOR, XNOR).',
                'confidence': 0.5, 'details': {}, 'suggestions': []
            }

        new_type = types_mentioned[-1]
        gates    = circuit.get('gates', [])
        logic    = [g for g in gates if g['type'].upper() not in ('INPUT','CLOCK','OUTPUT')]

        if not logic:
            return {'answer': 'No logic gates to modify.', 'confidence': 1.0,
                    'details': {}, 'suggestions': []}

        # Simulate changing first logic gate to new_type
        import copy
        modified_circuit = copy.deepcopy(circuit)
        target_gate = None
        for g in modified_circuit['gates']:
            if g['id'] == logic[0]['id']:
                g['type'] = new_type
                target_gate = g
                break

        if self.fault_detector.model:
            orig_row  = self.fault_detector._circuit_to_row(circuit)
            mod_row   = self.fault_detector._circuit_to_row(modified_circuit)
            orig_pred = self.fault_detector.predict_output(orig_row)
            mod_pred  = self.fault_detector.predict_output(mod_row)

            changed = orig_pred != mod_pred
            return {
                'answer': f"If gate '{logic[0]['id']}' changes to **{new_type}**: "
                          + (f"output changes from **{orig_pred}** -> **{mod_pred}**." if changed
                             else f"output remains **{orig_pred}** (no change)."),
                'confidence': 0.8,
                'details': {
                    'original_output': orig_pred,
                    'modified_output': mod_pred,
                    'output_changed':  changed,
                    'gate_changed':    logic[0]['id'],
                    'new_type':        new_type
                },
                'suggestions': [
                    'Use the circuit editor to apply this change.',
                    'Run fault detection after any change.'
                ]
            }

        return {'answer': 'Could not simulate change.', 'confidence': 0,
                'details': {}, 'suggestions': []}

    def _answer_explain(self, circuit: dict, question: str = '') -> dict:
        # If the question is a "what is X" / "explain Y" about a concept, prefer
        # the knowledge-base answer over the circuit-stats dump.
        if question:
            kb = self._try_knowledge_base(question)
            if kb is not None:
                return kb

        gates   = circuit.get('gates', [])
        wires   = circuit.get('wires', [])
        logic   = [g for g in gates if g['type'].upper() not in ('INPUT','CLOCK','OUTPUT')]
        inputs  = [g for g in gates if g['type'].upper() in ('INPUT','CLOCK')]
        outputs = [g for g in gates if g['type'].upper() == 'OUTPUT']

        # Empty circuit + concept-style question — defer to general handler so the
        # user gets useful suggestions instead of a uninformative "0 gates" dump.
        if not gates:
            return {
                'answer': ("There's no circuit on the canvas yet. Try asking about a digital-logic "
                           "concept (\"what is XOR\", \"explain NAND universality\", \"how do flip-flops work\"), "
                           "or place some gates and ask me to explain them."),
                'confidence': 0.6,
                'details': {'circuit_size': 0},
                'suggestions': [
                    'What is an XOR gate?',
                    'Explain NAND universality.',
                    'How do flip-flops work?',
                    'What is propagation delay?',
                    'Difference between Mealy and Moore machines?',
                    'Build a half adder.',
                ]
            }

        type_counts = {}
        for g in logic:
            t = g['type'].upper()
            type_counts[t] = type_counts.get(t, 0) + 1

        desc = (f"This circuit has {len(inputs)} input(s) and {len(outputs)} output(s). "
                f"It uses {len(logic)} logic gate(s): "
                f"{', '.join(f'{c}× {t}' for t, c in type_counts.items())}. "
                f"The gates are connected by {len(wires)} wire(s).")

        return {
            'answer': desc,
            'confidence': 1.0,
            'details': {
                'inputs': len(inputs),
                'outputs': len(outputs),
                'logic_gates': len(logic),
                'wires': len(wires),
                'gate_types': type_counts
            },
            'suggestions': [
                'Ask "what is the output when A=1, B=0?" for a specific output prediction.',
                'Ask "are there any faults?" to validate the circuit.',
                'Ask "how to minimize?" for gate reduction suggestions.'
            ]
        }

    # -- Build-from-text (question -> circuit JSON) ----------------------------

    def build_from_text(self, text: str) -> dict:
        """
        Try to construct a circuit from free-form text.

        Recognised forms:
          1. "build a half adder", "make a 2-to-1 mux"          -> KNOWN_CIRCUITS
          2. "build A xor B and C", "make ~(A&B) | C"           -> boolean parser
          3. "XOR using NAND", "build A&B using only NOR"       -> restricted set
        """
        if self.boolean_synth is None:
            return {
                'answer':      'Boolean synthesizer not available.',
                'confidence':  0.0,
                'details':     {},
                'suggestions': [],
            }

        # Normalise typos / synonyms first so subsequent matchers see a
        # canonical phrasing ("subtracter" -> "subtractor", "gatye" -> "gate",
        # "flipflop" -> "flip flop", "1 bit adder" -> "full adder", ...).
        text = _normalize_request_text(text)

        # Pull out the restriction phrase ("using NAND", "from OR and NOT",
        # "with help of NAND/NOR", "NAND only", ...). Whatever is left after
        # the phrase is removed is what we search for a circuit name in.
        target, body = _parse_target(text)
        t      = text.lower().strip()
        t_body = body.lower().strip()
        target_label = (f" using only {'/'.join(target)}"
                        if target else "")

        # ── Multi-output spec: "Y1 = expr1 ; Y2 = expr2 ; ..." ────────────
        # Emitted by the SMART truth-table builder for circuits with >1 output.
        # Detect a `;` between two `Name = expr` clauses and route through
        # _build_multi_output.
        if ';' in body and re.search(r'[A-Za-z_]\w*\s*=', body):
            parts = []
            for chunk in re.split(r'\s*;\s*', body):
                m_chunk = re.match(r'^\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$', chunk)
                if m_chunk:
                    parts.append((m_chunk.group(1), m_chunk.group(2)))
            if len(parts) >= 2:
                try:
                    circuit, info = self._build_multi_output(parts, target)
                except BooleanParseError as e:
                    return self._impossible_target_answer(
                        f"multi-output ({len(parts)} outputs)", target, str(e))
                return {
                    'answer':     f"Built **multi-output circuit**{target_label}  -  "
                                  f"{info['gate_count']} logic gate"
                                  f"{'s' if info['gate_count'] != 1 else ''}, "
                                  f"{info['wire_count']} wires, "
                                  f"{len(parts)} outputs.",
                    'confidence': 0.9,
                    'circuit':    circuit,
                    'info':       info,
                    'details':    info,
                    'suggestions': [
                        "Press RUN to simulate.",
                        "Open K-Map / BOOL tabs to verify each output.",
                    ],
                }

        # 0a-pre. Detect "X using <sub-block>" where the combination has NO
        # known composition recipe. Without this, "adder using flip flop"
        # silently falls through to the parametric/boolean path and the
        # "using flip flop" hint is dropped — the user gets a normal adder
        # and thinks the system ignored their input. Return a clear answer
        # listing the available compositions instead.
        m_using = re.search(
            r'\busing\s+(half\s+adder|ha|full\s+adder|fa|'
            r'(?:d\s+|t\s+|jk\s+|sr\s+)?flip\s+flop|dff|tff|jkff|'
            r'register|shift\s+register|latch|sr\s+latch|d\s+latch|'
            r'multiplexer|mux|2[-\s]?to[-\s]?1\s*mux|mux2|'
            r'comparator|cmp|decoder|encoder)\b',
            t_body, re.IGNORECASE)
        if m_using:
            phrase = re.sub(r'\s+', ' ', m_using.group(0).lower())
            # Does ANY known RAW_TEMPLATE name match the whole body? If so
            # we'll just fall through normally and the template loop will
            # pick it up. We only emit the "not a valid composition" answer
            # when NO template matches AND the parametric path also can't
            # use it.
            template_matches = any(
                name in t_body
                for name in RAW_TEMPLATES.keys()
                if 'using' in name or 'from' in name or 'with' in name
            )
            if not template_matches:
                comp_list = sorted({
                    name for name in RAW_TEMPLATES.keys()
                    if ' using ' in name or ' from ' in name or ' with ' in name
                })
                # Pick the 6 most-relevant suggestions by keyword overlap.
                kw_tokens = set(re.findall(r'\w+', phrase))
                comp_list.sort(key=lambda n: -len(set(re.findall(r'\w+', n)) & kw_tokens))
                suggestions = comp_list[:6]
                return {
                    'answer': (
                        f"`{body.strip()}` isn't a standard circuit composition. "
                        f"Try one of these instead:\n  • " +
                        "\n  • ".join(suggestions) +
                        "\n\n(Tip: flip-flops are sequential / have memory — they "
                        "compose into registers and counters, not into adders.)"
                    ),
                    'confidence': 0.4,
                    'details': {'requested': body, 'suggestions': suggestions},
                    'suggestions': suggestions,
                    'intent': 'concept',
                    'ml_source': 'compose_validator',
                }

        # 0a. Parametric N-bit synthesis ("4-bit adder", "8-bit comparator").
        #     Tried before fixed templates so "1 bit adder" still maps to
        #     full adder via the alias rule, but "4 bit adder" goes here.
        nbit = _try_parametric_nbit(t_body)
        if nbit is not None:
            name, parts = nbit
            try:
                circuit, info = self._build_multi_output(parts, target)
            except BooleanParseError as e:
                return self._impossible_target_answer(name, target, str(e))
            return {
                'answer':     f"Built **{name}**{target_label}  -  "
                              f"{info['gate_count']} logic gate"
                              f"{'s' if info['gate_count'] != 1 else ''}, "
                              f"{info['wire_count']} wires, "
                              f"{len(parts)} outputs.",
                'confidence': 0.9,
                'circuit':    circuit,
                'info':       info,
                'details':    info,
                'suggestions': [
                    "Press RUN to simulate. Set each Ai/Bi input then RUN.",
                    "Try 'using only NAND' for the universal-gate form.",
                ],
            }

        # 0b. Sequential / feedback circuits (SR latch, D flip-flop, ...).
        #     These are pre-built gate/wire JSON because boolean_synth can't
        #     emit feedback wires. Static simulation can't model the loop  - 
        #     surfaces a heads-up in the answer.
        for name, factory in sorted(RAW_TEMPLATES.items(),
                                    key=lambda kv: -len(kv[0])):
            if re.search(rf'\b{re.escape(name)}\b', t_body):
                circuit = factory()
                gates = circuit['gates']
                wires = circuit['wires']
                n_logic = sum(1 for g in gates
                              if g['type'] not in ('INPUT', 'OUTPUT', 'CLOCK'))
                outs = [g['label'] for g in gates if g['type'] == 'OUTPUT']
                info = {
                    'gate_count': n_logic,
                    'wire_count': len(wires),
                    'input_vars': [g['label'] for g in gates
                                   if g['type'] == 'INPUT'],
                    'outputs':    outs,
                    'target_gates': None,
                    'sequential': True,
                }
                return {
                    'answer':     f"Built **{name}**  -  {n_logic} logic gate"
                                  f"{'s' if n_logic != 1 else ''}, "
                                  f"{len(wires)} wires, {len(outs)} outputs. "
                                  f"This circuit has feedback (a loop), so "
                                  f"static simulation can't show its dynamic "
                                  f"behaviour  -  toggle the inputs to study "
                                  f"the structure.",
                    'confidence': 0.9,
                    'circuit':    circuit,
                    'info':       info,
                    'details':    info,
                    'suggestions': [
                        "Toggle S and R to study the latch states.",
                        "Use a CLOCK on the enable/CLK input for sequential timing.",
                    ],
                }

        # 1a. Multi-output known circuits (half adder, full adder, ...).
        #     Sort longest-name-first so specific phrases like
        #     "3 to 8 decoder" win over the generic "decoder" alias.
        #     ALSO: if a single-output entry in KNOWN_CIRCUITS has a longer
        #     matching name (e.g. "half adder sum" vs the multi-output
        #     "half adder"), defer to that. Without this check, "build a
        #     half adder sum" would silently return the 2-output half adder
        #     instead of the sum-only XOR.
        _single_match_len = 0
        for sk in KNOWN_CIRCUITS:
            if re.search(rf'\b{re.escape(sk)}\b', t_body) and len(sk) > _single_match_len:
                _single_match_len = len(sk)
        for name, parts in sorted(MULTI_OUTPUT_CIRCUITS.items(),
                                  key=lambda kv: -len(kv[0])):
            if len(name) < _single_match_len:
                break    # any further multi-output names are even shorter
            if re.search(rf'\b{re.escape(name)}\b', t_body):
                try:
                    circuit, info = self._build_multi_output(parts, target)
                except BooleanParseError as e:
                    return self._impossible_target_answer(name, target, str(e))
                return {
                    'answer':     f"Built **{name}**{target_label}  -  "
                                  f"{info['gate_count']} logic gate"
                                  f"{'s' if info['gate_count'] != 1 else ''}, "
                                  f"{info['wire_count']} wires, "
                                  f"{len(parts)} outputs.",
                    'confidence': 0.95,
                    'circuit':    circuit,
                    'info':       info,
                    'details':    info,
                    'suggestions': [
                        "Press RUN to simulate.",
                        "Try 'using only NAND' for the universal-gate form.",
                    ],
                }

        # 1b. Single-output known circuit name. Longest-first for the same
        #     reason as 1a (specific > generic alias).
        for name, expr in sorted(KNOWN_CIRCUITS.items(),
                                 key=lambda kv: -len(kv[0])):
            if re.search(rf'\b{re.escape(name)}\b', t_body):
                try:
                    circuit, info = self.boolean_synth.build(
                        expr, target_gates=target,
                        output_label=name.split()[0].upper())
                except BooleanParseError as e:
                    return self._impossible_target_answer(name, target, str(e))
                return {
                    'answer':     f"Built **{name}**{target_label}  -  "
                                  f"{info['gate_count']} logic gate"
                                  f"{'s' if info['gate_count'] != 1 else ''}, "
                                  f"{info['wire_count']} wires.",
                    'confidence': 0.95,
                    'circuit':    circuit,
                    'info':       info,
                    'details':    info,
                    'suggestions': [
                        "Press RUN to simulate.",
                        "Try 'using only NAND' to see the universal-gate form.",
                    ],
                }

        # 1c. Bare gate name ("XOR", "build NAND", "NOT gate from OR").
        #    The boolean parser can't consume "XOR" alone because it's an
        #    operator. Strip leading verbs from the already-target-stripped
        #    body, drop the word "gate(s)", and match what remains against
        #    the gate-name table.
        bare = re.sub(
            r'^\s*(please\s+)?(build|make|design|create|construct|generate|'
            r'give me|show me|i want|i need|made)\s*'
            r'(?:(?:a|an|the)\s+(?=[A-Za-z]{2}))?\s*(circuit\s+for\s+)?',
            '', body, flags=re.I)
        bare = re.sub(r'\b(gate|gates|logic)\b', '', bare, flags=re.I)
        bare = bare.strip().rstrip('.?!').upper()
        if bare in BARE_GATE_EXPR:
            expr, default_label = BARE_GATE_EXPR[bare]
            try:
                circuit, info = self.boolean_synth.build(
                    expr, target_gates=target, output_label=default_label)
            except BooleanParseError as e:
                return self._impossible_target_answer(bare, target, str(e))
            return {
                'answer':     f"Built **{bare}**{target_label}  -  "
                              f"{info['gate_count']} logic gate"
                              f"{'s' if info['gate_count'] != 1 else ''}, "
                              f"{info['wire_count']} wires.",
                'confidence': 0.95,
                'circuit':    circuit,
                'info':       info,
                'details':    info,
                'suggestions': [
                    "Press RUN to simulate.",
                    "Try 'XOR using only NAND' for the universal-gate form.",
                ],
            }

        # 1c.4  Try a direct boolean parse on the cleaned body. This catches
        #       phrasings the boolean parser already understands but that
        #       other NL parsers were stealing  -  e.g. "not A and not B",
        #       "A and not B", "A and B and not C". We only commit to it
        #       when there are NO "when/if/for" / "1 for inputs" tokens (those
        #       are truth-table specs, not direct expressions).
        direct_body = re.sub(
            r'^\s*(please\s+)?(build|make|design|create|construct|generate|'
            r'give me|show me|i want|i need|circuit\s+for)\s*'
            r'(?:(?:a|an|the)\s+(?=[A-Za-z]{2}))?\s*(circuit\s+for\s+)?',
            '', body, flags=re.I).strip().rstrip('.?!')
        # Also strip a bare leading "circuit for" when no verb preceded it
        # (e.g. "circuit for A + B" -> "A + B").
        direct_body = re.sub(r'^\s*circuit\s+for\s+', '', direct_body, flags=re.I).strip()
        looks_like_expr = (
            direct_body
            and not re.search(r'\b(when|if|for|while|unless|only)\b', direct_body, re.I)
            and not re.search(r'\b\d{2,}\b', direct_body)   # no "011" minterms
            and not re.search(r'=\s*[01]', direct_body)     # no "A=1"
        )
        if looks_like_expr:
            # Translate engineering-notation booleans (+ for OR, . for AND, '
            # for NOT) into the parser's syntax. Only do this when the body
            # contains at least one `+`, `.`, or trailing-quote-NOT - otherwise
            # we'd corrupt normal expressions like "A & B".
            normalized_expr = direct_body
            if re.search(r"[A-Za-z]\s*[+.]\s*[A-Za-z]|[A-Za-z]'", direct_body):
                normalized_expr = re.sub(r"\+", " | ", normalized_expr)
                normalized_expr = re.sub(r"(?<=\w)\.(?=\w)", " & ", normalized_expr)
                normalized_expr = re.sub(r"([A-Za-z]\w*)'", r"~\1", normalized_expr)
            try:
                circuit, info = self.boolean_synth.build(
                    normalized_expr, target_gates=target)
                if info.get('gate_count', 0) > 0:
                    simp = info.get('simplified', direct_body)
                    return {
                        'answer':     f"Built circuit from `{direct_body}`{target_label}  -  "
                                      f"{info['gate_count']} logic gate"
                                      f"{'s' if info['gate_count'] != 1 else ''}, "
                                      f"{info['wire_count']} wires.",
                        'confidence': 0.85,
                        'circuit':    circuit,
                        'info':       info,
                        'details':    info,
                        'suggestions': [
                            "Press RUN to simulate.",
                            "Try 'using only NAND' for the universal-gate form.",
                        ],
                    }
            except BooleanParseError:
                pass  # not a clean boolean expression; let NL parsers try

        # 1c.5  Multi-output natural-language spec
        #       ("3 inputs, 2 outputs; when all 3 are 1 both outputs give 1;
        #        when all are 0 the first output is 1").
        spec_parts = _spec_from_text(body)
        if spec_parts is not None:
            try:
                circuit, info = self._build_multi_output(spec_parts, target)
            except BooleanParseError as e:
                return self._impossible_target_answer(
                    "custom multi-output", target, str(e))
            return {
                'answer':     (f"Built a custom **{len(info.get('input_vars',[]))}-input, "
                               f"{len(spec_parts)}-output** circuit"
                               f"{target_label}. Outputs: "
                               + ", ".join(f"`{lbl} = {expr}`" for lbl, expr in spec_parts) + "."),
                'confidence': 0.8,
                'circuit':    circuit,
                'info':       info,
                'details':    info,
                'suggestions': [
                    "Press RUN to simulate. Toggle each input then RUN.",
                    "Try 'using only NAND' for the universal-gate form.",
                ],
            }

        # 1c.55 Counting constraints ("exactly two inputs are 1",
        #       "at least 3 are high", "fewer than 2 are on").
        cc = _count_constraint_from_text(body)
        if cc is not None:
            expr, cc_name, cc_desc = cc
            try:
                circuit, info = self.boolean_synth.build(expr, target_gates=target)
            except BooleanParseError as e:
                if target:
                    return self._impossible_target_answer(cc_name, target, str(e))
                circuit = info = None
            if circuit is not None and info.get('gate_count', 0) > 0:
                simp = info.get('simplified', expr)
                simp_note = ("" if info.get('is_simplest')
                             else f" Simplifies to **{simp}**.")
                return {
                    'answer':     f"{cc_desc} Boolean: `{expr}`.{simp_note} "
                                  f"Built {info['gate_count']} logic gate"
                                  f"{'s' if info['gate_count'] != 1 else ''}, "
                                  f"{info['wire_count']} wires.",
                    'confidence': 0.9,
                    'circuit':    circuit,
                    'info':       info,
                    'details':    info,
                    'suggestions': ["Press RUN to simulate."],
                }

        # 1c.5b Two-clause conditional ("A when SEL=0 else NOT B when SEL=1").
        #       Tried before the row-spec parser so its "SEL is 0/1" doesn't
        #       get misread as a binary truth-table row.
        cond = _conditional_from_text(body)
        if cond is not None:
            cexpr, cname, cdesc = cond
            try:
                circuit, info = self.boolean_synth.build(cexpr, target_gates=target)
            except BooleanParseError as e:
                if target:
                    return self._impossible_target_answer(cname, target, str(e))
                circuit = info = None
            if circuit is not None and info.get('gate_count', 0) > 0:
                simp = info.get('simplified', cexpr)
                simp_note = ('' if info.get('is_simplest')
                             else f' Simplifies to **{simp}**.')
                return {
                    'answer': f'{cdesc} Boolean: `{cexpr}`.{simp_note} '
                              f"Built {info['gate_count']} logic gate"
                              f"{'s' if info['gate_count'] != 1 else ''}, "
                              f"{info['wire_count']} wires.",
                    'confidence': 0.9,
                    'circuit': circuit, 'info': info, 'details': info,
                    'suggestions': ["Press RUN to simulate."],
                }

        # 1c.6  Explicit row-by-row truth-table spec
        #       ("input 1 gives 0 and input 0 gives 1",
        #        "when A=0 B=1 output is 1, when A=1 B=0 output is 1").
        #       Tried before _logic_from_phrasing so the word "and" in
        #       these specs doesn't cause an AND false-match.
        row_spec = _row_spec_from_text(body)
        if row_spec is not None:
            expr, name_rs, desc_rs = row_spec
            # Identity ("A" or "(A)"  -  single-input passthrough) collapses
            # to a wire with no gates; force `X & X` so the user gets a
            # buildable 1-gate circuit instead of a degenerate identity.
            stripped = re.sub(r'[()\s]', '', expr or '')
            if re.fullmatch(r'[A-Za-z]\w*', stripped):
                expr = f'{stripped} & {stripped}'
            try:
                circuit, info = self.boolean_synth.build(
                    expr, target_gates=target)
            except BooleanParseError as e:
                if target:
                    return self._impossible_target_answer(name_rs, target, str(e))
                circuit = info = None
            if circuit is not None and info.get('gate_count', 0) > 0:
                simp = info.get('simplified', expr)
                simp_note = ("" if info.get('is_simplest')
                             else f" Simplifies to **{simp}**.")
                return {
                    'answer':     f"{desc_rs} Boolean: `{expr}`.{simp_note} "
                                  f"Built {info['gate_count']} logic gate"
                                  f"{'s' if info['gate_count'] != 1 else ''}, "
                                  f"{info['wire_count']} wires.",
                    'confidence': 0.9,
                    'circuit':    circuit,
                    'info':       info,
                    'details':    info,
                    'suggestions': [
                        "Press RUN to simulate.",
                        "Add 'using only NAND' for the universal-gate form.",
                    ],
                }

        # 1c.7  Ordinal input references ("first input on, second input off")
        ordinal = _ordinal_row_spec(body)
        if ordinal is not None:
            expr, _, desc_ord = ordinal
            try:
                circuit, info = self.boolean_synth.build(expr, target_gates=target)
            except BooleanParseError as e:
                if target:
                    return self._impossible_target_answer('ordinal spec', target, str(e))
                circuit = info = None
            if circuit is not None and info.get('gate_count', 0) > 0:
                simp = info.get('simplified', expr)
                simp_note = '' if info.get('is_simplest') else f' Simplifies to **{simp}**.'
                return {
                    'answer': f"{desc_ord} Boolean: `{expr}`.{simp_note} "
                              f"Built {info['gate_count']} logic gate"
                              f"{'s' if info['gate_count']!=1 else ''}, "
                              f"{info['wire_count']} wires.",
                    'confidence': 0.85,
                    'circuit': circuit, 'info': info, 'details': info,
                    'suggestions': ["Press RUN to simulate."],
                }

        # 1d. Natural-language behaviour for a single output ("output is high
        #     when both A and B are 1", "exactly one of A and B", "majority
        #     of three"). Minterm rows are tried first because phrases like
        #     "1 for 00 and 11" contain the word "and" which the phrasing
        #     matcher would otherwise misread.
        nl = (_value_set_from_text(body)
              or _conditional_from_text(body)
              or _minterms_from_text(body)
              or _logic_from_phrasing(body))
        if nl is not None:
            expr, nl_name, nl_desc = nl
            try:
                circuit, info = self.boolean_synth.build(expr, target_gates=target)
            except BooleanParseError as e:
                if target:
                    return self._impossible_target_answer(nl_name, target, str(e))
                circuit = info = None
            if circuit is not None and info.get('gate_count', 0) > 0:
                simp = info.get('simplified', expr)
                simp_note = ("" if info.get('is_simplest')
                             else f" Simplifies to **{simp}**.")
                return {
                    'answer':     f"{nl_desc} Boolean: `{expr}`.{simp_note} "
                                  f"Built {info['gate_count']} logic gate"
                                  f"{'s' if info['gate_count'] != 1 else ''}, "
                                  f"{info['wire_count']} wires.",
                    'confidence': 0.8,
                    'circuit':    circuit,
                    'info':       info,
                    'details':    info,
                    'suggestions': [
                        "Press RUN to simulate.",
                        "Try 'using only NAND' for the universal-gate form.",
                    ],
                }

        # 2. Try to extract a boolean expression directly. `body` already has
        #    the restriction phrase stripped  -  just remove leading verbs.
        cleaned = re.sub(
            r'^\s*(please\s+)?(build|make|design|create|construct|generate|'
            r'give me|show me|i want|i need|made)'
            r'\s*(a|an|the)?\s*(circuit\s+for\s+)?', '', body, flags=re.I)
        cleaned = cleaned.strip().rstrip('.?!')

        try:
            circuit, info = self.boolean_synth.build(cleaned,
                                                     target_gates=target)
            n_logic = info.get('gate_count', 0)
            if n_logic == 0:
                # Identity expression like "A"  -  boolean_synth returns a wire
                # but no real logic gate. That's not a meaningful "build".
                raise ValueError(f"`{cleaned}` is not a logic expression")
            return {
                'answer':     f"Built circuit from `{cleaned}`{target_label}  -  "
                              f"{n_logic} logic gate"
                              f"{'s' if n_logic != 1 else ''}, "
                              f"{info['wire_count']} wires.",
                'confidence': 0.85,
                'circuit':    circuit,
                'info':       info,
                'details':    info,
                'suggestions': [
                    "Press RUN to simulate the new circuit.",
                    "Ask for 'NAND only' to convert to universal gates.",
                ],
            }
        except BooleanParseError as e:
            # The expression parsed, but the requested gate set can't
            # represent it (e.g. "NOT from OR"  -  OR alone is monotonic).
            if target:
                return self._impossible_target_answer(cleaned, target, str(e))
            ml = self._try_ml_truth_table(text, target, target_label)
            if ml is not None:
                return ml
            return self._not_recognised_answer(text, str(e))
        except Exception as e:
            ml = self._try_ml_truth_table(text, target, target_label)
            if ml is not None:
                return ml
            return self._not_recognised_answer(text, str(e))

    # -- ML fallback: trained truth-table predictor --------------------------

    def _try_ml_truth_table(self, text, target, target_label):
        """
        Last-resort strategy: ask the trained NL -> truth-table model to
        extract a function from the text, then synthesise that function via
        Quine-McCluskey. Returns None if the model isn't available or its
        prediction is too weak to trust.
        """
        try:
            from .nl_tt_model import NLTruthTableModel, MODEL_PATH
            import os
            if not os.path.exists(MODEL_PATH):
                return None
            # Cache the model on the instance to avoid reloading every call.
            if not hasattr(self, '_nltt_model'):
                self._nltt_model = NLTruthTableModel.load(MODEL_PATH)
            pred = self._nltt_model.predict(text)
        except Exception:
            return None

        n_in       = pred['n_inputs']
        minterms   = pred['minterms']
        conf_n     = pred['n_inputs_conf']
        conf_cells = pred['mean_cell_conf']
        confidence = conf_n * conf_cells

        # The per-cell logistic regressions are weak compositional models and
        # produce confident-but-wrong answers for many phrasings. Empirically,
        # joint confidence below ~0.85 means the model is largely guessing.
        # Better to admit "couldn't parse" than place a wrong circuit.
        if conf_n < 0.75 or conf_cells < 0.85:
            return None
        if confidence < 0.75:
            return None
        # Reject degenerate constant outputs unless very confident  -  most
        # "couldn't parse" texts will lean toward all-zero predictions.
        if not minterms and confidence < 0.90:
            return None
        if len(minterms) == (1 << n_in) and confidence < 0.90:
            return None

        var_names = ['A', 'B', 'C', 'D'][:n_in]
        if not minterms:
            expr = '0'
        elif len(minterms) == (1 << n_in):
            expr = '1'
        else:
            terms = []
            for m in minterms:
                bits = format(m, f'0{n_in}b')
                lits = [v if b == '1' else f'~{v}'
                        for v, b in zip(var_names, bits)]
                terms.append('(' + ' & '.join(lits) + ')')
            expr = ' | '.join(terms)

        try:
            circuit, info = self.boolean_synth.build(expr, target_gates=target)
        except Exception:
            return None
        simp = info.get('simplified', expr)
        simp_note = ("" if info.get('is_simplest')
                     else f" Simplifies to **{simp}**.")
        return {
            'answer':     (f"Recognised this as a {n_in}-input function "
                           f"(model confidence {confidence:.0%}). Boolean: "
                           f"`{expr}`.{simp_note} Built "
                           f"{info['gate_count']} logic gate"
                           f"{'s' if info['gate_count'] != 1 else ''}, "
                           f"{info['wire_count']} wires."),
            'confidence': round(float(confidence), 3),
            'circuit':    circuit,
            'info':       info,
            'details':    {**info, 'ml_minterms': minterms,
                           'ml_n_inputs_conf': conf_n,
                           'ml_cell_conf': conf_cells},
            'suggestions': [
                "Press RUN to simulate.",
                "If the truth table looks wrong, rephrase more explicitly "
                "(e.g. 'output is 1 when A=1 and B=0').",
            ],
        }

    # -- shared "can't build" response helpers --------------------------------

    def _not_recognised_answer(self, text: str, err: str) -> dict:
        named = sorted(set(list(MULTI_OUTPUT_CIRCUITS)
                           + list(KNOWN_CIRCUITS)))
        sample = ', '.join(named[:8])
        return {
            'answer': (
                f"I couldn't build `{text}`. Try one of:\n"
                f"• a known circuit: {sample}\n"
                f"• a bare gate: XOR, NAND, NOR, XNOR (optionally "
                f"'using NAND' / 'using NOR')\n"
                f"• a boolean expression: A & B | ~C"),
            'confidence':  0.2,
            'details':     {'parse_error': err,
                            'available_circuits': named},
            'suggestions': named[:5],
        }

    def _impossible_target_answer(self, what: str, target: list,
                                  err: str) -> dict:
        """
        Returned when the parser understood the request AND the gate-set
        restriction, but the requested set can't represent the function.
        e.g. "NOT from OR"  -  OR alone is monotonic, can't invert.
        """
        gset = '/'.join(target) if target else '?'
        # Suggest a fix the user can paste in.
        if target == ['OR']:
            hint = "OR alone is monotonic  -  it can't invert. Try NOR, NAND, or 'OR and NOT'."
        elif target == ['AND']:
            hint = "AND alone is monotonic  -  it can't invert. Try NAND, NOR, or 'AND and NOT'."
        elif target == ['XOR']:
            hint = "XOR alone isn't universal. Add NOT, or use NAND/NOR only."
        elif target == ['NOT']:
            hint = "NOT alone has no fan-in 2  -  it can't combine signals. Try 'NAND', 'NOR', or 'AND and NOT'."
        else:
            hint = ("That gate set isn't universal for this function. "
                    "Try NAND, NOR, or AND/OR/NOT.")
        return {
            # Flag tells the frontend: we *understood* the request, we just
            # can't satisfy it. Do NOT override this with a local-template
            # build that ignores the gate-set restriction.
            'understood':  True,
            'answer': (
                f"Can't build **{what}** using only {gset}. {hint}"),
            'confidence':  0.7,
            'details':     {'target_gates': target,
                            'reason': err},
            'suggestions': [
                f"{what} using NAND",
                f"{what} using NOR",
                f"{what} using AND, OR and NOT",
            ],
        }

    def _build_multi_output(self, parts, target):
        """
        Build one circuit with shared inputs and several OUTPUT gates.
        `parts` is a list of (label, expression).
        """
        from .boolean_synth import _Builder, parse_expression, _restrict_to, _layout

        b = _Builder()
        gate_count_logic = 0
        for label, expr in parts:
            ast = parse_expression(expr)
            if target:
                ast = _restrict_to(ast, target)
            root_id = b.emit(ast)
            out_id  = b._new_gate('OUTPUT', label=label)
            b._wire(root_id, out_id, 0)

        circuit = {'gates': b.gates, 'wires': b.wires}
        _layout(circuit)

        info = {
            'gate_count':   sum(1 for g in b.gates if g['type'] not in
                                ('INPUT', 'OUTPUT', 'CLOCK')),
            'wire_count':   len(b.wires),
            'input_vars':   [g['label'] for g in b.gates if g['type'] == 'INPUT'
                             and not g.get('label', '').startswith('const_')],
            'outputs':      [lbl for lbl, _ in parts],
            'target_gates': target,
        }
        return circuit, info

    # ── Digital-logic knowledge base ────────────────────────────────────────
    # Polished answers for canonical interview / textbook questions.  Each
    # entry is (pattern, title, body).  First-match wins; patterns are
    # checked in order so put more specific ones first.

    _KB: list = [
        (r'\bnand\b.*\b(universal|complete)|\b(universal|complete)\w*\b.*\bnand\b',
         'NAND universality',
         "NAND is a *universal* gate — every Boolean function can be built using only NANDs.\n\n"
         "• NOT(A)   = A NAND A\n"
         "• AND(A,B) = NOT(A NAND B) = (A NAND B) NAND (A NAND B)\n"
         "• OR(A,B)  = NOT(NOT A) OR NOT(NOT B) = (A NAND A) NAND (B NAND B)  (De Morgan)\n\n"
         "Because {NOT, AND, OR} is itself functionally complete, deriving all three from NAND proves NAND is universal. "
         "NOR is universal by symmetry."),

        (r'\bnor\b.*\b(universal|complete)|\b(universal|complete)\w*\b.*\bnor\b',
         'NOR universality',
         "NOR is universal — like NAND, every Boolean function can be built from NORs alone.\n\n"
         "• NOT(A)   = A NOR A\n"
         "• OR(A,B)  = NOT(A NOR B) = (A NOR B) NOR (A NOR B)\n"
         "• AND(A,B) = (A NOR A) NOR (B NOR B)\n\n"
         "NOR-only design was historically common in CMOS because PMOS pull-up networks favour series transistors."),

        (r"\bde\s*morgan", 'De Morgan\'s laws',
         "De Morgan's two laws:\n"
         "  ¬(A ∧ B) = ¬A ∨ ¬B      i.e.   NOT(A AND B) = (NOT A) OR (NOT B)\n"
         "  ¬(A ∨ B) = ¬A ∧ ¬B      i.e.   NOT(A OR B)  = (NOT A) AND (NOT B)\n\n"
         "They turn AND into OR (and vice-versa) when you push a NOT inside. "
         "Used constantly when re-expressing circuits in NAND-only or NOR-only form."),

        (r'\bpropagation\s+delay\b|\bt_pd\b',
         'Propagation delay',
         "Propagation delay (t_pd) is the time from an input transition until the corresponding output transition reaches a valid logic level. "
         "For a circuit it is the *worst-case longest path* through the gates from inputs to outputs.\n\n"
         "• Used to compute the maximum clock frequency: f_max ≈ 1 / (t_pd + t_setup + t_clk-q).\n"
         "• Distinct from contamination delay (t_cd) — the shortest path, which sets hold-time slack."),

        (r'\b(race\s*condition|race\s*hazard|critical\s*race)',
         'Race condition',
         "A race condition in sequential logic occurs when two inputs change at nearly the same time and the final state depends on which change *wins*.\n\n"
         "Classical example: SR latch driven so that S and R both go 1→0; the latch may end in 0, 1, or oscillate. "
         "Mitigations:\n"
         "  • Use master-slave or edge-triggered flip-flops instead of latches.\n"
         "  • Synchronous design — all signals change on the clock edge.\n"
         "  • Avoid logic where two paths re-converge after asymmetric delays."),

        (r'\b(setup|hold)\s+time\b',
         'Setup & hold time',
         "Setup time (t_su): the data input must be stable for t_su BEFORE the active clock edge.\n"
         "Hold time  (t_h):  the data input must remain stable for t_h AFTER the active clock edge.\n\n"
         "Violating setup → the flip-flop may go metastable. Violating hold → the latched value is corrupted by the next-cycle data."),

        (r'\b(metastab|metastability)',
         'Metastability',
         "When a flip-flop samples an input that is changing inside the setup/hold window, it can enter a metastable state — an indeterminate voltage between 0 and 1 that resolves to either value after an unpredictable delay. "
         "Mitigated by:\n"
         "  • Synchroniser chains (2- or 3-stage FF pipeline) — exponentially reduce MTBF.\n"
         "  • Slower clock relative to the metastability resolution time τ."),

        (r'\b(latch).*\bflip[\s-]?flop\b|\bflip[\s-]?flop\b.*\b(latch)|difference.*latch.*flip|flip.*vs.*latch',
         'Latch vs flip-flop',
         "Latch: level-sensitive — the output follows the input the whole time the enable signal is asserted.\n"
         "Flip-flop: edge-triggered — the output samples the input only at the rising (or falling) clock edge.\n\n"
         "Flip-flops are race-immune, easier to time-analyse, and preferred for synchronous design. Latches are smaller (~½ the transistors) and used for retiming or low-power clock-gating."),

        (r'\b(master[\s-]?slave|master\s+slave\s+flip)',
         'Master-slave flip-flop',
         "Two latches in series with inverted enables:\n"
         "  • The MASTER latch is transparent while CLK = 0; it captures D.\n"
         "  • The SLAVE  latch is transparent while CLK = 1; it forwards the master's value to Q.\n\n"
         "Net effect: edge-triggered behaviour. Q updates on the 0→1 clock transition. Eliminates the latch's transparency-window race condition."),

        (r'\b(karnaugh|k[\s-]?map)\b',
         'Karnaugh map',
         "A K-map is a 2-D grid laid out in Gray code so adjacent cells differ in exactly one variable. "
         "Used to minimise Boolean expressions visually:\n\n"
         "1. Fill each cell with the function value (0/1/X).\n"
         "2. Group 1-cells in rectangles of size 1, 2, 4, 8… (must be power of two).\n"
         "3. Each group becomes one product term — variables that change inside the group are eliminated.\n\n"
         "Equivalent to the algebraic Quine-McCluskey algorithm but tractable by hand up to ~4 variables."),

        (r'\b(sop|sum\s*of\s*products)\b',
         'Sum of Products (SOP)',
         "SOP form: f = Σ (minterms where f = 1). Each minterm is an AND of all input variables (negated where the input is 0). "
         "Example for f(A,B) = 1 on inputs 01 and 10:  f = A'·B + A·B'.\n\n"
         "Canonical SOP is the disjunction of every minterm of the function; minimised SOP groups adjacent minterms via K-map or Quine-McCluskey."),

        (r'\b(pos|product\s*of\s*sums)\b',
         'Product of Sums (POS)',
         "POS form: f = Π (maxterms where f = 0). Each maxterm is an OR of all variables (negated where the input is 1). "
         "Dual to SOP — useful when the function has more 1s than 0s, because POS will have fewer terms."),

        (r'\b(combinational|combinatorial)\b.*\bsequential\b|\bsequential\b.*\bcombinational',
         'Combinational vs sequential circuits',
         "Combinational: output depends only on current inputs. No memory. Examples: adders, multiplexers, decoders.\n"
         "Sequential:    output depends on current inputs AND past history (state). Built from flip-flops or latches plus combinational logic. Examples: counters, FSMs, registers."),

        (r'\b(mealy|moore)\b',
         'Mealy vs Moore machines',
         "Both are FSMs.\n"
         "  • Moore — outputs depend only on the current state. Cleaner, output is glitch-free, but typically uses more states.\n"
         "  • Mealy — outputs depend on (state, input). Fewer states, responds in the same cycle, but more prone to combinational glitches."),

        (r'\b(half|full)\s+adder\b',
         'Adders',
         "Half adder:  A,B → Sum = A⊕B, Carry = A·B.  Two gates (XOR + AND).\n"
         "Full adder:  A,B,Cin → Sum = A⊕B⊕Cin, Cout = (A·B) + (Cin·(A⊕B)).\n\n"
         "Ripple-carry n-bit adder chains n full adders; carry propagates through every FA, delay O(n). "
         "Carry-lookahead, carry-save, and Kogge-Stone adders reduce this to O(log n) or O(1) latency."),

        (r'\b(mux|multiplexer)\b',
         'Multiplexer',
         "A 2ⁿ:1 mux selects one of 2ⁿ data inputs via n select lines.\n"
         "  2:1: Y = S'·D0 + S·D1\n"
         "  4:1: Y = S1'S0'·D0 + S1'S0·D1 + S1S0'·D2 + S1S0·D3\n\n"
         "Muxes are functionally complete (any Boolean function of n vars can be implemented with one 2ⁿ:1 mux)."),

        (r'\b(decoder|encoder)\b',
         'Decoders & encoders',
         "n-to-2ⁿ decoder: drives exactly one of 2ⁿ outputs high, selected by the n-bit input.\n"
         "  Used inside memories (address → wordline) and as the heart of demultiplexers.\n\n"
         "Priority encoder: 2ⁿ-to-n encoder that, when multiple inputs are high, emits the index of the highest-priority asserted input. "
         "Critical in interrupt controllers."),

        (r'\b(parity)\b',
         'Parity generator/checker',
         "Even-parity bit P over n data bits = XOR of all bits → forces the total number of 1s including P to be even.\n"
         "Odd parity inverts it (P = XNOR-chain).\n\n"
         "Detects any single-bit error but not double-bit; superseded by Hamming codes for stronger correction."),

        (r'\b(carry\s*look[\s-]?ahead|cla)\b',
         'Carry-lookahead adder',
         "For each bit i: Generate Gi = Ai·Bi, Propagate Pi = Ai⊕Bi. Then\n"
         "  Ci+1 = Gi + Pi·Ci\n"
         "Flattened: C1 = G0 + P0·C0; C2 = G1 + P1·G0 + P1·P0·C0; …\n"
         "Carry propagation collapses from O(n) ripple to O(log n) with hierarchical CLA blocks."),

        (r'\b(tri[\s-]?state|three[\s-]?state)\b',
         'Tri-state buffer',
         "A buffer with an enable input. When EN = 1 it passes the input to the output; when EN = 0 it presents high-impedance (Z) — effectively disconnecting from the bus.\n"
         "Tri-state buffers let multiple drivers share a single wire (bus); only one is enabled at a time."),

        # ── Individual gates ─────────────────────────────────────────────────
        # Permissive — match "what is xor", "explain xor", "xor gate", "what's an or", etc.
        (r'\b(what.{0,5}is|explain|describe|tell\s+me\s+about|how.{0,5}does|define|teach\s+me|what\'s)\s.{0,20}\band(\s+gate)?\b|\band\s+gate\b',
         'AND gate',
         "AND outputs 1 only when **all** inputs are 1.\n\n"
         "Truth table (2-input):\n"
         "  A B │ Y\n"
         "  0 0 │ 0\n"
         "  0 1 │ 0\n"
         "  1 0 │ 0\n"
         "  1 1 │ 1\n\n"
         "Boolean: Y = A·B. Symbol: D-shape with flat back and semicircular front. Used as the conjunction primitive in every Boolean expression."),

        (r'\b(what.{0,5}is|explain|describe|tell\s+me\s+about|how.{0,5}does|define|teach\s+me|what\'s)\s.{0,20}\bor(\s+gate)?\b|\bor\s+gate\b',
         'OR gate',
         "OR outputs 1 when **any** input is 1.\n\n"
         "Truth table (2-input):\n"
         "  A B │ Y\n"
         "  0 0 │ 0\n"
         "  0 1 │ 1\n"
         "  1 0 │ 1\n"
         "  1 1 │ 1\n\n"
         "Boolean: Y = A + B. Distinctive shape: curved concave back, convex top/bottom, pointed tip."),

        (r'\b(what.{0,5}is|explain|describe|tell\s+me\s+about|how.{0,5}does|define|teach\s+me|what\'s)\s.{0,20}\bnot(\s+gate)?\b|\bnot\s+gate\b|\binverter\b',
         'NOT gate (inverter)',
         "NOT inverts its single input.\n\n"
         "  A │ Y\n"
         "  0 │ 1\n"
         "  1 │ 0\n\n"
         "Boolean: Y = ¬A (or A'). Symbol: triangle pointing right with a small bubble at the tip — the triangle is the buffer, the bubble is the inversion. Without the bubble it's a BUF (non-inverting buffer)."),

        (r'\b(what.{0,5}is|explain|describe|tell\s+me\s+about|how.{0,5}does|define|teach\s+me|what\'s)\s.{0,20}\bnand(\s+gate)?\b|\bnand\s+gate\b',
         'NAND gate',
         "NAND = NOT AND. Outputs 0 only when **all** inputs are 1; otherwise outputs 1.\n\n"
         "  A B │ Y\n"
         "  0 0 │ 1\n"
         "  0 1 │ 1\n"
         "  1 0 │ 1\n"
         "  1 1 │ 0\n\n"
         "Boolean: Y = ¬(A·B). NAND is **functionally complete** — every Boolean function can be built using only NAND gates. Cheapest gate in CMOS (4 transistors)."),

        (r'\b(what.{0,5}is|explain|describe|tell\s+me\s+about|how.{0,5}does|define|teach\s+me|what\'s)\s.{0,20}\bnor(\s+gate)?\b|\bnor\s+gate\b',
         'NOR gate',
         "NOR = NOT OR. Outputs 1 only when **all** inputs are 0.\n\n"
         "  A B │ Y\n"
         "  0 0 │ 1\n"
         "  0 1 │ 0\n"
         "  1 0 │ 0\n"
         "  1 1 │ 0\n\n"
         "Boolean: Y = ¬(A + B). Also functionally complete. Used to build SR latches."),

        (r'\b(what.{0,5}is|explain|describe|tell\s+me\s+about|how.{0,5}does|define|teach\s+me|what\'s)\s.{0,20}\bxor(\s+gate)?\b|\bxor\s+gate\b|^\s*xor\s*\??\s*$',
         'XOR gate (exclusive OR)',
         "XOR outputs 1 when its inputs **differ**.\n\n"
         "  A B │ Y\n"
         "  0 0 │ 0\n"
         "  0 1 │ 1\n"
         "  1 0 │ 1\n"
         "  1 1 │ 0\n\n"
         "Boolean: Y = A ⊕ B = A·B' + A'·B. Key building block of adders (Sum = A⊕B⊕Cin), parity generators, and Gray-code converters. Distinctive shape is OR-gate + extra back arc."),

        (r'\b(what.{0,5}is|explain|describe|tell\s+me\s+about|how.{0,5}does|define|teach\s+me|what\'s)\s.{0,20}\bxnor(\s+gate)?\b|\bxnor\s+gate\b|\bequivalence\s+gate\b',
         'XNOR gate (equivalence)',
         "XNOR outputs 1 when its inputs are **equal** — it's the NOT of XOR.\n\n"
         "  A B │ Y\n"
         "  0 0 │ 1\n"
         "  0 1 │ 0\n"
         "  1 0 │ 0\n"
         "  1 1 │ 1\n\n"
         "Boolean: Y = A ⊙ B = A·B + A'·B'. Used in equality comparators and parity checkers."),

        (r'\bbuf(fer)?\s+gate\b|\bwhat\s+is\s+(a\s+)?buf\b|\bnon[-\s]?inverting\s+buffer\b',
         'Buffer (BUF)',
         "Buffer passes the input straight through: Y = A. Same shape as NOT but without the inversion bubble.\n\n"
         "Used for signal regeneration on long wires, fan-out boosting, and clock-tree balancing. Also the basis of tri-state buffers when an enable input is added."),

        # ── Sequential circuits ──────────────────────────────────────────────
        (r'\b(what.{0,5}is|explain|describe|tell\s+me\s+about|how.{0,5}does|define)\s.{0,20}\b(a\s+|an\s+)?flip[\s-]?flop\b',
         'Flip-flop',
         "A flip-flop is a 1-bit edge-triggered memory element — the basic storage cell of synchronous digital logic. "
         "It samples its data input on each active clock edge and holds that value until the next edge.\n\n"
         "Four common types:\n"
         "  • D-FF   — Q(next) = D    (delays input by one clock cycle)\n"
         "  • JK-FF  — toggles when J=K=1; otherwise behaves like SR (no invalid state)\n"
         "  • T-FF   — toggles Q on every edge when T=1\n"
         "  • SR-FF  — set/reset (raw S=R=1 is invalid)\n\n"
         "Used as the storage element in registers, counters, and finite-state machines."),

        (r'\bsr\s+(latch|flip)\b|\bs[\s-]?r\s+(latch|flip[\s-]?flop)\b',
         'SR latch',
         "Set-Reset latch — the simplest 1-bit memory. Two cross-coupled NOR gates (or NANDs with active-low S̄/R̄).\n\n"
         "  S R │ Q   Q̅\n"
         "  0 0 │ Q   Q̅   (hold)\n"
         "  0 1 │ 0   1   (reset)\n"
         "  1 0 │ 1   0   (set)\n"
         "  1 1 │ 0   0   (invalid — both outputs forced 0; race when freed)"),

        (r'\bd\s+(latch|flip[\s-]?flop)\b',
         'D flip-flop / D latch',
         "D latch: level-sensitive. Q = D while the enable is high; Q holds when enable goes low. One D input avoids the S=R=1 invalid state of the SR latch.\n\n"
         "D flip-flop: edge-triggered version. On every active clock edge, samples D and presents it on Q for the next cycle. The basic building block of synchronous registers."),

        (r'\bjk\s+(flip[\s-]?flop|latch)\b|\bj[\s-]?k\s+(flip[\s-]?flop|latch)\b',
         'JK flip-flop',
         "Universal flip-flop, no invalid state.\n\n"
         "  J K │ Q(next)\n"
         "  0 0 │ Q       (hold)\n"
         "  0 1 │ 0       (reset)\n"
         "  1 0 │ 1       (set)\n"
         "  1 1 │ Q̅       (toggle)\n\n"
         "When J=K=1 in a master-slave or edge-triggered design, Q toggles each clock edge — the basis of asynchronous counters."),

        (r'\bt\s+flip[\s-]?flop\b|\btoggle\s+flip',
         'T flip-flop (toggle)',
         "Single-input flip-flop: T=1 toggles Q on every clock edge, T=0 holds. Equivalent to a JK with J and K tied together. Used to build ripple counters (each T-FF divides frequency by 2)."),

        (r'\bshift\s+register\b',
         'Shift register',
         "Chain of D flip-flops with the Q of each driving the D of the next, all sharing one clock. Each rising edge shifts the data one position.\n\n"
         "Variants:\n"
         "  • SISO — serial in, serial out (delay line)\n"
         "  • SIPO — serial in, parallel out (UART deserialiser)\n"
         "  • PISO — parallel in, serial out (UART serialiser)\n"
         "  • PIPO — parallel in/out (synchronous register file)"),

        (r'\b(ring|johnson)\s+counter\b',
         'Ring & Johnson counters',
         "Ring counter: shift register where the last Q feeds back to the first D. n flip-flops → n unique one-hot states.\n\n"
         "Johnson (twisted-ring) counter: same loop but feeds back the *inverted* Q. n flip-flops → 2n unique states. Glitch-free decoding, used for low-power counters and stepper-motor drivers."),

        (r'\b(synchronous|asynchronous)\s+counter\b|\bripple\s+counter\b',
         'Synchronous vs asynchronous counters',
         "Async (ripple) counter: each flip-flop is clocked by the previous Q. Simple, but propagation delays accumulate → high-bit transitions appear later than low bits.\n\n"
         "Sync counter: all FFs share the master clock; combinational logic decides which FFs toggle each edge. More gates, but every output updates simultaneously — suitable for high-speed and as state registers in FSMs."),

        # ── Number systems & arithmetic ─────────────────────────────────────
        (r'\b(2|two)[\'s]?\s+complement\b',
         "Two's complement",
         "Standard signed-integer representation. For n bits, the value of bits b_{n-1}…b_0 is:\n"
         "    -b_{n-1}·2^{n-1} + Σ b_i·2^i\n\n"
         "Negation: invert all bits then add 1. Range for n bits: −2^{n-1} … 2^{n-1}−1. Addition/subtraction use the *same* binary adder — no separate sign handling. Universal in modern CPUs."),

        (r'\b(bcd|binary[\s-]?coded[\s-]?decimal)\b',
         'BCD (binary-coded decimal)',
         "Each decimal digit (0–9) is encoded in 4 bits: 0000–1001. Codes 1010–1111 are invalid.\n\n"
         "BCD → 7-segment decoders drive 7-segment displays directly. Banking and calculator hardware historically used BCD arithmetic because exact decimal rounding matters."),
        (r'\bhazard|glitch\b',
         'Hazards',
         "A logic hazard is a brief, unintended output transition caused by uneven gate delays.\n"
         "  • Static-1 hazard: output should stay 1 but momentarily dips to 0.\n"
         "  • Static-0 hazard: stays 0 but blips to 1.\n"
         "  • Dynamic hazard:   multiple unintended transitions during one logical change.\n\n"
         "Static-1 hazards are removed by adding redundant prime implicants to the SOP (the 'consensus' term)."),
    ]

    def _try_knowledge_base(self, q: str):
        for pat, title, body in self._KB:
            if re.search(pat, q, re.IGNORECASE):
                return {'answer': f"**{title}**\n\n{body}",
                        'confidence': 0.95,
                        'details': {'kb_match': title}}
        return None

    def _answer_general(self, question: str, circuit: dict) -> dict:
        # Try the digital-logic KB first — handles canonical SDE/analyst questions.
        kb = self._try_knowledge_base(question)
        if kb is not None:
            return kb

        gates = circuit.get('gates', [])
        logic = [g for g in gates if g['type'].upper() not in ('INPUT','CLOCK','OUTPUT')]
        return {
            'answer': (f"I can answer questions about this {len(logic)}-gate circuit, "
                       "or about digital-logic concepts (NAND universality, propagation delay, "
                       "De Morgan, K-maps, latches vs flip-flops, race conditions, hazards, …). "
                       "Try one of the suggestions below."),
            'confidence': 0.5,
            'details': {'circuit_size': len(gates)},
            'suggestions': [
                'What is propagation delay?',
                'Explain NAND universality.',
                'Difference between latch and flip-flop?',
                'How can I minimize this circuit?',
                'What gates are used?',
                'What is the output when A=1, B=0?',
            ]
        }