/** Pure logic helpers shared by both games. */

export type GateOp =
  | "AND" | "OR" | "NAND" | "NOR" | "XOR" | "XNOR" | "NOT" | "BUF";

/** Evaluate a binary gate on two bits (NOT/BUF use only `a`). */
export function evalGate(op: GateOp, a: 0 | 1, b: 0 | 1 = 0): 0 | 1 {
  switch (op) {
    case "AND":  return (a & b) as 0 | 1;
    case "OR":   return (a | b) as 0 | 1;
    case "NAND": return (1 - (a & b)) as 0 | 1;
    case "NOR":  return (1 - (a | b)) as 0 | 1;
    case "XOR":  return (a ^ b) as 0 | 1;
    case "XNOR": return (1 - (a ^ b)) as 0 | 1;
    case "NOT":  return (1 - a) as 0 | 1;
    case "BUF":  return a;
  }
}

/** Evaluate a chain of gates fed by an initial value and a per-stage `b`
 *  input. Stage i = evalGate(ops[i], prev, otherInputs[i]). */
export function evalChain(
  ops: GateOp[],
  initial: 0 | 1,
  otherInputs: (0 | 1)[],
): 0 | 1 {
  let v: 0 | 1 = initial;
  for (let i = 0; i < ops.length; i++) {
    v = evalGate(ops[i], v, otherInputs[i] ?? 0);
  }
  return v;
}

/** Truth-table column (length 2^n) produced by an N-input gate (n ≥ 2). */
export function tableOf(nIn: number, op: GateOp): (0 | 1)[] {
  const out: (0 | 1)[] = [];
  const rows = 1 << nIn;
  for (let i = 0; i < rows; i++) {
    const bits = Array.from({ length: nIn }, (_, k) => ((i >> (nIn - 1 - k)) & 1) as 0 | 1);
    if (nIn === 1) {
      out.push(evalGate(op, bits[0]));
    } else {
      let v: 0 | 1 = bits[0];
      for (let k = 1; k < nIn; k++) v = evalGate(op, v, bits[k]);
      out.push(v);
    }
  }
  return out;
}

export const BINARY_GATES: GateOp[] = ["AND", "OR", "NAND", "NOR", "XOR", "XNOR"];
export const ALL_GATES:    GateOp[] = [...BINARY_GATES, "NOT", "BUF"];

/** A tiny visual symbol for each gate — used in chips/buttons. */
export const GATE_GLYPH: Record<GateOp, string> = {
  AND:  "∧",
  OR:   "∨",
  NAND: "⊼",
  NOR:  "⊽",
  XOR:  "⊕",
  XNOR: "⊙",
  NOT:  "¬",
  BUF:  "▷",
};
