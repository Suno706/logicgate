import { useState } from "react";
import { useCircuitState, useCircuitDispatch } from "../store";

interface Props {
  gateId: string | null;
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[9px] font-mono uppercase tracking-widest text-gray-600 w-16 flex-shrink-0">{label}</span>
      <span className="text-xs font-mono text-gray-300 truncate">{value}</span>
    </div>
  );
}

export function PropsPanel({ gateId }: Props) {
  const state    = useCircuitState();
  const dispatch = useCircuitDispatch();
  const { circuit, simOutputs } = state;
  const gate = gateId ? circuit.gates.find((g) => g.id === gateId) ?? null : null;

  const [editLabel, setEditLabel] = useState(false);
  const [labelVal,  setLabelVal]  = useState("");

  if (!gate) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <span className="text-xs text-gray-600 font-mono text-center px-4">
          Select a gate on the canvas to view its properties
        </span>
      </div>
    );
  }

  const simOut = simOutputs[gate.id];
  const wires  = circuit.wires.filter((w) => w.from_gate === gate.id || w.to_gate === gate.id);

  function startEdit() {
    setLabelVal(gate!.label ?? "");
    setEditLabel(true);
  }

  function commitEdit() {
    dispatch({ type: "RENAME_GATE", id: gate!.id, label: labelVal.trim() });
    setEditLabel(false);
  }

  async function toggleValue() {
    if (gate!.type !== "INPUT") return;
    dispatch({ type: "SET_GATE_VALUE", id: gate!.id, value: gate!.value === 1 ? 0 : 1 });
  }

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-4">
      <div className="space-y-1.5">
        <div className="text-[9px] font-mono uppercase tracking-widest text-gray-600 mb-2">Gate</div>
        <Row label="ID"   value={gate.id} />
        <Row label="Type" value={
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold" style={{ background: "#7c5cff20", color: "#bb99ff" }}>
            {gate.type}
          </span>
        } />
        <Row label="Pos" value={`(${gate.x}, ${gate.y})`} />
        <Row label="Label" value={
          editLabel ? (
            <input
              autoFocus
              className="bg-bg-700 border border-accent rounded px-1.5 py-0.5 text-xs font-mono text-gray-100 focus:outline-none w-28"
              value={labelVal}
              onChange={(e) => setLabelVal(e.target.value)}
              onBlur={commitEdit}
              onKeyDown={(e) => { if (e.key === "Enter") commitEdit(); if (e.key === "Escape") setEditLabel(false); }}
            />
          ) : (
            <button onClick={startEdit} className="text-gray-300 hover:text-accent transition-colors">
              {gate.label || <span className="text-gray-600 italic">none</span>}
              <span className="ml-1 text-[9px] text-gray-600">✎</span>
            </button>
          )
        } />
      </div>

      {/* Signal */}
      <div className="space-y-1.5">
        <div className="text-[9px] font-mono uppercase tracking-widest text-gray-600 mb-2">Signal</div>
        {(gate.type === "INPUT" || gate.type === "CLOCK") && (
          <div className="flex items-center gap-2">
            <span className="text-[9px] font-mono uppercase tracking-widest text-gray-600 w-16">Value</span>
            <button
              onClick={toggleValue}
              className={`px-3 py-1 rounded text-xs font-mono font-bold border transition-all ${
                gate.value === 1
                  ? "bg-ok/10 border-ok/50 text-ok"
                  : "bg-bg-700 border-bg-600 text-gray-500"
              }`}
            >
              {gate.value === 1 ? "HIGH (1)" : "LOW (0)"}
            </button>
          </div>
        )}
        {simOut !== undefined && (
          <Row label="Output" value={
            <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${simOut === 1 ? "bg-ok/10 text-ok" : "bg-err/10 text-err"}`}>
              {simOut === 1 ? "HIGH (1)" : "LOW (0)"}
            </span>
          } />
        )}
        {simOut === undefined && gate.type !== "INPUT" && gate.type !== "CLOCK" && (
          <div className="text-[9px] text-gray-600 font-mono">Run simulation to see output</div>
        )}
      </div>

      {/* Connections */}
      <div className="space-y-1.5">
        <div className="text-[9px] font-mono uppercase tracking-widest text-gray-600 mb-2">
          Connections ({wires.length})
        </div>
        {wires.length === 0 && <div className="text-[9px] text-gray-600 font-mono">No wires connected</div>}
        {wires.map((w) => {
          const isFrom = w.from_gate === gate.id;
          const other  = isFrom ? w.to_gate : w.from_gate;
          const otherG = circuit.gates.find((g) => g.id === other);
          return (
            <div key={w.id} className="flex items-center gap-2 text-[9px] font-mono text-gray-500">
              <span className={isFrom ? "text-ok" : "text-accent"}>
                {isFrom ? "→ out" : "← in"}
              </span>
              <span className="text-gray-400">{otherG?.label || otherG?.type || other}</span>
              <button
                onClick={() => dispatch({ type: "REMOVE_WIRE", id: w.id })}
                className="text-err/60 hover:text-err ml-auto"
              >✕</button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
