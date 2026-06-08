"""
Programmatic dataset of (question_text, intent_label) pairs.

We use templates with slot-fills to produce a few thousand realistic phrasings
without paying any LLM. The labels match the intents handled by
QuestionSolver.solve().

Intents
-------
  build            "build a half adder", "create XOR using NAND", "Y=1 when A=1"
  output_query     "what is the output", "compute the output for A=1 B=0"
  gate_count       "how many gates", "count of components", "number of NOR gates"
  gate_type        "what gates are used", "which types are in this circuit"
  minimize         "minimize this", "fewer gates please", "reduce the circuit"
  fault_check      "any errors", "is this correct", "check for faults"
  what_if          "what if I change AND to NAND", "replace the OR with XOR"
  explain          "what does this circuit do", "explain how it works"
  input_effect     "what happens when A=1", "if I set B to 0"
"""
from __future__ import annotations
import itertools
import random


# -- Slot vocabularies ----------------------------------------------------------
VERBS_BUILD = [
    'build', 'make', 'design', 'create', 'construct', 'generate',
    'give me', 'show me', 'draw', 'wire up', 'i want', 'i need',
    'put together', 'synthesize', 'assemble', 'lay out', 'sketch',
    'render', 'produce', 'plot', 'set up', 'implement',
]
ARTICLES   = ['', 'a ', 'an ', 'the ', 'some ', 'this ']
CIRCUITS   = [
    # ── Arithmetic
    'half adder', 'full adder', '4-bit adder', '8-bit adder', '16-bit adder',
    '2-bit adder', '3-bit adder', 'ripple carry adder', 'carry-lookahead adder',
    'half subtractor', 'full subtractor', '4-bit subtractor',
    'binary multiplier', '2-bit multiplier',

    # ── Multiplexers / demuxes
    '2-to-1 mux', '4-to-1 mux', '8-to-1 mux', '16-to-1 mux',
    '1-to-2 demux', '1-to-4 demux', '1-to-8 demux',

    # ── Decoders / encoders
    '2-to-4 decoder', '3-to-8 decoder', '4-to-16 decoder',
    'BCD to 7-segment decoder', 'BCD decoder',
    '4-to-2 encoder', '8-to-3 encoder', 'priority encoder',

    # ── Comparators
    'comparator', 'magnitude comparator', '2-bit comparator',
    '4-bit comparator', 'equality comparator',

    # ── Sequential / storage
    'SR latch', 'D latch', 'gated D latch',
    'D flip-flop', 'JK flip-flop', 'T flip-flop', 'master-slave flip-flop',
    'edge-triggered D flip-flop',
    'shift register', 'SIPO shift register', 'PIPO shift register',
    'ring counter', 'Johnson counter',
    '4-bit register', '8-bit register',
    'mod-8 counter', 'mod-10 counter', 'BCD counter',
    'up counter', 'down counter', 'up-down counter',
    'asynchronous counter', 'synchronous counter',

    # ── Misc combinational
    'parity generator', 'odd parity generator', 'even parity generator',
    'parity checker', 'majority voter', '3-input majority circuit',
    'XOR gate', 'XNOR gate', 'NAND gate', 'NOR gate',
    'AND gate', 'OR gate', 'NOT gate',
    'buffer', 'tristate buffer',

    # ── ALU bits
    '1-bit ALU', '4-bit ALU', 'adder-subtractor',

    # ── Combinational tasks (NL phrasings)
    'circuit that outputs 1 when all inputs are 1',
    'circuit that outputs 1 when any input is 1',
    'circuit that detects when exactly two inputs are 1',
    'circuit that outputs 1 for odd parity',
    'circuit that outputs 1 when A equals B',
    'circuit that outputs 1 when A is greater than B',
    'circuit that detects 101 pattern',
    'voting circuit for 3 inputs',
]
GATE_SETS  = ['NAND', 'NOR', 'AOI', 'AND-OR-NOT', 'AND-NOT', 'OR-NOT',
              'NAND only', 'NOR only', 'universal NAND', 'universal NOR']
