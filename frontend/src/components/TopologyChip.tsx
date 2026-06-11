import { useEffect, useRef, useState } from "react";
import { Sparkles, Loader2 } from "lucide-react";
import { useCircuitState } from "../store";

/** TopologyChip — floats at the bottom-left of the canvas and shows the
 *  ML topology classifier's live prediction of what the user is building.
 *
 *  Debounced so we don't hammer the backend on every drag. Hidden when
 *  the circuit is empty so it doesn't fight the canvas empty state. */

interface ApiResp {
  top:   [string, number][];
  ready: boolean;
  note?: string;
}

const FRIENDLY: Record<string, string> = {
  half_adder:           "Half Adder",
  full_adder:           "Full Adder",
  two_to_one_mux:       "2:1 MUX",
  four_to_one_mux:      "4:1 MUX",
  two_to_four_decoder:  "2→4 Decoder",
  d_flip_flop:          "D Flip-Flop",
  jk_flip_flop:         "JK Flip-Flop",
  sr_latch:             "SR Latch",
  n_bit_register:       "N-bit Register",
  generic:              "Custom circuit",
};

export function TopologyChip() {
  const { circuit } = useCircuitState();
  const [resp, setResp]       = useState<ApiResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExp]    = useState(false);
  const timer = useRef<number | null>(null);

  const gates = circuit.gates.length;
  const wires = circuit.wires.length;

  useEffect(() => {
    if (gates < 2) {
      setResp(null);
      return;
    }
    // Debounce: only fire 350 ms after the last edit, so dragging a wire
    // around doesn't spam the endpoint.
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      setLoading(true);
      try {
        const r = await fetch("/api/topology/classify", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ circuit }),
        });
        if (!r.ok) {
          setResp(null);
          return;
        }
        const data: ApiResp = await r.json();
        setResp(data);
      } catch {
        setResp(null);
      } finally {
        setLoading(false);
      }
    }, 350);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gates, wires]);

  if (gates < 2) return null;
  if (!resp || resp.top.length === 0) {
    return (
      <div className="absolute bottom-2 left-2 z-20 px-3 py-1.5 rounded-full bg-bg-800/90 border border-bg-600 text-[11px] text-gray-500 backdrop-blur shadow-lg flex items-center gap-2">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
        Classifier warming up…
      </div>
    );
  }

  const top   = resp.top[0];
  const label = FRIENDLY[top[0]] || top[0];
  const conf  = Math.round(top[1] * 100);
  const confColour =
    conf >= 80 ? "text-ok"
    : conf >= 50 ? "text-warn"
    : "text-gray-400";

  return (
    <div
      onClick={() => setExp((v) => !v)}
      title="Topology classifier — RandomForest on 34 structural features. Click for top-3."
      className="absolute bottom-2 left-2 z-20 cursor-pointer select-none rounded-xl bg-bg-800/90 border border-accent/30 backdrop-blur shadow-lg overflow-hidden hover:border-accent/60 transition-colors"
    >
      <div className="flex items-center gap-2 px-3 py-1.5 text-[11px]">
        {loading ? <Loader2 size={12} className="animate-spin text-accent" />
                 : <Sparkles size={12} className="text-accent" />}
        <span className="text-gray-500">Looks like</span>
        <span className="text-gray-100 font-medium">{label}</span>
        <span className={`font-mono tabular-nums ${confColour}`}>
          {conf}%
        </span>
      </div>
      {expanded && resp.top.length > 1 && (
        <div className="border-t border-bg-600 px-3 py-2 text-[10px] text-gray-500 space-y-0.5">
          {resp.top.slice(1).map(([lbl, p]) => (
            <div key={lbl} className="flex items-center gap-2 tabular-nums">
              <span className="flex-1">{FRIENDLY[lbl] || lbl}</span>
              <span>{Math.round(p * 100)}%</span>
            </div>
          ))}
          <div className="pt-1 mt-1 border-t border-bg-600 text-[9px] text-gray-600">
            RandomForest · 34 structural features
          </div>
        </div>
      )}
    </div>
  );
}
