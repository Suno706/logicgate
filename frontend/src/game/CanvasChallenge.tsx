import { useState } from "react";
import { CheckCircle2, X, Dice5, Loader2 } from "lucide-react";
import { simulate } from "../api";
import { useCircuitState } from "../store";
import type { Circuit, Gate } from "../types";

/** Canvas Challenge.
 *
 *  Floats above the canvas while challenge mode is active. The player
 *  builds a real circuit on the actual editor (drag from the sidebar,
 *  wire gates, place I/O). When they hit "Check", we iterate every
 *  input combination, simulate, and compare the output column to the
 *  target. Match every row = solved, dice for a fresh random target. */

export interface ChallengeState {
  active: boolean;
  nIn:    2 | 3;
  target: (0 | 1)[];   // length 2^nIn
}

export function randomTarget(nIn: 2 | 3): (0 | 1)[] {
  const rows = 1 << nIn;
  while (true) {
    const bits: (0 | 1)[] = Array.from({ length: rows }, () => (Math.random() < 0.5 ? 0 : 1));
    const sum = bits.reduce<number>((a, b) => a + b, 0);
    if (sum !== 0 && sum !== rows) return bits;
  }
}

/** Seed the canvas with input/output gates spaced out for an empty start. */
export function seedChallengeCircuit(nIn: 2 | 3): Circuit {
  const labels = "ABC";
  const gates: Gate[] = [];
  for (let i = 0; i < nIn; i++) {
    gates.push({
      id:    `chal_in_${labels[i].toLowerCase()}`,
      type:  "INPUT",
      x:     120,
      y:     180 + i * 110,
      label: labels[i],
      value: 0,
    });
  }
  gates.push({
    id:    "chal_out_y",
    type:  "OUTPUT",
    x:     720,
    y:     180 + Math.floor((nIn - 1) / 2) * 110,
    label: "Y",
  });
  return { gates, wires: [] };
}

interface Props {
  challenge: ChallengeState;
  onNew:  () => void;
  onExit: () => void;
}