EXPRESSIONS= [
    'A and B', 'A or B', 'not A', 'A xor B', 'A and not B', 'not A or B',
    'A & B | ~C', '(A | B) & ~C', 'A ^ B ^ C', '~(A & B)', '~(A | B)',
    'A & B & C', 'A | B | C', '(A ^ B) & C', '~A & ~B & ~C',
    '(A | B) & (C | D)', 'A ^ B ^ C ^ D', '(A & B) | (C & D)',
    'A nand B', 'A nor B', '(A xor B) or C', 'A implies B',
    'not (A or B)', 'A and B and C', '(not A) and B', 'A or not B',
]

VARS       = ['A', 'B', 'C', 'D', 'X', 'Y', 'Z']

# -- Templates -> labelled examples ----------------------------------------------

def _build_samples():
    out = []
    # Named circuit, plain
    for v in VERBS_BUILD:
        for art in ARTICLES:
            for c in CIRCUITS:
                out.append((f'{v} {art}{c}', 'build'))
    # Named + restriction
    for v in VERBS_BUILD[:6]:
        for c in CIRCUITS[:14]:
            for gs in GATE_SETS:
                out.append((f'{v} a {c} using only {gs}', 'build'))
                out.append((f'{v} {c} with {gs}', 'build'))
                out.append((f'{v} a {c} using {gs}', 'build'))
                out.append((f'{c} from {gs} gates', 'build'))
    # Plain boolean expressions
    for v in VERBS_BUILD[:6]:
        for e in EXPRESSIONS:
            out.append((f'{v} {e}', 'build'))
            out.append((f'{v} a circuit for {e}', 'build'))
            out.append((f'circuit that computes {e}', 'build'))
    # "Y = 1 when ..." truth-table phrasings
    inputs_phrases = ['A=1 and B=0', 'A=1 B=1', 'A=0 and B=0',
                      'A=1, B=0, C=1', 'all inputs are 1', 'all are zero',
                      'exactly one input is high', 'majority of inputs are 1']
    for ip in inputs_phrases:
        out.append((f'Y is 1 when {ip}', 'build'))
        out.append((f'output is 1 when {ip}', 'build'))
        out.append((f'output high when {ip}', 'build'))
        out.append((f'build a circuit where Y=1 when {ip}', 'build'))
    # Truth-table minterm specs
    for triple in ['001, 011, 110', '011, 110, 111', '000, 111',
                   '001, 010, 100, 111']:
        out.append((f'output 1 for inputs {triple}', 'build'))
        out.append((f'minterms {triple}', 'build'))
        out.append((f'Y=1 for {triple}, else 0', 'build'))

    # ── Complex specification phrasings ──────────────────────────────────────
    # These are the kinds of queries an analyst / SDE actually types — multi-input
    # circuits with a behaviour described by "when ... then ..." or by counting
    # how many inputs are high.
    INPUT_COUNTS = ['2', '3', '4', '5', '6', 'three', 'four', 'five', 'six']
    BEHAVIOURS = [
        ('when all inputs are 1 the output is 0', 'build'),
        ('when all inputs are high output is 0',  'build'),
        ('when every input is 1 output is 0',     'build'),
        ('output is 0 when all inputs are 1',     'build'),
        ('output is 1 when all inputs are 0',     'build'),
        ('output is 1 when any input is high',    'build'),
        ('output is 1 when at least one input is 1', 'build'),
        ('output is 1 when exactly one input is 1',  'build'),
        ('output is 1 when at least two inputs are 1','build'),
        ('output is 1 when majority of inputs are 1', 'build'),
        ('output is 1 when odd number of inputs are 1','build'),
        ('output is 1 when even number of inputs are 1','build'),
        ('output high when an odd number of inputs are high','build'),
        ('output high when no inputs are high', 'build'),
    ]
    for n in INPUT_COUNTS:
        for behaviour, _ in BEHAVIOURS:
            out.append((f'make a circuit with {n} inputs where {behaviour}', 'build'))
            out.append((f'build a {n}-input circuit where {behaviour}',      'build'))
            out.append((f'design a circuit with {n} inputs, {behaviour}',    'build'))
            out.append((f'{n} input circuit where {behaviour}',              'build'))
            out.append((f'{n}-input circuit, {behaviour}',                   'build'))
            out.append((f'i want a {n}-input gate where {behaviour}',        'build'))
            out.append((f'give me a {n} input thing where {behaviour}',      'build'))
            out.append((f'make an output from {n} inputs when {behaviour.replace("the output is", "output").replace("output is", "")}', 'build'))

    # "make output", "give output", "produce output" — concise specifications
    SHORT_VERBS = ['make a output', 'make an output', 'give me an output',
                   'produce an output', 'i want an output', 'i need an output',
                   'create an output', 'design an output']
    SHORT_TAILS = [
        'where inputs are all 1 then out is 0',
        'when inputs are 1 then out is 0',
        'when all inputs are 1 then output is 0',
        'when any input is 1 then output is 1',
        'when both inputs are 1 then output is 1',
        'when all inputs are 0 then output is 1',
        'when odd number of inputs are 1 then output is 1',
        'when majority is 1 then output is 1',
    ]
    for sv in SHORT_VERBS:
        for st in SHORT_TAILS:
            out.append((f'{sv} {st}', 'build'))
            out.append((f'{sv} from 3 input {st}', 'build'))
            out.append((f'{sv} from 4 input {st}', 'build'))
            out.append((f'{sv} from 5 input {st}', 'build'))
            out.append((f'{sv} from 3-5 input {st}', 'build'))   # the exact user phrasing

    # Counting-style: "circuit that outputs 1 when X of N inputs are 1"
    for n in ['2', '3', '4', '5']:
        for k in ['1', '2', '3']:
            for cmp in ['exactly', 'at least', 'at most', 'more than', 'fewer than']:
                out.append((f'circuit with {n} inputs where output is 1 when {cmp} {k} are high', 'build'))
                out.append((f'build a {n}-input circuit, output high when {cmp} {k} of the inputs are 1', 'build'))

    # Conditional specifications with explicit input letters
    for nv in [(2, ['A','B']), (3, ['A','B','C']), (4, ['A','B','C','D'])]:
        n, vs = nv
        varlist = ' '.join(vs)
        out.append((f'circuit with {n} inputs {varlist} where Y=1 when {vs[0]}={vs[-1]}', 'build'))
        out.append((f'design a {n}-input circuit on inputs {varlist}', 'build'))
        out.append((f'make a circuit on {varlist}, output is 1 when all are 1', 'build'))
        out.append((f'circuit on inputs {varlist}, Y=1 only if {" and ".join(vs)}', 'build'))

    return out


