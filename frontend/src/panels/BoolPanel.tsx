import { useState } from "react";
import { Loader2, Sigma } from "lucide-react";
import { useCircuitState } from "../store";
import { collectOutputMap, deriveBool, type BoolDerivation } from "./boolUtils";
import type { Gate } from "../types";

interface OutResult { out: Gate; result: BoolDerivation }

export function BoolPanel() {
  const { circuit } = useCircuitState();
  const ins  = circuit.gates.filter((g) => g.type === "INPUT" || g.type === "CLOCK");
  const outs = circuit.gates.filter((g) => g.type === "OUTPUT" || g.type === "LED");

  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [results, setResults] = useState<OutResult[]>([]);

  async function build() {
    if (!ins.length || !outs.length) {
      setError("Need at least one INPUT and one OUTPUT.");
      return;
    }
    if (ins.length > 32) {
      setError(`Boolean derivation limited to 32 inputs. Your circuit has ${ins.length}.`);
      return;
    }
    if (ins.length > 12) {
      setError(`${ins.length} inputs → ${1 << ins.length} minterms. Above 12 inputs Quine-McCluskey can hang the browser. Reduce to ≤12 inputs.`);
      return;
    }
    setLoading(true); setError(null);
    try {
      const inNamesArr = ins.map((g, i) => g.label || String.fromCharCode(65 + i));
      const all: OutResult[] = [];
      for (const o of outs) {
        const m = await collectOutputMap(circuit, ins, o);
        all.push({ out: o, result: deriveBool(m, ins.length, inNamesArr) });
      }
      setResults(all);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setLoading(false); }
  }

  const inNames = ins.map((g, i) => g.label || String.fromCharCode(65 + i)).join(", ");

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

      {/* Variable legend — show which canvas gate becomes which letter */}
      {ins.length > 0 && (
        <div className="bg-bg-700/30 border border-bg-600 rounded p-2 flex-shrink-0">
          <div className="text-[8px] font-mono uppercase tracking-widest text-gray-600 mb-1">
            Inputs (left → right = MSB → LSB)
          </div>
          <div className="flex flex-wrap gap-1.5">
            {ins.map((g, i) => (
              <div key={g.id} className="flex items-center gap-1 text-[9px] font-mono">
                <span className="px-1.5 py-0.5 rounded bg-accent/15 text-accent font-bold">
                  {g.label || String.fromCharCode(65 + i)}
                </span>
                <span className="text-gray-600">= {g.id}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!results.length && !loading && !error && (
        <div className="text-[9px] text-gray-600 font-mono text-center py-3">
          One SOP / POS / minimised expression per OUTPUT.
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-3 min-h-0">
        {results.map(({ out, result }) => (
          <BoolBlock key={out.id} outName={out.label || out.id} r={result} inNames={inNames} />
        ))}
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
