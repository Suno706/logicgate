import type { Gate, GateType, MacroGate, PinPos, Wire, Circuit } from "./types";
import { MACRO_SPECS } from "./types";

export const GATE_W = 80;
export const GATE_H = 60;
export const IO_W = 72;
export const IO_H = 48;
export const PIN_R = 4;
export const MACRO_W = 124;

const MACRO_TYPES = new Set<GateType>([
  "HA", "FA", "DFF", "JKFF", "TFF", "SRLATCH",
  "MUX2", "MUX4", "DEC24", "DEC38", "ENC42", "CMP2",
  "REG4",
]);

export function isMacro(type: GateType): type is MacroGate {
  return MACRO_TYPES.has(type);
}

export function gateDims(type: GateType): { w: number; h: number } {
  if (type === "INPUT" || type === "OUTPUT" || type === "CLOCK" ||
      type === "VCC"   || type === "GND"    || type === "LED") {
    return { w: IO_W, h: IO_H };
  }
  if (isMacro(type)) {
    const spec = MACRO_SPECS[type];
    const pinRows = Math.max(spec.inputs.length, spec.outputs.length);
    return { w: MACRO_W, h: Math.max(56, 20 + pinRows * 18) };
  }
  return { w: GATE_W, h: GATE_H };
}

export function inputPinCount(type: GateType): number {
  if (isMacro(type)) return MACRO_SPECS[type].inputs.length;
  switch (type) {
    case "INPUT":
    case "CLOCK":
    case "VCC":
    case "GND":
      return 0;
    case "NOT":
    case "BUF":
    case "OUTPUT":
    case "LED":
      return 1;
    default:
      return 2;
  }
}

export function outputPinCount(type: GateType): number {
  if (isMacro(type)) return MACRO_SPECS[type].outputs.length;
  if (type === "OUTPUT" || type === "LED") return 0;
  return 1;
}

export function getInputPins(gate: Gate): PinPos[] {
  const { h } = gateDims(gate.type);
  const n = inputPinCount(gate.type);
  const pins: PinPos[] = [];
  for (let i = 0; i < n; i++) {
    const y = n === 1 ? gate.y + h / 2 : gate.y + (h / (n + 1)) * (i + 1);
    pins.push({ x: gate.x, y, pin: i, isOutput: false });
  }
  return pins;
}

export function getOutputPins(gate: Gate): PinPos[] {
  const { w, h } = gateDims(gate.type);
  const n = outputPinCount(gate.type);
  if (n === 0) return [];
  const pins: PinPos[] = [];
  for (let i = 0; i < n; i++) {
    const y = n === 1 ? gate.y + h / 2 : gate.y + (h / (n + 1)) * (i + 1);
    pins.push({ x: gate.x + w, y, pin: i, isOutput: true });
  }
  return pins;
}

/** Bezier wire path; honors both from_pin and to_pin so multi-output gates
    (HA, FA, flip-flops) route correctly to the right pin. */
export function wirePath(fromGate: Gate, toGate: Gate, wire: Wire): string {
  const outs = getOutputPins(fromGate);
  const ins  = getInputPins(toGate);
  const out  = outs[wire.from_pin] ?? outs[0];
  const inp  = ins[wire.to_pin]   ?? ins[0];
  if (!out || !inp) return "";
  const dx = Math.max(40, Math.abs(inp.x - out.x) * 0.5);
  return `M ${out.x} ${out.y} C ${out.x + dx} ${out.y}, ${inp.x - dx} ${inp.y}, ${inp.x} ${inp.y}`;
}

export function hitGate(gate: Gate, wx: number, wy: number): boolean {
  const { w, h } = gateDims(gate.type);
  return wx >= gate.x && wx <= gate.x + w && wy >= gate.y && wy <= gate.y + h;
}

export function hitPin(pin: PinPos, wx: number, wy: number, r = 10): boolean {
  return Math.hypot(pin.x - wx, pin.y - wy) <= r;
}