def _output_query_samples():
    out = []
    bases = ['what is the output', 'what will be the output',
             'compute the output', 'calculate the result',
             'what does the circuit output', 'tell me the output',
             'show me the output', 'evaluate this circuit',
             'what is Y when', 'find the value of Y',
             'predict the output', 'what is the result',
             'simulate this circuit and show the output',
             'run this and tell me the output',
             'output value please', "what's Y", "what's the result"]
    for q in bases:
        out.append((q, 'output_query'))
        out.append((f'{q}?', 'output_query'))
    # Per-variable input setting (definite output_query  -  has explicit values).
    for a in (0, 1):
        for b in (0, 1):
            out.append((f'what is the output when A={a} and B={b}', 'output_query'))
            out.append((f'output for A={a}, B={b}', 'output_query'))
            out.append((f'evaluate for A={a} B={b}', 'output_query'))
            out.append((f'predict output if A={a}, B={b}', 'output_query'))
            out.append((f'find Y for A={a} B={b}', 'output_query'))
            for c in (0, 1):
                out.append((f'output when A={a} B={b} C={c}', 'output_query'))
                out.append((f'what is Y if A={a}, B={b}, C={c}', 'output_query'))
    return out


def _input_effect_samples():
    out = []
    bases = ['what if I change {v} to {x}', 'if I set {v} to {x}',
             'when I toggle input {v}', 'what happens if {v}={x}',
             'change input {v} and see', 'flip {v} from {y} to {x}',
             'what happens when input {v} changes', 'toggling {v}',
             'effect of changing {v}', 'how does {v} affect the output',
             'observe what happens if {v} is {x}']
    for v in VARS:
        for x in (0, 1):
            y = 1 - x
            for tpl in bases:
                out.append((tpl.format(v=v, x=x, y=y), 'input_effect'))
    return out


