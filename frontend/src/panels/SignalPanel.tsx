import { useCircuitState } from "../store";

export function SignalPanel() {
  const { circuit, simOutputs } = useCircuitState();
  const items = circuit.gates.filter((g) =>
    g.type === "INPUT" || g.type === "CLOCK" ||
    g.type === "OUTPUT" || g.type === "LED" ||
    simOutputs[g.id] !== undefined,
  );

  return (
    <div className="flex-1 flex flex-col p-3 gap-2 min-h-0 overflow-hidden">
      <div className="text-[8px] font-mono uppercase tracking-widest text-gray-600">
        Signal Levels  · {items.length} gates
      </div>

      {items.length === 0 && (
        <div className="text-[9px] text-gray-600 font-mono text-center py-4">
          Run a simulation to see signal levels.
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-1.5 min-h-0">
        {items.map((g) => {
          const v = g.type === "INPUT" || g.type === "CLOCK"
            ? g.value ?? 0
            : simOutputs[g.id];
          const known = v !== undefined;
          const high  = v === 1;
          return (
            <div key={g.id} className="bg-bg-700/40 border border-bg-600 rounded px-2 py-1.5 flex items-center gap-2">
              <div className="w-16 flex-shrink-0">
                <div className="text-[10px] font-mono font-bold text-gray-200 truncate">{g.label || g.id}</div>
                <div className="text-[7px] font-mono text-gray-700">{g.type}</div>
              </div>
              <div className="flex-1 h-8 relative bg-bg-800 rounded overflow-hidden">
                {known && (
                  <>
                    <div className={`absolute top-1/2 left-0 h-px ${high ? "bg-ok" : "bg-err"}`}
                         style={{ width: "20%" }} />
                    <div className={`absolute ${high ? "top-1 bottom-1/2" : "top-1/2 bottom-1"} ${high ? "bg-ok/30" : "bg-err/20"}`}
                         style={{ left: "20%", width: "60%" }} />
                    <div className={`absolute left-1/5 h-full w-px ${high ? "bg-ok" : "bg-err"}`}
                         style={{ left: "20%" }} />
                    <div className={`absolute right-1/5 h-full w-px ${high ? "bg-ok" : "bg-err"}`}
                         style={{ right: "20%" }} />
                    <div className={`absolute top-1/2 right-0 h-px ${high ? "bg-ok" : "bg-err"}`}
                         style={{ width: "20%" }} />
                  </>
                )}
              </div>
              <div className={`w-10 text-right font-mono font-bold text-xs ${
                !known ? "text-gray-600" : high ? "text-ok" : "text-err"
              }`}>
                {!known ? "?" : high ? "HIGH" : "LOW"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
