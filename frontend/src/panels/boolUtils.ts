import type { Circuit, Gate } from "../types";
import { simulate } from "../api";

/** Returns INPUT gates that have a wire path to `target` (backward BFS).
 * Inputs not reachable from the target don't affect its value — they'd just
 * add fake variables to the K-map / boolean expression. */
export function inputsReachingOutput(circuit: Circuit, target: Gate): Gate[] {
  const incoming = new Map<string, string[]>();
  for (const w of circuit.wires) {
    if (!incoming.has(w.to_gate)) incoming.set(w.to_gate, []);
    incoming.get(w.to_gate)!.push(w.from_gate);
  }
  const seen = new Set<string>([target.id]);
  const stack = [target.id];
  while (stack.length) {
    const id = stack.pop()!;
    for (const src of incoming.get(id) || []) {
      if (!seen.has(src)) {
        seen.add(src);
        stack.push(src);
      }
    }
  }
  return circuit.gates.filter((g) =>
    (g.type === "INPUT" || g.type === "CLOCK") && seen.has(g.id)
    // Constant-tie inputs from older synthesized circuits are not real
    // variables — sweeping them would double the K-map with garbage rows.
    && !(g.label || "").startsWith("const_"));
}

/** Sweep every input combination, return outMap[mask] = 0|1 for one OUTPUT gate. */
export async function collectOutputMap(
  circuit: Circuit,
  ins: Gate[],
  outGate: Gate,
): Promise<Record<number, 0 | 1>> {
  const n = ins.length;
  const map: Record<number, 0 | 1> = {};
  const tasks: Promise<void>[] = [];
  for (let mask = 0; mask < 1 << n; mask++) {
    const modGates = circuit.gates.map((g) => {
      const idx = ins.findIndex((i) => i.id === g.id);
      if (idx === -1) return g;
      return { ...g, value: (((mask >> (n - 1 - idx)) & 1) as 0 | 1) };
    });
    const m = mask;
    tasks.push(
      simulate({ gates: modGates, wires: circuit.wires }).then((r) => {
        map[m] = (r.outputs[outGate.id] ?? 0) as 0 | 1;
      }),
    );
  }
  await Promise.all(tasks);
  return map;
}

