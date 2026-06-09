import { useState } from "react";
import { Loader2, Sigma } from "lucide-react";
import { useCircuitState } from "../store";
import { collectOutputMap, deriveBool, inputsReachingOutput, type BoolDerivation } from "./boolUtils";
import type { Gate } from "../types";

interface OutResult { out: Gate; ins: Gate[]; result: BoolDerivation }

export function BoolPanel() {
  const { circuit } = useCircuitState();
  const allIns = circuit.gates.filter((g) => g.type === "INPUT" || g.type === "CLOCK");
  const outs   = circuit.gates.filter((g) => g.type === "OUTPUT" || g.type === "LED");

  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [results, setResults] = useState<OutResult[]>([]);

  async function build() {
    if (!outs.length) {
      setError("Need at least one OUTPUT gate.");
      return;
    }
    setLoading(true); setError(null);
    try {
      const all: OutResult[] = [];
      const warnings: string[] = [];
      for (const o of outs) {
        const reachable = inputsReachingOutput(circuit, o);
        if (reachable.length === 0) {
          warnings.push(`"${o.label || o.id}" has no INPUTs wired to it — skipped.`);
          continue;
        }
        if (reachable.length > 12) {
          warnings.push(`"${o.label || o.id}" depends on ${reachable.length} inputs (Quine-McCluskey caps at 12).`);
          continue;
        }
        const inNamesArr = reachable.map((g, i) => g.label || String.fromCharCode(65 + i));
        const m = await collectOutputMap(circuit, reachable, o);
        all.push({ out: o, ins: reachable, result: deriveBool(m, reachable.length, inNamesArr) });
      }
      setResults(all);
      setError(warnings.length ? warnings.join(" • ") : null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setLoading(false); }
  }

  // Track which INPUTs are reachable from ANY output for the legend.
  const reachableAcrossAll = new Set<string>();
  for (const o of outs) {
    for (const g of inputsReachingOutput(circuit, o)) reachableAcrossAll.add(g.id);
  }
  const ins = allIns;

  return (
    <div className="flex-1 flex flex-col p-3 gap-3 min-h-0 overflow-hidden">
      <button
        onClick={build}
        disabled={loading}
        className="w-full py-1.5 rounded bg-bg-700 hover:bg-bg-600 border border-bg-600 text-xs font-mono text-gray-300 disabled:opacity-40 transition-all flex items-center justify-center gap-2"
      >
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Sigma size={12} />}
        {loading ? "Deriving…" : "Derive Boolean expressions →"}
      </button>

      {error && <div className="text-[9px] font-mono text-err flex-shrink-0">{error}</div>}

      {/* Variable legend — dim inputs that aren't connected to any output. */}
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
                  <span className={`px-1.5 py-0.5 rounded font-bold ${used ? "bg-accent/15 text-accent" : "bg-bg-600 text-gray-500"}`}>
                    {g.label || String.fromCharCode(65 + i)}
                  </span>
                  <span className="text-gray-600">= {g.id}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {!results.length && !loading && !error && (
        <div className="text-[9px] text-gray-600 font-mono text-center py-3">
          One SOP / POS / minimised expression per OUTPUT.
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-3 min-h-0">
        {results.map(({ out, ins: usedIns, result }) => {
          const local = usedIns.map((g, i) => g.label || String.fromCharCode(65 + i)).join(", ");
          return (
            <BoolBlock key={out.id} outName={out.label || out.id} r={result} inNames={local} />
          );
        })}
      </div>
    </div>
  );
}

function BoolBlock({ outName, r, inNames }: { outName: string; r: BoolDerivation; inNames: string }) {
  return (
    <div className="bg-bg-700/40 border border-bg-600 rounded-lg p-2.5 space-y-2">
      <div className="text-[10px] font-mono font-bold text-accent">Output: <span className="text-gray-200">{outName}</span></div>

      {r.isConstant0 && <div className="text-err font-mono text-xs">f = 0 (always LOW)</div>}
      {r.isConstant1 && <div className="text-ok  font-mono text-xs">f = 1 (always HIGH)</div>}

      {!r.isConstant0 && !r.isConstant1 && (
        <>
          <Section label="Sum of Products (SOP)">
            <Expr>{outName} = {r.sop}</Expr>
          </Section>

          {r.simplified && r.simplified !== r.sop && (
            <Section label="Simplified (Quine-McCluskey)">
              <Expr accent>{outName} = {r.simplified}</Expr>
            </Section>
          )}

          <div className="space-y-1 pt-1 border-t border-bg-600">
            <Row k="Variables">{inNames} <span className="text-gray-600">(MSB → LSB)</span></Row>
            <Row k="Minterms">Σm({r.minterms?.join(", ") || "—"})</Row>
            <Row k="Maxterms">ΠM({r.maxterms?.join(", ") || "—"})</Row>
            <Row k="Canonical POS"><span className="break-all">{r.canonicalPOS}</span></Row>
          </div>
        </>
      )}
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[8px] font-mono uppercase tracking-widest text-gray-600 mb-1">{label}</div>
      {children}
    </div>
  );
}

function Expr({ children, accent }: { children: React.ReactNode; accent?: boolean }) {
  return (
    <div className={`bg-bg-800 border border-bg-600 rounded px-2 py-1.5 font-mono text-[10px] break-all ${
      accent ? "text-accent" : "text-gray-300"
    }`}>
      {children}
    </div>
  );
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2 text-[9px] font-mono">
      <span className="text-gray-600 uppercase tracking-wider w-24 flex-shrink-0">{k}</span>
      <span className="text-gray-400 flex-1">{children}</span>
    </div>
  );
}