export function screenToWorld(sx: number, sy: number, pan: { x: number; y: number }, zoom: number) {
  return { x: (sx - pan.x) / zoom, y: (sy - pan.y) / zoom };
}

export function worldToScreen(wx: number, wy: number, pan: { x: number; y: number }, zoom: number) {
  return { x: wx * zoom + pan.x, y: wy * zoom + pan.y };
}

export function snapToGrid(v: number, grid = 16): number {
  return Math.round(v / grid) * grid;
}

export function gateLabel(type: GateType): string {
  switch (type) {
    case "AND":  case "OR":   case "NOT":  case "NAND":
    case "NOR":  case "XOR":  case "XNOR": case "BUF":
      return type;
    case "INPUT":  return "IN";
    case "OUTPUT": return "OUT";
    case "CLOCK":  return "CLK";
    case "VCC":    return "VCC";
    case "GND":    return "GND";
    case "LED":    return "LED";
    case "HA":     return "½ ADD";
    case "FA":     return "FULL ADD";
    case "DFF":    return "D-FF";
    case "JKFF":   return "JK-FF";
    case "TFF":    return "T-FF";
    case "SRLATCH":return "SR LATCH";
    case "MUX2":   return "MUX 2:1";
    case "MUX4":   return "MUX 4:1";
    case "DEC24":  return "DEC 2:4";
    case "DEC38":  return "DEC 3:8";
    case "ENC42":  return "ENC 4:2";
    case "CMP2":   return "CMP 2";
    case "REG4":   return "4-BIT REG";
    default:       return type;
  }
}

export function wireSignalValue(
  wire: Wire,
  simOutputs: Record<string, 0 | 1>,
  gates: Gate[],
): 0 | 1 | null {
  const src = gates.find((g) => g.id === wire.from_gate);
  if (!src) return null;
  if (src.type === "INPUT" || src.type === "CLOCK") return src.value ?? 0;
  if (src.type === "VCC") return 1;
  if (src.type === "GND") return 0;
  // Multi-output gates (macros) emit per-pin entries as "id:pin"
  const pinned = simOutputs[`${src.id}:${wire.from_pin}` as keyof typeof simOutputs];
  if (pinned !== undefined) return pinned;
  const val = simOutputs[src.id];
  return val !== undefined ? val : null;
}

export function buildTruthTable(
  circuit: Circuit,
  simFn: (inputs: Record<string, 0 | 1>) => Promise<Record<string, 0 | 1>>,
): Promise<{ headers: string[]; rows: (0 | 1)[][] }> {
  const inputs = circuit.gates.filter((g) => g.type === "INPUT" || g.type === "CLOCK");
  const outputs = circuit.gates.filter((g) => g.type === "OUTPUT" || g.type === "LED");
  if (!inputs.length || !outputs.length) {
    return Promise.resolve({ headers: [], rows: [] });
  }
  const n = inputs.length;
  const rows: (0 | 1)[][] = [];
  const promises: Promise<void>[] = [];

  for (let mask = 0; mask < 1 << n; mask++) {
    const idx = mask;
    const inputVals: Record<string, 0 | 1> = {};
    inputs.forEach((inp, i) => {
      inputVals[inp.id] = (idx >> (n - 1 - i)) & 1 ? 1 : 0;
    });
    promises.push(
      simFn(inputVals).then((outs) => {
        const row: (0 | 1)[] = [
          ...inputs.map((_, i) => (((idx >> (n - 1 - i)) & 1) as 0 | 1)),
          ...outputs.map((o) => (outs[o.id] ?? 0) as 0 | 1),
        ];
        rows[idx] = row;
      }),
    );
  }

  return Promise.all(promises).then(() => ({
    headers: [
      ...inputs.map((g) => g.label ?? gateLabel(g.type)),
      ...outputs.map((g) => g.label ?? gateLabel(g.type)),
    ],
    rows,
  }));
}
