import {
  useRef, useState, useEffect,
  type PointerEvent, type WheelEvent,
} from "react";
import type { Gate, Wire, GateType } from "../types";
import { GateShape } from "./GateShape";
import {
  gateDims, getInputPins, getOutputPins, wirePath,
  hitGate, hitPin, screenToWorld, snapToGrid, wireSignalValue,
} from "../utils";
import { useCircuitState, useCircuitDispatch, makeGate } from "../store";
import type { Tool } from "../types";

interface Props {
  tool: Tool;
  snapGrid: boolean;
  pendingType: GateType | null;
  onClearPending: () => void;
  onGateSelected: (id: string | null) => void;
}

interface WireStart {
  gateId: string;
  pin: number;
  wx: number;
  wy: number;
}

const ZOOM_MIN = 0.2;
const ZOOM_MAX = 4;
const GRID = 16;

export function Canvas({ tool, snapGrid, pendingType, onClearPending, onGateSelected }: Props) {
  const state  = useCircuitState();
  const dispatch = useCircuitDispatch();
  const { circuit, selected, simOutputs } = state;

  const svgRef = useRef<SVGSVGElement>(null);

  const [pan,  setPan]  = useState({ x: 80, y: 60 });
  const [zoom, setZoom] = useState(1);

  /* mutable interaction refs — avoid stale closure in pointer events */
  const dragRef   = useRef<{ ids: string[]; origins: { id: string; x: number; y: number }[]; startW: { x: number; y: number } } | null>(null);
  const panRef    = useRef<{ startS: { x: number; y: number }; startPan: { x: number; y: number } } | null>(null);
  const selBoxRef = useRef<{ startW: { x: number; y: number } } | null>(null);
  /* Click-vs-drag detection: if a pointer-down on a gate releases without
     moving more than CLICK_THRESHOLD world units, treat it as a click. */
  const clickRef  = useRef<{ gateId: string; type: string; startW: { x: number; y: number }; time: number } | null>(null);
  const panState  = useRef(pan);
  const zoomState = useRef(zoom);
  useEffect(() => { panState.current = pan; }, [pan]);
  useEffect(() => { zoomState.current = zoom; }, [zoom]);

  const [wireStart,   setWireStart]   = useState<WireStart | null>(null);
  /* mirror in a ref so pointer-event handlers always see the latest value */
  const wireStartRef = useRef<WireStart | null>(null);
  useEffect(() => { wireStartRef.current = wireStart; }, [wireStart]);

  /* monotonic wire id counter — Date.now() collides at sub-ms speed */
  const wireCounter = useRef(0);
  function newWireId() { return `w${Date.now()}_${++wireCounter.current}`; }
  const [mouseW,      setMouseW]      = useState({ x: 0, y: 0 });
  const [hoveredGate, setHoveredGate] = useState<string | null>(null);
  const [hoveredPin,  setHoveredPin]  = useState<{ gateId: string; pin: number; isOutput: boolean } | null>(null);
  const [selBox,      setSelBox]      = useState<{ x: number; y: number; w: number; h: number } | null>(null);

  /* helpers */
  function svgRect() { return svgRef.current!.getBoundingClientRect(); }

  function toWorld(clientX: number, clientY: number) {
    const r = svgRect();
    return screenToWorld(clientX - r.left, clientY - r.top, panState.current, zoomState.current);
  }

  function findGate(wx: number, wy: number): Gate | null {
    for (let i = circuit.gates.length - 1; i >= 0; i--) {
      if (hitGate(circuit.gates[i], wx, wy)) return circuit.gates[i];
    }
    return null;
  }

  function findPin(wx: number, wy: number) {
    for (const gate of circuit.gates) {
      for (const p of getOutputPins(gate)) {
        if (hitPin(p, wx, wy, 10)) return { gateId: gate.id, pin: p.pin, isOutput: true, x: p.x, y: p.y };
      }
      for (const p of getInputPins(gate)) {
        if (hitPin(p, wx, wy, 10)) return { gateId: gate.id, pin: p.pin, isOutput: false, x: p.x, y: p.y };
      }
    }
    return null;
  }

  function snap(v: number) { return snapGrid ? snapToGrid(v, GRID) : Math.round(v); }

  /* ── pointer down ───────────────────────────────────────────────── */
  function onPointerDown(e: PointerEvent<SVGSVGElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
    const w = toWorld(e.clientX, e.clientY);
    const sx = e.clientX - svgRect().left;
    const sy = e.clientY - svgRect().top;

    /* pan: middle-mouse or alt+left or hand tool */
    if (e.button === 1 || (e.button === 0 && e.altKey) || tool === "hand") {
      panRef.current = { startS: { x: sx, y: sy }, startPan: panState.current };
      return;
    }

    /* place gate from palette */
    if (pendingType && e.button === 0) {
      const g = makeGate(pendingType, snap(w.x - 40), snap(w.y - 28));
      dispatch({ type: "ADD_GATE", gate: g });
      onGateSelected(g.id);
      onClearPending();
      return;
    }

    if (e.button !== 0) return;

    /* wire tool: click on output pin to start, input pin to finish */
    if (tool === "wire") {
      const pin = findPin(w.x, w.y);
      const ws  = wireStartRef.current;
      if (pin?.isOutput) {
        const next = { gateId: pin.gateId, pin: pin.pin, wx: pin.x, wy: pin.y };
        setWireStart(next);
        wireStartRef.current = next;
      } else if (pin && !pin.isOutput && ws && ws.gateId !== pin.gateId) {
        dispatch({ type: "ADD_WIRE", wire: { id: newWireId(), from_gate: ws.gateId, from_pin: ws.pin, to_gate: pin.gateId, to_pin: pin.pin } });
        setWireStart(null);
        wireStartRef.current = null;
      } else {
        setWireStart(null);
        wireStartRef.current = null;
      }
      return;
    }

    /* select tool */
    const pin = findPin(w.x, w.y);
    if (pin?.isOutput) {
      /* drag-wire from select mode too */
      setWireStart({ gateId: pin.gateId, pin: pin.pin, wx: pin.x, wy: pin.y });
      return;
    }

    const gate = findGate(w.x, w.y);
    if (gate) {
      if (!selected.has(gate.id)) {
        dispatch({ type: "SELECT", ids: [gate.id], add: e.shiftKey });
        onGateSelected(gate.id);
      } else if (e.shiftKey) {
        /* deselect individual */
        const next = new Set(selected);
        next.delete(gate.id);
        dispatch({ type: "SELECT", ids: [...next] });
        onGateSelected(null);
        return;
      } else {
        onGateSelected(gate.id);
      }
      const ids = selected.has(gate.id)
        ? [...selected]
        : [gate.id];
      dragRef.current = {
        ids,
        origins: circuit.gates.filter((g) => ids.includes(g.id)).map((g) => ({ id: g.id, x: g.x, y: g.y })),
        startW: w,
      };
      /* Remember this pointer-down as a potential click-to-toggle on INPUT.
         If the user releases without dragging, we toggle the value. */
      clickRef.current = { gateId: gate.id, type: gate.type, startW: w, time: Date.now() };
    } else {
      if (!e.shiftKey) {
        dispatch({ type: "CLEAR_SELECTION" });
        onGateSelected(null);
      }
      selBoxRef.current = { startW: w };
    }
  }

  /* ── pointer move ───────────────────────────────────────────────── */
  function onPointerMove(e: PointerEvent<SVGSVGElement>) {
    const sx = e.clientX - svgRect().left;
    const sy = e.clientY - svgRect().top;
    const w  = toWorld(e.clientX, e.clientY);
    setMouseW(w);

    /* hover */
    const pin = findPin(w.x, w.y);
    if (pin) { setHoveredPin({ gateId: pin.gateId, pin: pin.pin, isOutput: pin.isOutput }); setHoveredGate(null); }
    else      { setHoveredPin(null); setHoveredGate(findGate(w.x, w.y)?.id ?? null); }

    if (panRef.current) {
      const { startS, startPan } = panRef.current;
      setPan({ x: startPan.x + (sx - startS.x), y: startPan.y + (sy - startS.y) });
      return;
    }

    if (dragRef.current) {
      const dx = w.x - dragRef.current.startW.x;
      const dy = w.y - dragRef.current.startW.y;
      dragRef.current.origins.forEach(({ id, x, y }) => {
        dispatch({ type: "MOVE_GATE", id, x: snap(x + dx), y: snap(y + dy) });
      });
      return;
    }

    if (selBoxRef.current) {
      const { startW } = selBoxRef.current;
      setSelBox({ x: Math.min(startW.x, w.x), y: Math.min(startW.y, w.y), w: Math.abs(w.x - startW.x), h: Math.abs(w.y - startW.y) });
    }
  }

  /* ── pointer up ─────────────────────────────────────────────────── */
  function onPointerUp(e: PointerEvent<SVGSVGElement>) {
    e.currentTarget.releasePointerCapture(e.pointerId);
    const w = toWorld(e.clientX, e.clientY);

    /* finish drag-wire in select mode */
    const ws = wireStartRef.current;
    if (ws && tool !== "wire") {
      const pin = findPin(w.x, w.y);
      if (pin && !pin.isOutput && pin.gateId !== ws.gateId) {
        dispatch({ type: "ADD_WIRE", wire: { id: newWireId(), from_gate: ws.gateId, from_pin: ws.pin, to_gate: pin.gateId, to_pin: pin.pin } });
      }
      setWireStart(null);
      wireStartRef.current = null;
    }

    /* finish box-select */
    if (selBoxRef.current && selBox) {
      const { x, y, w: bw, h: bh } = selBox;
      const ids = circuit.gates.filter((g) => {
        const { w: gw, h: gh } = gateDims(g.type);
        return g.x + gw >= x && g.x <= x + bw && g.y + gh >= y && g.y <= y + bh;
      }).map((g) => g.id);
      dispatch({ type: "SELECT", ids, add: e.shiftKey });
      if (ids.length === 1) onGateSelected(ids[0]);
    }

    /* Click-to-toggle: if pointer-down landed on an INPUT and released
       without dragging (≤ 4 world-units, ≤ 350ms), toggle the value. */
    const click = clickRef.current;
    if (click && (click.type === "INPUT" || click.type === "CLOCK")) {
      const upW = toWorld(e.clientX, e.clientY);
      const dx  = upW.x - click.startW.x;
      const dy  = upW.y - click.startW.y;
      const dt  = Date.now() - click.time;
      if (dx * dx + dy * dy <= 16 && dt <= 350) {
        const cur = circuit.gates.find((g) => g.id === click.gateId);
        if (cur) {
          dispatch({ type: "SET_GATE_VALUE", id: click.gateId, value: cur.value === 1 ? 0 : 1 });
        }
      }
    }

    clickRef.current  = null;
    dragRef.current   = null;
    panRef.current    = null;
    selBoxRef.current = null;
    setSelBox(null);
  }

  /* ── wheel zoom ─────────────────────────────────────────────────── */
  function onWheel(e: WheelEvent<SVGSVGElement>) {
    e.preventDefault();
    const r  = svgRect();
    const sx = e.clientX - r.left;
    const sy = e.clientY - r.top;
    const factor   = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const newZoom  = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoomState.current * factor));
    const wx = (sx - panState.current.x) / zoomState.current;
    const wy = (sy - panState.current.y) / zoomState.current;
    setPan({ x: sx - wx * newZoom, y: sy - wy * newZoom });
    setZoom(newZoom);
  }

  /* ── keyboard ───────────────────────────────────────────────────── */
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "Delete" || e.key === "Backspace") dispatch({ type: "REMOVE_SELECTED" });
      if ((e.ctrlKey || e.metaKey) && e.key === "a") { e.preventDefault(); dispatch({ type: "SELECT_ALL" }); }
      if ((e.ctrlKey || e.metaKey) && e.key === "z") { e.preventDefault(); dispatch({ type: "UNDO" }); }
      if ((e.ctrlKey || e.metaKey) && (e.key === "y" || (e.shiftKey && e.key === "z"))) { e.preventDefault(); dispatch({ type: "REDO" }); }
      if (e.key === "Escape") { setWireStart(null); dispatch({ type: "CLEAR_SELECTION" }); onGateSelected(null); onClearPending(); }
      /* zoom shortcuts */
      if ((e.ctrlKey || e.metaKey) && e.key === "=") { e.preventDefault(); setZoom((z) => Math.min(ZOOM_MAX, z * 1.2)); }
      if ((e.ctrlKey || e.metaKey) && e.key === "-") { e.preventDefault(); setZoom((z) => Math.max(ZOOM_MIN, z / 1.2)); }
      if ((e.ctrlKey || e.metaKey) && e.key === "0") { e.preventDefault(); setZoom(1); setPan({ x: 80, y: 60 }); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dispatch, onClearPending, onGateSelected]);

  /* ── fit-to-view: pan/zoom so all gates are visible ─────────────────── */
  useEffect(() => {
    function fit() {
      if (circuit.gates.length === 0) return;
      const margin = 60;
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const g of circuit.gates) {
        const { w, h } = gateDims(g.type);
        if (g.x < minX) minX = g.x;
        if (g.y < minY) minY = g.y;
        if (g.x + w > maxX) maxX = g.x + w;
        if (g.y + h > maxY) maxY = g.y + h;
      }
      const sr  = svgRect();
      const cw  = maxX - minX + margin * 2;
      const ch  = maxY - minY + margin * 2;
      const z   = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN,
                           Math.min(sr.width / cw, sr.height / ch)));
      setZoom(z);
      // Center the bounding box in the viewport.
      const newPanX = sr.width  / 2 - (minX + (maxX - minX) / 2) * z;
      const newPanY = sr.height / 2 - (minY + (maxY - minY) / 2) * z;
      setPan({ x: newPanX, y: newPanY });
    }
    window.addEventListener("logicgate:fit-view", fit);
    return () => window.removeEventListener("logicgate:fit-view", fit);
  }, [circuit.gates]);

  /* ── auto-pulsing CLOCK ─────────────────────────────────────────────
     Every CLOCK gate flips its value at the configured frequency. The
     simulator picks it up on the next tick. Default 2 Hz (500 ms half-period). */
  useEffect(() => {
    const clocks = circuit.gates.filter((g) => g.type === "CLOCK");
    if (!clocks.length) return;
    const HALF_PERIOD_MS = 500;   // 1 Hz square wave
    const id = window.setInterval(() => {
      // Read latest values via the closure — circuit reference is fresh on each
      // render so the effect re-binds when gates change.
      for (const c of clocks) {
        dispatch({ type: "SET_GATE_VALUE", id: c.id, value: (c.value === 1 ? 0 : 1) as 0 | 1 });
      }
    }, HALF_PERIOD_MS);
    return () => window.clearInterval(id);
  }, [circuit.gates, dispatch]);

  /* ── wire click (delete) ────────────────────────────────────────── */
  function onWireClick(wire: Wire, e: React.MouseEvent) {
    e.stopPropagation();
    if (tool === "select") dispatch({ type: "REMOVE_WIRE", id: wire.id });
  }

  /* ── input gate toggle ──────────────────────────────────────────── */
  function onGateDblClick(gate: Gate, e: React.MouseEvent) {
    e.stopPropagation();
    if (gate.type === "INPUT") {
      dispatch({ type: "SET_GATE_VALUE", id: gate.id, value: gate.value === 1 ? 0 : 1 });
    }
  }

  /* ── build lookup ───────────────────────────────────────────────── */
  const byId = new Map(circuit.gates.map((g) => [g.id, g]));

  const cursor =
    tool === "hand"  ? "cursor-grab"
    : wireStart      ? "cursor-crosshair"
    : pendingType    ? "cursor-copy"
    : "cursor-default";

  return (
    <svg
      ref={svgRef}
      className={`w-full h-full select-none bg-bg-900 ${cursor}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onWheel={onWheel}
      style={{ touchAction: "none" }}
    >
      {/* dot grid — uses theme token so it stays visible in both modes */}
      <defs>
        <pattern id="cdot" width={GRID * zoom} height={GRID * zoom} patternUnits="userSpaceOnUse"
          x={pan.x % (GRID * zoom)} y={pan.y % (GRID * zoom)}>
          <circle cx={0} cy={0} r={0.7} fill="var(--lg-bg-600)" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#cdot)" />

      <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>

        {/* ── wires ── */}
        {circuit.wires.map((wire) => {
          const from = byId.get(wire.from_gate);
          const to   = byId.get(wire.to_gate);
          if (!from || !to) return null;
          const d   = wirePath(from, to, wire);
          const sig = wireSignalValue(wire, simOutputs, circuit.gates);
          const col = sig === 1 ? "#3ddc97" : sig === 0 ? "#3a4a5a" : "#3a3a5a";
          return (
            <path key={wire.id} d={d} stroke={col} strokeWidth={2} fill="none"
              strokeLinecap="round"
              style={{ cursor: tool === "select" ? "pointer" : "default" }}
              onClick={(ev) => onWireClick(wire, ev)}>
              <title>Click to delete wire</title>
            </path>
          );
        })}

        {/* ── in-progress wire ── */}
        {wireStart && (
          <path
            d={`M ${wireStart.wx} ${wireStart.wy} C ${wireStart.wx + 50} ${wireStart.wy}, ${mouseW.x - 50} ${mouseW.y}, ${mouseW.x} ${mouseW.y}`}
            stroke="#7c5cff" strokeWidth={1.5} fill="none"
            strokeDasharray="6 3" strokeLinecap="round" pointerEvents="none"
          />
        )}

        {/* ── gates ── */}
        {circuit.gates.map((g) => (
          <g key={g.id} onDoubleClick={(e) => onGateDblClick(g, e)}>
            <GateShape
              type={g.type} label={g.label} x={g.x} y={g.y}
              value={g.value}
              simOutput={simOutputs[g.id] !== undefined ? simOutputs[g.id] : null}
              selected={selected.has(g.id)}
              hovered={hoveredGate === g.id}
            />
          </g>
        ))}

        {/* ── pin highlight ── */}
        {hoveredPin && (() => {
          const gate = byId.get(hoveredPin.gateId);
          if (!gate) return null;
          const pins = hoveredPin.isOutput ? getOutputPins(gate) : getInputPins(gate);
          const p    = pins[hoveredPin.pin];
          if (!p) return null;
          return (
            <circle cx={p.x} cy={p.y} r={7}
              fill={hoveredPin.isOutput ? "#7c5cff30" : "#3ddc9730"}
              stroke={hoveredPin.isOutput ? "#7c5cff" : "#3ddc97"}
              strokeWidth={1.5} pointerEvents="none" />
          );
        })()}

        {/* ── selection box ── */}
        {selBox && (
          <rect x={selBox.x} y={selBox.y} width={selBox.w} height={selBox.h}
            fill="#7c5cff0c" stroke="#7c5cff" strokeWidth={1}
            strokeDasharray="4 2" pointerEvents="none" />
        )}
      </g>

      {/* ── HUD: zoom + hints ── */}
      <text x={10} y={16} fontSize={10} fill="#2a3a4a" fontFamily="JetBrains Mono, monospace">
        {Math.round(zoom * 100)}%
      </text>
      {wireStart && (
        <text x={10} y={28} fontSize={9} fill="#7c5cff" fontFamily="JetBrains Mono, monospace">
          Click an input pin to connect · Esc to cancel
        </text>
      )}
      {pendingType && (
        <text x={10} y={28} fontSize={9} fill="#ffb454" fontFamily="JetBrains Mono, monospace">
          Click to place {pendingType} · Esc to cancel
        </text>
      )}
    </svg>
  );
}

/* ── Empty-canvas welcome overlay ────────────────────────────────────────── */
export function CanvasEmptyState() {
  return (
    <div className="absolute inset-0 flex items-center justify-center pointer-events-none select-none">
      <div className="text-center space-y-3 opacity-30">
        <div className="text-4xl font-mono font-black text-gray-500 tracking-tight">LG</div>
        <div className="text-xs font-mono text-gray-600 space-y-1">
          <div>Pick a gate from the left panel and click to place</div>
          <div className="text-gray-700">or use the Smart panel to build from a description</div>
        </div>
      </div>
    </div>
  );
}
