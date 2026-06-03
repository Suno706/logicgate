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
    r'(?:nand|nor|xnor|xor|inverter|inv|and|or|not)'
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
    m = _RESTRICTION_PREFIX_RE.search(text)
    if not m:
        m = _RESTRICTION_SUFFIX_RE.search(text)
    if not m:
        return None, text

    phrase = m.group(0).lower()
    if 'aoi' in phrase or 'and-or-not' in phrase:
        target = ['AND', 'OR', 'NOT']
    else:
        tokens = re.findall(_GATE_TOKEN_RE, phrase, flags=re.IGNORECASE)
        # "and" / "or" can be either a gate name OR a list separator. When
        # they sit between two other gate tokens ("NAND and NOT", "OR and
        # NOT") they're a separator  -  drop them. Only at the start/end of
        # the token list do we treat them as actual gates.
        filtered = []
        for i, tok in enumerate(tokens):
            if (tok.lower() in ('and', 'or')
                    and 0 < i < len(tokens) - 1):
                continue
            filtered.append(tok)
        # Dedupe while preserving order.
        seen, target = set(), []
        for tok in filtered:
            g = _GATE_TOKEN_MAP[tok.lower()]
            if g not in seen:
                seen.add(g)
                target.append(g)
        if not target:
            return None, text

    stripped = text[:m.start()] + text[m.end():]
    return target, stripped.strip()

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
    (r'\bhalfadder\b',        'half adder'),
    (r'\bfulladder\b',        'full adder'),
    (r'\bhalfsubtractor\b',   'half subtractor'),
    (r'\bfullsubtractor\b',   'full subtractor'),
    (r'\bsubtracter\b',       'subtractor'),
    (r'\bsubstractor\b',      'subtractor'),
    (r'\bsubstracter\b',      'subtractor'),
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
]


def _normalize_request_text(text: str) -> str:
    """
    Apply alias / typo rules to the user's request so subsequent matchers
    see a canonical phrasing. Case-insensitive replacement that preserves
    the surrounding text.
    """
    out = text
    for pattern, repl in _ALIAS_RULES:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)

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
    """English description -> (expression, name, description) or None."""
    t = ' ' + text.lower().strip() + ' '

    # If the text says "three inputs"/"four lines", expand vs to that size.
    n_explicit = _count_inputs_in_text(text)
    detected = _nl_detect_vars(text)
    if n_explicit and n_explicit > len(detected):
        vs = (['A', 'B', 'C', 'D', 'E'])[:n_explicit]
    else:
        vs = detected or ['A', 'B']

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
    # Only match when there is exactly one variable and clear inversion intent.
    if (has('invert', 'inverse', 'complement', 'negate', 'negation')
            or re.search(r'\bnot\s+\w+\b', t)):
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

    # Per-output set of minterm rows that produce 1.
    on_rows = [set() for _ in range(n_out)]

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
        if mts and outs:
            saw_clause = True
            for mt in mts:
                idx = int(mt, 2)
                for oi in outs:
                    on_rows[oi].add(idx)
    if not saw_clause:
        return None

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
        intent = self._classify_intent(question_lower)

        # Extract any input values mentioned in question
        input_overrides = self._extract_inputs(question_lower)

        if intent == 'build':
            return self.build_from_text(question)

        if intent == 'output_query' or intent == 'input_effect':
            return self._answer_output_query(question, circuit, input_overrides)

        elif intent == 'gate_count':
            return self._answer_gate_count(circuit)

        elif intent == 'gate_type':
            return self._answer_gate_type(question, circuit)

        elif intent == 'minimize':
            return self._answer_minimize(circuit)

        elif intent == 'fault_check':
            return self._answer_fault_check(circuit)

        elif intent == 'what_if':
            return self._answer_what_if(question, circuit)

        elif intent == 'explain':
            return self._answer_explain(circuit)

        else:
            return self._answer_general(question, circuit)

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
        ml = self._get_ml_intent()
        if ml is not None:
            intent, conf = ml.classify(q)
            if conf >= getattr(ml, 'LOW_CONF', 0.30):
                return intent

        # Regex fallback (legacy).
        scores = {}
        for intent, patterns in self.patterns.items():
            score = sum(1 for p in patterns if re.search(p, q))
            if score > 0:
                scores[intent] = score
        if not scores:
            return 'general'
        return max(scores, key=scores.get)

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

    def _answer_explain(self, circuit: dict) -> dict:
        gates   = circuit.get('gates', [])
        wires   = circuit.get('wires', [])
        logic   = [g for g in gates if g['type'].upper() not in ('INPUT','CLOCK','OUTPUT')]
        inputs  = [g for g in gates if g['type'].upper() in ('INPUT','CLOCK')]
        outputs = [g for g in gates if g['type'].upper() == 'OUTPUT']

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
            r'(a|an|the)?\s*(circuit\s+for\s+)?', '', body, flags=re.I)
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
            r'(a|an|the)?\s*(circuit\s+for\s+)?', '', body, flags=re.I).strip().rstrip('.?!')
        looks_like_expr = (
            direct_body
            and not re.search(r'\b(when|if|for|while|unless|only)\b', direct_body, re.I)
            and not re.search(r'\b\d{2,}\b', direct_body)   # no "011" minterms
            and not re.search(r'=\s*[01]', direct_body)     # no "A=1"
        )
        if looks_like_expr:
            try:
                circuit, info = self.boolean_synth.build(
                    direct_body, target_gates=target)
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
        nl = _minterms_from_text(body) or _logic_from_phrasing(body)
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

    def _answer_general(self, question: str, circuit: dict) -> dict:
        gates = circuit.get('gates', [])
        logic = [g for g in gates if g['type'].upper() not in ('INPUT','CLOCK','OUTPUT')]
        return {
            'answer': f"I can answer questions about this {len(logic)}-gate circuit. Try asking: "
                      "'What is the output?', 'How many gates?', 'Any faults?', 'How to minimize?', or 'Explain this circuit.'",
            'confidence': 0.5,
            'details': {'circuit_size': len(gates)},
            'suggestions': [
                'What is the output when A=1, B=0?',
                'Are there any faults in this circuit?',
                'How can I minimize this circuit?',
                'Explain this circuit.',
                'What gates are used?'
            ]
        }