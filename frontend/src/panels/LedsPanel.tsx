import { useCircuitState } from "../store";
import { Circle } from "lucide-react";

export function LedsPanel() {
  const { circuit, simOutputs } = useCircuitState();
  const outputs = circuit.gates.filter((g) => g.type === "OUTPUT" || g.type === "LED");
  const ins     = circuit.gates.filter((g) => g.type === "INPUT" || g.type === "CLOCK");

  return (
    <div className="flex-1 flex flex-col p-3 gap-4 min-h-0 overflow-y-auto">

      <div>
        <div className="text-[8px] font-mono uppercase tracking-widest text-gray-600 mb-2">
          Inputs
        </div>
        <div className="grid grid-cols-2 gap-2">
          {ins.length === 0 && <div className="col-span-2 text-[9px] text-gray-600 font-mono">No inputs</div>}
          {ins.map((g) => <Led key={g.id} name={g.label || g.id} type={g.type} value={g.value ?? 0} />)}
        </div>
      </div>

      <div>
        <div className="text-[8px] font-mono uppercase tracking-widest text-gray-600 mb-2">
          Outputs
        </div>
        <div className="grid grid-cols-2 gap-2">
          {outputs.length === 0 && <div className="col-span-2 text-[9px] text-gray-600 font-mono">No outputs</div>}
          {outputs.map((g) => {
            const v = simOutputs[g.id];
            return <Led key={g.id} name={g.label || g.id} type={g.type} value={v} />;
          })}
        </div>
      </div>

      {Object.keys(simOutputs).length === 0 && outputs.length > 0 && (
        <div className="text-[9px] text-gray-600 font-mono text-center">
          Press ▶ Simulate to light up the LEDs
        </div>
      )}
    </div>
  );
}

function Led({ name, type, value }: { name: string; type: string; value: 0 | 1 | undefined }) {
  const on  = value === 1;
  const off = value === 0;
  const unk = value === undefined;

  const color = on ? "#3ddc97" : off ? "#ff5577" : "#3a4a5a";
  const glow  = on ? "0 0 18px #3ddc9788, 0 0 4px #3ddc97" : "none";

  return (
    <div className={`bg-bg-700 border rounded-lg p-2 flex flex-col items-center gap-1 ${
      on ? "border-ok/40" : off ? "border-err/30" : "border-bg-600"
    }`}>
      <div className="text-[8px] font-mono text-gray-500 truncate w-full text-center">{name}</div>
      <div className="relative">
        <Circle size={28} strokeWidth={2}
          style={{ color, filter: on ? "drop-shadow(0 0 6px #3ddc97)" : undefined, boxShadow: glow }} />
        {on  && <div className="absolute inset-0 flex items-center justify-center text-ok  font-mono font-bold text-[10px]">1</div>}
        {off && <div className="absolute inset-0 flex items-center justify-center text-err font-mono font-bold text-[10px]">0</div>}
        {unk && <div className="absolute inset-0 flex items-center justify-center text-gray-700 font-mono font-bold text-[10px]">?</div>}
      </div>
      <div className="text-[7px] font-mono text-gray-700">{type}</div>
    </div>
  );
}