def _gate_count_samples():
    out = []
    bases = ['how many gates does this have', 'how many gates',
             'count the gates', 'total gate count', 'number of gates',
             'how many components', 'gates used count',
             'how many logic gates are in this circuit',
             'count of gates', 'how many gates are there',
             'tell me the gate count', 'gate total', 'sum of gates',
             "what's the gate count", 'how many gates do we have']
    for q in bases:
        out.append((q, 'gate_count'))
        out.append((f'{q}?', 'gate_count'))
    # Per-type counts ("how many NAND gates").
    for t in ['NAND', 'NOR', 'AND', 'OR', 'NOT', 'XOR', 'XNOR']:
        out.append((f'how many {t} gates', 'gate_count'))
        out.append((f'count of {t} gates', 'gate_count'))
        out.append((f'number of {t} gates in the circuit', 'gate_count'))
    return out


def _gate_type_samples():
    out = []
    bases = ['what gates are used', 'which gate types are present',
             'list the gate types', 'what kind of gates are here',
             'show me the gate types', 'breakdown of gates by type',
             'what types of gates does this circuit use',
             'gate types in this circuit', 'which gates do we have',
             'enumerate the gate types', 'tell me the kinds of gates',
             'what kinds of gates', 'show all gate types',
             'distinct gate types used', 'most used gate type',
             'which gate dominates this circuit']
    for q in bases:
        out.append((q, 'gate_type'))
        out.append((f'{q}?', 'gate_type'))
    return out


def _minimize_samples():
    out = []
    bases = ['minimize this circuit', 'reduce the gate count',
             'fewer gates please', 'simplify this', 'optimize the design',
             'can this be smaller', 'how can I minimize',
             'minimum number of gates', 'least gates possible',
             'simplify the boolean expression', 'k-map this',
             'apply boolean algebra to reduce', 'shrink this circuit',
             'optimise the gate count', 'reduce complexity',
             'apply Quine-McCluskey', 'apply QMC',
             "what's the smallest equivalent circuit",
             'minimize using k-map', 'find a smaller circuit',
             'simplify with boolean algebra', 'is there a smaller form',
             'reduce this to fewer gates', 'optimal gate count',
             'is this already minimized', 'can I use fewer gates here']
    for q in bases:
        out.append((q, 'minimize'))
        out.append((f'{q}?', 'minimize'))
    return out


def _fault_samples():
    out = []
    bases = ['any faults', 'is this correct', 'check the circuit',
             'are there errors', 'find problems', 'verify the design',
             'detect faults', 'is anything wrong', 'validate this circuit',
             'are there any issues', 'look for bugs', 'sanity check',
             'is there a floating input', 'any unconnected pins',
             'find faults', 'fault detection', 'check for issues',
             'audit this circuit', 'is it broken', "what's wrong with this",
             'any disconnected wires', 'spot the problem',
             'tell me about any errors', 'verify correctness',
             'is the wiring correct', 'are all inputs connected',
             'lint this circuit', 'find dead gates', 'find unused gates',
             'are there feedback loops', 'any cycles']
    for q in bases:
        out.append((q, 'fault_check'))
        out.append((f'{q}?', 'fault_check'))
    return out


def _what_if_samples():
    out = []
    bases = ['what if I change {old} to {new}',
             'replace the {old} with {new}',
             'swap {old} gate for a {new}',
             'use {new} instead of {old}',
             'change {old} to {new}', 'turn {old} into {new}',
             'substitute {new} for {old}', 'if {old} becomes {new}',
             "what's the effect of swapping {old} with {new}",
             'replace the {old} gate with a {new} gate']
    types = ['AND', 'OR', 'NAND', 'NOR', 'XOR', 'XNOR', 'NOT']
    for old in types:
        for new in types:
            if old == new: continue
            for tpl in bases:
                out.append((tpl.format(old=old, new=new), 'what_if'))
    return out


