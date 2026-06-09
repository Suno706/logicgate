import { useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { useCircuitState } from "../store";
import { collectOutputMap, GRAY2, inputsReachingOutput } from "./boolUtils";
import type { Gate } from "../types";

export function KmapPanel() {
  const { circuit } = useCircuitState();
  const allIns = circuit.gates.filter((g) => g.type === "INPUT" || g.type === "CLOCK");
  const outs   = circuit.gates.filter((g) => g.type === "OUTPUT" || g.type === "LED");

  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [maps,    setMaps]    = useState<{ out: Gate; ins: Gate[]; map: Record<number, 0 | 1> }[]>([]);

  async function build() {
    if (!outs.length) {
      setError("Add at least one OUTPUT gate.");
      return;
    }
    setLoading(true); setError(null);
    try {
      const all: { out: Gate; ins: Gate[]; map: Record<number, 0 | 1> }[] = [];
      const warnings: string[] = [];
      for (const o of outs) {
        // Only inputs that have a wire path to this output affect it.
        const reachable = inputsReachingOutput(circuit, o);
        if (reachable.length < 1) {
          warnings.push(`"${o.label || o.id}" has no INPUTs wired to it — skipped.`);
          continue;
        }
        if (reachable.length > 6) {
          warnings.push(`"${o.label || o.id}" depends on ${reachable.length} inputs — K-maps support up to 6.`);
          continue;
        }
        const m = await collectOutputMap(circuit, reachable, o);
        all.push({ out: o, ins: reachable, map: m });
      }
      setMaps(all);
      setError(warnings.length ? warnings.join(" • ") : null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setLoading(false); }
  }

  // Track which INPUTs are reachable from ANY output (for the legend).
  const reachableAcrossAll = new Set<string>();
  for (const o of outs) {
    for (const g of inputsReachingOutput(circuit, o)) reachableAcrossAll.add(g.id);
  }
  const ins = allIns;
  const inNames = ins.map((g, i) => g.label || String.fromCharCode(65 + i));

  return (
    <div className="flex-1 flex flex-col p-3 gap-3 min-h-0 overflow-hidden">
      <button
        onClick={build}
        disabled={loading}
        className="w-full py-1.5 rounded bg-bg-700 hover:bg-bg-600 border border-bg-600 text-xs font-mono text-gray-300 disabled:opacity-40 transition-all flex items-center justify-center gap-2"
      >
        {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
        {loading ? "Computing…" : "Generate K-maps →"}
      </button>

      {error && <div className="text-[9px] font-mono text-err flex-shrink-0">{error}</div>}

      {/* Variable legend — show on-canvas gate id → letter mapping. Unconnected
          inputs are dimmed so the user can see they're not used. */}
      {ins.length > 0 && (
        <div className="bg-bg-700/30 border border-bg-600 rounded p-2 flex-shrink-0">
          <div className="text-[8px] font-mono uppercase tracking-widest text-gray-600 mb-1">
            Inputs (dimmed = not connected to any output)
          </div>
          <div className="flex flex-wrap gap-1.5">
            {ins.map((g, i) => {
              const used = reachableAcrossAll.has(g.id);
              return (
                <div key={g.id} className={`flex items-center gap-1 text-[9px] font-mono ${used ? "" : "opacity-40"}`}>
                  <span className={`px-1.5 py-0.5 rounded font-bold ${used ? "bg-accent/15 text-accent" : "bg-bg-600 text-gray-500"}`}>{inNames[i]}</span>
                  <span className="text-gray-600">= {g.id}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {!maps.length && !loading && !error && (
        <div className="text-[9px] text-gray-600 font-mono text-center py-3">
          One Karnaugh map per OUTPUT, with Gray-code labels.
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-3 min-h-0">
        {maps.map(({ out, ins: usedIns, map }) => (
          <KmapBlock key={out.id} outName={out.label || out.id} n={usedIns.length}
            inNames={usedIns.map((g, i) => g.label || String.fromCharCode(65 + i))}
            outMap={map} />
        ))}
      </div>
    </div>
  );
}

function KmapBlock({
  outName, n, inNames, outMap,
}: {
  outName: string; n: number; inNames: string[]; outMap: Record<number, 0 | 1>;
}) {
  return (
    <div className="bg-bg-700/40 border border-bg-600 rounded-lg p-2.5">
      <div className="text-[10px] font-mono font-bold text-accent mb-2">
        K-Map: <span className="text-gray-300">{outName}</span>
        <span className="text-gray-600 font-normal ml-1">({n} inputs)</span>
      </div>
      <KmapTable n={n} inNames={inNames} outMap={outMap} />
    </div>
  );
}

function Cell({ v }: { v: 0 | 1 }) {
  return (
    <td className={`px-2 py-1 text-center border border-bg-600 font-mono font-bold text-[10px] ${
      v === 1 ? "text-ok bg-ok/10" : "text-err/70"
    }`}>{v}</td>
  );
}

function KmapTable({ n, inNames, outMap }: { n: number; inNames: string[]; outMap: Record<number, 0 | 1> }) {
  if (n === 2) {
    return (
      <table className="w-full text-[9px] font-mono border-collapse">
        <thead>
          <tr>
            <th className="px-2 py-1 text-accent text-center border border-bg-600 bg-bg-800">{inNames[0]} \ {inNames[1]}</th>
            <th className="px-2 py-1 text-warn text-center border border-bg-600 bg-bg-800">{inNames[1]}=0</th>
            <th className="px-2 py-1 text-warn text-center border border-bg-600 bg-bg-800">{inNames[1]}=1</th>
          </tr>
        </thead>
        <tbody>
          {[0, 1].map((a) => (
            <tr key={a}>
              <th className="px-2 py-1 text-accent text-center border border-bg-600 bg-bg-800">{inNames[0]}={a}</th>
              {[0, 1].map((b) => <Cell key={b} v={outMap[(a << 1) | b] ?? 0} />)}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (n === 3) {
    return (
      <table className="w-full text-[9px] font-mono border-collapse">
        <thead>
          <tr>
            <th className="px-1 py-1 border border-bg-600 bg-bg-800"></th>
            <th colSpan={4} className="px-1 py-1 text-accent text-center border border-bg-600 bg-bg-800">{inNames[1]} {inNames[2]}</th>
          </tr>
          <tr>
            <th className="px-1 py-1 text-accent border border-bg-600 bg-bg-800">{inNames[0]}</th>
            {GRAY2.map(([b, c], i) => (
              <th key={i} className="px-1 py-1 text-warn text-center border border-bg-600 bg-bg-800">{b}{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[0, 1].map((a) => (
            <tr key={a}>
              <th className="px-1 py-1 text-accent text-center border border-bg-600 bg-bg-800">{a}</th>
              {GRAY2.map(([b, c], i) => (
                <Cell key={i} v={outMap[(a << 2) | (b << 1) | c] ?? 0} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  // 4-var K-map (used as building block for n=4, n=5, n=6)
  function Map4({ rowVars, colVars, rowsOffset, colsOffset, fixedMask, fixedBits }: {
    rowVars: [string, string]; colVars: [string, string];
    rowsOffset: number; colsOffset: number;
    fixedMask: number; fixedBits: number;
  }) {
    return (
      <table className="text-[9px] font-mono border-collapse">
        <thead>
          <tr>
            <th className="px-1 py-1 border border-bg-600 bg-bg-800"></th>
            <th colSpan={4} className="px-1 py-1 text-accent text-center border border-bg-600 bg-bg-800">{colVars[0]} {colVars[1]}</th>
          </tr>
          <tr>
            <th className="px-1 py-1 text-accent border border-bg-600 bg-bg-800">{rowVars[0]} {rowVars[1]}</th>
            {GRAY2.map(([c, d], i) => (
              <th key={i} className="px-1 py-1 text-warn text-center border border-bg-600 bg-bg-800">{c}{d}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {GRAY2.map(([a, b], ri) => (
            <tr key={ri}>
              <th className="px-1 py-1 text-accent text-center border border-bg-600 bg-bg-800">{a}{b}</th>
              {GRAY2.map(([c, d], ci) => {
                const key = ((a << rowsOffset) | (b << (rowsOffset-1)) |
                             (c << colsOffset) | (d << (colsOffset-1)) |
                             (fixedBits & fixedMask));
                return <Cell key={ci} v={outMap[key] ?? 0} />;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  if (n === 4) {
    return (
      <Map4 rowVars={[inNames[0], inNames[1]]}
            colVars={[inNames[2], inNames[3]]}
            rowsOffset={3} colsOffset={1}
            fixedMask={0} fixedBits={0} />
    );
  }

  if (n === 5) {
    // 5-var: two 4-var K-maps side by side, one for inNames[0]=0, one for =1
    return (
      <div className="flex gap-3 overflow-x-auto">
        {[0, 1].map((e) => (
          <div key={e} className="flex-shrink-0">
            <div className="text-[8px] font-mono text-warn mb-1 text-center">
              {inNames[0]} = {e}
            </div>
            <Map4 rowVars={[inNames[1], inNames[2]]}
                  colVars={[inNames[3], inNames[4]]}
                  rowsOffset={4} colsOffset={2}
                  fixedMask={1 << 4} fixedBits={e << 4} />
          </div>
        ))}
      </div>
    );
  }

  // n === 6 — 2×2 grid of 4-var maps, fixed by (inNames[0], inNames[1])
  return (
    <div className="grid grid-cols-2 gap-3 overflow-x-auto">
      {[0, 1].map((e0) => (
        [0, 1].map((e1) => (
          <div key={`${e0}${e1}`}>
            <div className="text-[8px] font-mono text-warn mb-1 text-center">
              {inNames[0]}{inNames[1]} = {e0}{e1}
            </div>
            <Map4 rowVars={[inNames[2], inNames[3]]}
                  colVars={[inNames[4], inNames[5]]}
                  rowsOffset={5} colsOffset={3}
                  fixedMask={(1 << 5) | (1 << 4)}
                  fixedBits={(e0 << 5) | (e1 << 4)} />
          </div>
        ))
      ))}
    </div>
  );
}
