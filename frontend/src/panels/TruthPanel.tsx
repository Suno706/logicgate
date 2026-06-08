import { useState } from "react";
import { simulate } from "../api";
import { useCircuitState } from "../store";
import type { Circuit } from "../types";

function generateTruth(circuit: Circuit, simFn: (c: Circuit) => Promise<{ success: boolean; outputs: Record<string, 0 | 1> }>) {
  const inputs  = circuit.gates.filter((g) => g.type === "INPUT" || g.type === "CLOCK");
  const outputs = circuit.gates.filter((g) => g.type === "OUTPUT");
  if (!inputs.length || !outputs.length) return Promise.resolve(null);

  const n    = inputs.length;
  const rows: (0 | 1)[][] = Array(1 << n);
  const promises: Promise<void>[] = [];

  for (let mask = 0; mask < 1 << n; mask++) {
    const idx = mask;
    const modGates = circuit.gates.map((g) => {
      const i = inputs.findIndex((inp) => inp.id === g.id);
      if (i === -1) return g;
      return { ...g, value: (((idx >> (n - 1 - i)) & 1) as 0 | 1) };
    });
    const modCircuit = { gates: modGates, wires: circuit.wires };
    promises.push(
      simFn(modCircuit).then((r) => {
        if (!r.success) return;
        rows[idx] = [
          ...inputs.map((_, i) => (((idx >> (n - 1 - i)) & 1) as 0 | 1)),
          ...outputs.map((o) => (r.outputs[o.id] ?? 0) as 0 | 1),
        ];
      }),
    );
  }

  const headers = [
    ...inputs.map((g)  => g.label || "IN"),
    ...outputs.map((g) => g.label || "OUT"),
  ];
  return Promise.all(promises).then(() => ({ headers, rows, nIn: n }));
}

export function TruthPanel() {
  const { circuit } = useCircuitState();
  const [loading,  setL]   = useState(false);
  const [table,    setTbl] = useState<{ headers: string[]; rows: (0 | 1)[][]; nIn: number } | null>(null);
  const [error,    setErr] = useState<string | null>(null);

  const inputs  = circuit.gates.filter((g) => g.type === "INPUT" || g.type === "CLOCK");
  const outputs = circuit.gates.filter((g) => g.type === "OUTPUT");

  async function build() {
    if (!inputs.length || !outputs.length) {
      setErr("Circuit needs at least one input and one output.");
      return;
    }
    // Hard cap of 32 inputs (2^32 = 4 billion rows is impossible). Above 12
    // inputs we cap the *displayed* rows to keep the browser responsive.
    if (inputs.length > 32) {
      setErr(`Truth table limited to 32 inputs. Your circuit has ${inputs.length}.`);
      return;
    }
    if (inputs.length > 16) {
      setErr(`${inputs.length} inputs → ${1 << inputs.length} rows. Above 16 inputs this will take minutes and likely freeze the browser. Trim some inputs or use Boolean view instead.`);
      return;
    }
    setL(true); setErr(null);
    try {
      const result = await generateTruth(circuit, simulate);
      setTbl(result);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setL(false); }
  }

  return (
    <div className="flex-1 flex flex-col p-3 gap-3 min-h-0">
      <button
        onClick={build}
        disabled={loading || !inputs.length || !outputs.length}
        className="w-full py-1.5 rounded bg-bg-700 hover:bg-bg-600 border border-bg-600 text-xs font-mono text-gray-300 disabled:opacity-40 transition-all flex-shrink-0"
      >
        {loading ? `Computing (${1 << Math.min(inputs.length, 6)} rows)…` : "Generate truth table →"}
      </button>

      {error && <div className="text-[9px] font-mono text-err flex-shrink-0">{error}</div>}

      {!table && !loading && !error && (
        <div className="text-[9px] text-gray-600 font-mono text-center py-4 flex-shrink-0">
          {inputs.length === 0
            ? "Add INPUT gates to generate a truth table."
            : outputs.length === 0
            ? "Add OUTPUT gates to generate a truth table."
            : `${inputs.length} input${inputs.length !== 1 ? "s" : ""} → ${1 << inputs.length} rows`}
        </div>
      )}

      {table && (
        <div className="flex-1 overflow-auto min-h-0">
          <table className="w-full text-[9px] font-mono border-collapse">
            <thead>
              <tr>
                {table.headers.map((h, i) => (
                  <th key={i}
                    className={`px-2 py-1 text-center border-b border-bg-600 font-bold uppercase tracking-wider whitespace-nowrap ${
                      i < table.nIn ? "text-accent" : "text-ok"
                    }`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, ri) => (
                <tr key={ri} className="hover:bg-bg-700">
                  {row?.map((cell, ci) => (
                    <td key={ci} className={`px-2 py-0.5 text-center border-b border-bg-600/30 ${
                      ci < table.nIn
                        ? "text-gray-500"
                        : cell === 1 ? "text-ok font-bold" : "text-gray-600"
                    }`}>
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>

          <div className="mt-2 text-[8px] font-mono text-gray-700 text-right">
            {table.rows.length} rows · {table.nIn} inputs · {table.headers.length - table.nIn} outputs
          </div>
        </div>
      )}
    </div>
  );
}