def _explain_samples():
    out = []
    # ── About the current circuit
    bases = ['what does this circuit do', 'explain the circuit',
             'how does this work', 'describe this design',
             'tell me about this circuit', 'what is the purpose',
             'walk me through this', 'analyze the circuit',
             'what is this', 'identify this circuit',
             'what kind of circuit is this', 'recognise this circuit',
             'recognize this circuit', 'is this a known design',
             'name this circuit', 'what pattern is this',
             'what circuit is shown here', 'summarise this circuit',
             "describe what's happening", 'overview of the circuit',
             'interpret this design', 'high-level view of this circuit']
    for q in bases:
        out.append((q, 'explain'))
        out.append((f'{q}?', 'explain'))

    # ── About a CONCEPT or GATE TYPE (without a circuit context)
    # These are the queries that previously misrouted to output_query.
    CONCEPT_TOPICS = [
        'and gate', 'or gate', 'not gate', 'nand gate', 'nor gate',
        'xor gate', 'xnor gate', 'buffer', 'inverter',
        'half adder', 'full adder', 'ripple carry adder', 'carry lookahead adder',
        'mux', 'multiplexer', 'demultiplexer', 'decoder', 'encoder',
        'priority encoder', 'comparator', 'parity generator',
        'sr latch', 'd latch', 'd flip flop', 'jk flip flop', 't flip flop',
        'master slave flip flop', 'shift register', 'ring counter',
        'johnson counter', 'ripple counter', 'synchronous counter',
        'finite state machine', 'mealy machine', 'moore machine',
        'tri state buffer', 'tristate buffer',
        'karnaugh map', 'k-map', 'truth table', 'boolean algebra',
        'sum of products', 'product of sums', 'minterm', 'maxterm',
        'propagation delay', 'setup time', 'hold time', 'metastability',
        'race condition', 'static hazard', 'logic hazard',
        'nand universality', 'nor universality',
        'de morgans law', 'two complement', 'bcd', 'binary coded decimal',
        'combinational circuit', 'sequential circuit',
        'gray code', 'parity bit',
    ]
    EXPLAIN_PREFIXES = [
        'what is', "what's", 'whats', 'what is a', 'what is an',
        'explain', 'explain a', 'explain the', 'describe',
        'tell me about', 'define', 'what does', 'how does',
        'how do', 'can you explain', 'i want to learn about',
        'teach me', 'help me understand', 'what is meant by',
    ]
    for topic in CONCEPT_TOPICS:
        for pre in EXPLAIN_PREFIXES:
            out.append((f'{pre} {topic}', 'explain'))
            out.append((f'{pre} {topic}?', 'explain'))
        # Bare topic — "xor gate" alone is also explain
        out.append((topic, 'explain'))
        out.append((f'{topic}?', 'explain'))
        out.append((f'how does {topic} work', 'explain'))
        out.append((f'how does an {topic} work', 'explain'))
        out.append((f'how does {topic} work?', 'explain'))

    # Concept questions with informal/casual wording
    INFORMAL_PREFIXES = ['yo what is', 'hey explain', 'um what is',
                         'so what is', 'just tell me what is',
                         'wait what is', 'idk explain', 'plz explain']
    for topic in CONCEPT_TOPICS[:25]:    # first half is enough
        for pre in INFORMAL_PREFIXES:
            out.append((f'{pre} {topic}', 'explain'))

    return out


def all_samples():
    """Combine everything, dedupe, lowercase, return list of (text, label)."""
    seen = set()
    out  = []
    for fn in (_build_samples, _output_query_samples, _input_effect_samples,
               _gate_count_samples, _gate_type_samples, _minimize_samples,
               _fault_samples, _what_if_samples, _explain_samples):
        for text, label in fn():
            key = (text.lower().strip(), label)
            if key in seen: continue
            seen.add(key)
            out.append((text.lower().strip(), label))
    # Shuffle for stable but diverse train/test split.
    random.Random(42).shuffle(out)
    return out


if __name__ == '__main__':
    s = all_samples()
    from collections import Counter
    print(f'total samples: {len(s)}')
    print('per intent:', Counter(lbl for _, lbl in s).most_common())