export function CanvasChallenge({ challenge, onNew, onExit }: Props) {
  const { circuit } = useCircuitState();
  const [checking, setChecking] = useState(false);
  const [result,   setResult]   = useState<{ correct: number; total: number; rows: (0 | 1 | null)[] } | null>(null);

  const { nIn, target } = challenge;
  const inputLabels = "ABC".slice(0, nIn).split("");
  const rows = 1 << nIn;

  async function check() {
    const inputGates  = circuit.gates.filter((g) => g.type === "INPUT");
    const outputGates = circuit.gates.filter((g) => g.type === "OUTPUT");
    if (inputGates.length < nIn) {
      alert(`Add at least ${nIn} INPUT gate(s) to your circuit (labelled ${inputLabels.join(", ")}).`);
      return;
    }
    if (outputGates.length < 1) {
      alert("Add at least one OUTPUT gate to read the result.");
      return;
    }
    setChecking(true);
    setResult(null);

    // Pick the first nIn input gates and the first output gate
    const ins = inputGates.slice(0, nIn);
    const out = outputGates[0];

    const playerCol: (0 | 1 | null)[] = Array(rows).fill(null);
    try {
      const promises: Promise<void>[] = [];
      for (let mask = 0; mask < rows; mask++) {
        const modGates = circuit.gates.map((g) => {
          const i = ins.findIndex((x) => x.id === g.id);
          if (i === -1) return g;
          return { ...g, value: (((mask >> (nIn - 1 - i)) & 1) as 0 | 1) };
        });
        const modCircuit = { gates: modGates, wires: circuit.wires };
        promises.push(
          simulate(modCircuit).then((r) => {
            if (r.success) playerCol[mask] = (r.outputs[out.id] ?? 0) as 0 | 1;
          }).catch(() => { /* leave null */ })
        );
      }
      await Promise.all(promises);

      const correct = playerCol.reduce<number>(
        (n, v, i) => n + ((v !== null && v === target[i]) ? 1 : 0), 0
      );
      setResult({ correct, total: rows, rows: playerCol });
    } finally {
      setChecking(false);
    }
  }

  const won = result?.correct === rows;

  return (
    <div className="absolute top-3 left-1/2 -translate-x-1/2 z-30 w-[min(94vw,560px)] rounded-xl border border-accent/40 bg-bg-800/95 backdrop-blur shadow-2xl p-3 md:p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="px-2 py-0.5 rounded bg-accent/20 text-accent text-[10px] font-semibold uppercase tracking-wider">
          Challenge
        </span>
        <span className="text-[13px] text-gray-100 font-semibold">
          Build a circuit that matches this table
        </span>
        <div className="flex-1" />
        <button onClick={onNew}
          title="New random target (wipes the canvas)"
          className="p-1.5 rounded-md text-gray-400 hover:text-accent hover:bg-bg-700 transition-colors">
          <Dice5 size={14} />
        </button>
        <button onClick={onExit}
          title="Exit challenge mode (keep your circuit)"
          className="p-1.5 rounded-md text-gray-400 hover:text-err hover:bg-bg-700 transition-colors">
          <X size={14} />
        </button>
      </div>

      <div className="flex gap-4 items-start">
        {/* Target / result table */}
        <div className="rounded-lg border border-bg-600 overflow-hidden bg-bg-900/40">
          <table className="text-[12px] font-mono tabular-nums">
            <thead className="bg-bg-700/40 text-gray-500 text-[10px]">
              <tr>
                {inputLabels.map((c) => (
                  <th key={c} className="px-2 py-1 font-medium text-center">{c}</th>
                ))}
                <th className="px-2 py-1 font-medium text-center text-accent">Goal</th>
                <th className="px-2 py-1 font-medium text-center text-gray-200">You</th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: rows }).map((_, i) => {
                const yours = result?.rows?.[i] ?? null;
                const match = yours !== null && yours === target[i];
                return (
                  <tr key={i} className="border-t border-bg-600/40">
                    {Array.from({ length: nIn }).map((_, k) => (
                      <td key={k} className="px-2 py-0.5 text-center text-gray-400">
                        {(i >> (nIn - 1 - k)) & 1}
                      </td>
                    ))}
                    <td className="px-2 py-0.5 text-center font-semibold text-accent">
                      {target[i]}
                    </td>
                    <td className={`px-2 py-0.5 text-center font-semibold ${
                      yours === null ? "text-gray-600"
                        : match ? "text-ok" : "text-err"
                    }`}>
                      {yours ?? "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Right side: instructions + actions */}
        <div className="flex-1 flex flex-col gap-2 min-w-0">
          <p className="text-[11px] text-gray-400 leading-relaxed">
            Drag gates from the left palette, wire them between
            <span className="text-accent font-mono"> {inputLabels.join(", ")}</span> and
            <span className="text-accent font-mono"> Y</span>, then hit Check.
          </p>

          <button onClick={check} disabled={checking}
            className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-[13px] font-semibold text-white bg-accent hover:bg-accent-hover transition-colors disabled:opacity-50">
            {checking
              ? <><Loader2 size={14} className="animate-spin" /> Checking…</>
              : <><CheckCircle2 size={14} /> Check circuit</>}
          </button>

          {result && (
            <div className={`px-3 py-2 rounded-md text-[12px] font-medium border ${
              won
                ? "bg-ok/10 border-ok/40 text-ok"
                : "bg-warn/10 border-warn/40 text-warn"
            }`}>
              {won
                ? "🎉 All rows match — circuit built!"
                : `${result.correct} / ${result.total} rows match. Keep going.`}
            </div>
          )}

          {won && (
            <button onClick={onNew}
              className="px-3 py-1.5 rounded-md text-[12px] font-medium border border-accent text-accent hover:bg-accent/10 transition-colors">
              Next challenge →
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