/** Quine-McCluskey minimisation. Ported from templates/index.html. */
export function quineMcCluskey(
  minterms: number[],
  n: number,
  varNames: string[],
): string {
  if (!minterms.length) return "0";
  const N = 1 << n;
  if (minterms.length === N) return "1";

  interface Term { bits: (0 | 1 | null)[]; covered: Set<number> }

  function combine(a: Term, b: Term): Term | null {
    let diffCount = 0, diffPos = -1;
    for (let i = 0; i < n; i++) {
      if (a.bits[i] === null && b.bits[i] === null) continue;
      if (a.bits[i] === null || b.bits[i] === null) { diffCount += 2; break; }
      if (a.bits[i] !== b.bits[i]) { diffCount++; diffPos = i; }
    }
    if (diffCount === 1 && diffPos >= 0) {
      const result = a.bits.slice() as (0 | 1 | null)[];
      result[diffPos] = null;
      return { bits: result, covered: new Set([...a.covered, ...b.covered]) };
    }
    return null;
  }

  let terms: Term[] = minterms.map((m) => {
    // Store bits MSB-first so bits[i] aligns with varNames[i] (varNames[0]=A
    // is the MSB by convention). The old loop used `unshift`, which built
    // the array LSB-first — symmetric functions (XOR/AND/majority) still
    // produced a valid expression by coincidence, but asymmetric functions
    // came out mirrored (e.g. B·C'·D' instead of A'·B'·C for m=2/n=4).
    const bits: (0 | 1 | null)[] = [];
    for (let i = 0; i < n; i++) bits.push(((m >> (n - 1 - i)) & 1) as 0 | 1);
    return { bits, covered: new Set([m]) };
  });

  const primeImplicants: Term[] = [];

  while (terms.length) {
    const groups: Record<number, Term[]> = {};
    for (const t of terms) {
      const k = t.bits.filter((b) => b === 1).length;
      if (!groups[k]) groups[k] = [];
      groups[k].push(t);
    }
    const used = new Set<Term>();
    const next: Term[] = [];
    const ks = Object.keys(groups).map(Number).sort((a, b) => a - b);
    for (let ki = 0; ki < ks.length - 1; ki++) {
      const g1 = groups[ks[ki]] ?? [];
      const g2 = groups[ks[ki + 1]] ?? [];
      for (const a of g1) for (const b of g2) {
        const r = combine(a, b);
        if (r) {
          const key = r.bits.map((x) => x === null ? "-" : x).join("");
          if (!next.find((t) => t.bits.map((x) => x === null ? "-" : x).join("") === key)) {
            next.push(r);
          }
          used.add(a); used.add(b);
        }
      }
    }
    for (const t of terms) if (!used.has(t)) primeImplicants.push(t);
    terms = next;
  }

  if (!primeImplicants.length) {
    return minterms.map((m) => {
      const bits: (0 | 1)[] = [];
      for (let i = 0; i < n; i++) bits.push(((m >> (n - 1 - i)) & 1) as 0 | 1);
      return bits.map((b, i) => b ? varNames[i] : varNames[i] + "'").join("·");
    }).join(" + ");
  }

  // Essential prime implicant cover
  const covered = new Set<number>();
  const essential: Term[] = [];
  for (const m of minterms) {
    const covering = primeImplicants.filter((pi) => pi.covered.has(m));
    if (covering.length === 1 && !essential.includes(covering[0])) {
      essential.push(covering[0]);
      for (const c of covering[0].covered) covered.add(c);
    }
  }
  const selected = [...essential];
  for (const m of minterms) {
    if (covered.has(m)) continue;
    const opts = primeImplicants.filter((pi) => pi.covered.has(m) && !selected.includes(pi));
    if (opts.length) {
      opts.sort((a, b) =>
        [...b.covered].filter((x) => !covered.has(x)).length
        - [...a.covered].filter((x) => !covered.has(x)).length);
      selected.push(opts[0]);
      for (const c of opts[0].covered) covered.add(c);
    }
  }

  function piToExpr(pi: Term): string {
    const ts: string[] = [];
    for (let i = 0; i < n; i++) {
      if (pi.bits[i] === null) continue;
      ts.push(pi.bits[i] === 1 ? varNames[i] : varNames[i] + "'");
    }
    return ts.length ? ts.join("·") : "1";
  }
  return selected.map(piToExpr).join(" + ");
}

export interface BoolDerivation {
  isConstant0?: boolean;
  isConstant1?: boolean;
  sop?: string;
  simplified?: string;
  canonicalPOS?: string;
  minterms?: number[];
  maxterms?: number[];
}

export function deriveBool(
  outMap: Record<number, 0 | 1>,
  n: number,
  varNames: string[],
): BoolDerivation {
  const N = 1 << n;
  const minterms: number[] = [];
  const maxterms: number[] = [];
  for (let m = 0; m < N; m++) {
    if (outMap[m] === 1) minterms.push(m);
    else maxterms.push(m);
  }
  if (!minterms.length) return { isConstant0: true };
  if (minterms.length === N) return { isConstant1: true };

  const mintermToExpr = (mask: number) =>
    varNames.map((nm, i) => (((mask >> (n - 1 - i)) & 1) ? nm : nm + "'")).join("·");
  const maxtermToExpr = (mask: number) =>
    "(" + varNames.map((nm, i) => (((mask >> (n - 1 - i)) & 1) ? nm + "'" : nm)).join("+") + ")";

  return {
    sop:          minterms.map(mintermToExpr).join(" + "),
    simplified:   quineMcCluskey(minterms, n, varNames),
    canonicalPOS: maxterms.map(maxtermToExpr).join("·"),
    minterms,
    maxterms,
  };
}

/** Gray-code 2-bit order: 00, 01, 11, 10 */
export const GRAY2: [number, number][] = [[0, 0], [0, 1], [1, 1], [1, 0]];
