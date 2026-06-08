import type { GateType } from "../types";
import { MACRO_SPECS } from "../types";
import { gateDims, inputPinCount, outputPinCount, isMacro, gateLabel } from "../utils";

/* ── Palette (matches old templates/index.html) ───────────────────────────── */

const STROKE: Record<string, string> = {
  AND:    "#4a8fff",
  NAND:   "#ff6b6b",
  OR:     "#4abb4a",
  NOR:    "#ffaa44",
  XOR:    "#bb77ff",
  XNOR:   "#44aaff",
  NOT:    "#ff8844",
  BUF:    "#44ffaa",
  INPUT:  "#7c5cff",
  OUTPUT: "#3ddc97",
  CLOCK:  "#ffb454",
  VCC:    "#3ddc97",
  GND:    "#9aa6bf",
  LED:    "#ff5577",
  HA:     "#7c5cff",
  FA:     "#7c5cff",
  DFF:    "#bb77ff",
  JKFF:   "#bb77ff",
  TFF:    "#bb77ff",
  SRLATCH:"#bb77ff",
};

function strokeOf(type: GateType) { return STROKE[type] ?? "#7c5cff"; }

/* ── Pin labels for primitive gates (matches old buildPins) ───────────────── */

function defaultPinLabels(type: GateType): { ins: string[]; outs: string[] } {
  if (isMacro(type)) {
    const s = MACRO_SPECS[type];
    return { ins: s.inputs, outs: s.outputs };
  }
  const ni = inputPinCount(type);
  const no = outputPinCount(type);
  const ins  = ni === 0 ? [] : ni === 1 ? ["A"] : Array.from({ length: ni }, (_, i) => String.fromCharCode(65 + i));
  const outs = no === 0 ? [] : no === 1 ? ["Q"] : Array.from({ length: no }, (_, i) => `Q${i}`);
  return { ins, outs };
}

/* ── Gate body shapes — ported from templates/index.html gateShape() ──────── */

const ML = 18;  // left margin inside the gate viewBox (matches old HTML)
const MR = 18;  // right margin

function GateBody({ type, w, h }: { type: GateType; w: number; h: number }) {
  const col = strokeOf(type);
  const fill = col + "12";          // 12 hex = ~7% alpha
  const sw = 1.5;

  // INPUT — toggle-switch graphic (matches old HTML)
  if (type === "INPUT") {
    return <rect x={5} y={4} width={w - 10} height={h - 8} rx={7}
      fill={fill} stroke={col} strokeWidth={sw} />;
  }

  // OUTPUT — rounded rect + bulb (the bulb is drawn separately on the main shape)
  if (type === "OUTPUT") {
    return <rect x={5} y={4} width={w - 10} height={h - 8} rx={7}
      fill={fill} stroke={col} strokeWidth={sw} />;
  }

  // CLOCK — rounded rect (square wave drawn separately on the main shape)
  if (type === "CLOCK") {
    return <rect x={5} y={4} width={w - 10} height={h - 8} rx={7}
      fill={fill} stroke={col} strokeWidth={sw} />;
  }

  // VCC — T-shape (no rect)
  if (type === "VCC") {
    return (
      <>
        <line x1={w / 2} y1={20} x2={w / 2} y2={h - 6}
          stroke={col} strokeWidth={2} />
        <line x1={w / 2 - 14} y1={20} x2={w / 2 + 14} y2={20}
          stroke={col} strokeWidth={2} />
      </>
    );
  }

  // GND — ground rake (3 lines of decreasing width)
  if (type === "GND") {
    return (
      <>
        <line x1={w / 2} y1={18} x2={w / 2} y2={28}
          stroke={col} strokeWidth={2} />
        <line x1={w / 2 - 14} y1={28} x2={w / 2 + 14} y2={28}
          stroke={col} strokeWidth={2} />
        <line x1={w / 2 - 9}  y1={32} x2={w / 2 + 9}  y2={32}
          stroke={col} strokeWidth={2} />
        <line x1={w / 2 - 5}  y1={36} x2={w / 2 + 5}  y2={36}
          stroke={col} strokeWidth={2} />
      </>
    );
  }

  // LED — bulb with two leads (lit state handled via the value glow above)
  if (type === "LED") {
    return null;   // drawn in the main render below for finer control
  }

  // Macro components: labelled rectangle with title bar
  if (isMacro(type)) {
    return (
      <>
        <rect x={6} y={4} width={w - 12} height={h - 8} rx={6}
          fill={fill} stroke={col} strokeWidth={sw} />
        <text x={w / 2} y={h / 2 + 4} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace" fontSize={10}
          fontWeight={700} letterSpacing={1} pointerEvents="none">
          {gateLabel(type)}
        </text>
      </>
    );
  }

  // Standard primitive gates: ported curve geometry from old HTML
  const bx = ML;
  const bw = w - ML - MR;
  const by = 8;
  const bh = h - 16;
  const cy = h / 2;

  /* ── Canonical IEEE Std 91-1984 distinctive shapes ──────────────────────
   * AND/NAND: flat back, true semicircle right (D-shape).
   * OR family: concave back arc + curved top/bottom that bulge outward to
   *            a pointed tip on the right.
   * XOR/XNOR: OR shape + a second back arc (the "shield").
   * Bubbles for inverting outputs are radius-4 circles flush with the tip.
   */

  if (type === "AND" || type === "NAND") {
    // For NAND we shrink the body to leave room for the bubble inside `bw`.
    const arcInset = type === "NAND" ? 8 : 0;
    const radius   = (bh / 2);
    const flatEnd  = bx + bw - arcInset - radius;   // where the arc starts
    const arcTipX  = flatEnd + radius;              // rightmost point of arc
    const path = `M ${bx} ${by} L ${flatEnd} ${by} A ${radius} ${radius} 0 0 1 ${flatEnd} ${by + bh} L ${bx} ${by + bh} Z`;
    return (
      <>
        <path d={path} fill={fill} stroke={col} strokeWidth={sw} />
        {type === "NAND" && (
          <circle cx={arcTipX + 4} cy={cy} r={3.5} fill={fill} stroke={col} strokeWidth={sw} />
        )}
        <text x={bx + bw * 0.32} y={cy + 3} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace"
          fontSize={type === "NAND" ? 6.5 : 7.5} opacity={0.8} fontWeight={700} pointerEvents="none">
          {type}
        </text>
      </>
    );
  }

  if (type === "OR" || type === "NOR") {
    // OR distinctive shape: cubic-Bezier convex top + convex bottom + concave back.
    const bulge   = bh * 0.18;                 // how far top/bottom bulge out
    const concave = bw * 0.28;                 // how far back arc bulges in
    const tipPullback = type === "NOR" ? 8 : 0;
    const tipX    = bx + bw - tipPullback;
    const path =
      `M ${bx} ${by} ` +
      // Top: bulge upward then down to tip
      `C ${bx + bw * 0.35} ${by - bulge} ${bx + bw * 0.75} ${by + bh * 0.05} ${tipX} ${cy} ` +
      // Bottom: mirror — down then up to back-left
      `C ${bx + bw * 0.75} ${by + bh - bh * 0.05} ${bx + bw * 0.35} ${by + bh + bulge} ${bx} ${by + bh} ` +
      // Concave back
      `Q ${bx + concave} ${cy} ${bx} ${by} Z`;
    return (
      <>
        <path d={path} fill={fill} stroke={col} strokeWidth={sw} />
        {type === "NOR" && <circle cx={tipX + 4} cy={cy} r={3.5} fill={fill} stroke={col} strokeWidth={sw} />}
        <text x={bx + bw * 0.5} y={cy + 3} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace"
          fontSize={type === "NOR" ? 7 : 8} opacity={0.8} fontWeight={700} pointerEvents="none">
          {type}
        </text>
      </>
    );
  }

  if (type === "XOR" || type === "XNOR") {
    // XOR = OR shape shifted right by 5, plus a second back arc on the left.
    const shift   = 5;
    const ox      = bx + shift;
    const ow      = bw - shift;
    const bulge   = bh * 0.18;
    const concave = ow * 0.28;
    const tipPullback = type === "XNOR" ? 8 : 0;
    const tipX    = ox + ow - tipPullback;
    const body =
      `M ${ox} ${by} ` +
      `C ${ox + ow * 0.35} ${by - bulge} ${ox + ow * 0.75} ${by + bh * 0.05} ${tipX} ${cy} ` +
      `C ${ox + ow * 0.75} ${by + bh - bh * 0.05} ${ox + ow * 0.35} ${by + bh + bulge} ${ox} ${by + bh} ` +
      `Q ${ox + concave} ${cy} ${ox} ${by} Z`;
    // Extra back arc — slight left of the body, same concavity
    const backArc = `M ${bx} ${by} Q ${bx + concave} ${cy} ${bx} ${by + bh}`;
    return (
      <>
        <path d={body} fill={fill} stroke={col} strokeWidth={sw} />
        <path d={backArc} fill="none" stroke={col} strokeWidth={sw} />
        {type === "XNOR" && <circle cx={tipX + 4} cy={cy} r={3.5} fill={fill} stroke={col} strokeWidth={sw} />}
        <text x={ox + ow * 0.5} y={cy + 3} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace"
          fontSize={type === "XNOR" ? 6.5 : 7.5} opacity={0.8} fontWeight={700} pointerEvents="none">
          {type}
        </text>
      </>
    );
  }

  if (type === "NOT" || type === "BUF") {
    return (
      <>
        <path d={`M${bx} ${by} L${bx} ${by + bh} L${bx + bw - 8} ${cy} Z`}
          fill={fill} stroke={col} strokeWidth={sw} />
        {type === "NOT" && <circle cx={bx + bw - 2} cy={cy} r={5}
          fill="none" stroke={col} strokeWidth={sw} />}
        <text x={bx + bw * 0.35} y={cy + 3} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace"
          fontSize={7} opacity={0.8} fontWeight={700} pointerEvents="none">
          {type}
        </text>
      </>
    );
  }

  // Fallback
  return <rect x={0} y={0} width={w} height={h} rx={6}
    fill={fill} stroke={col} strokeWidth={sw} />;
}

/* ── Pin connector stubs and pin-name labels ──────────────────────────────── */

function PinLines({ type, w, h }: { type: GateType; w: number; h: number }) {
  const col = strokeOf(type);
  const ni = inputPinCount(type);
  const no = outputPinCount(type);
  const lines: React.ReactNode[] = [];

  // Where the gate body (or its bubble/tip) ends on the X axis. The output
  // stub draws from bodyR to w. Lining bodyR up with the actual rightmost
  // pixel of each shape eliminates the gap/overlap that made gates look messy.
  let bodyL = ML, bodyR = w - MR;
  if (type === "INPUT" || type === "OUTPUT" || type === "CLOCK" ||
      type === "VCC"   || type === "GND"    || type === "LED") {
    bodyL = 0; bodyR = w;
  } else if (isMacro(type)) {
    bodyL = 6; bodyR = w - 6;
  } else if (type === "NAND" || type === "NOR" || type === "XNOR") {
    // Bubble right-edge ≈ tip + 4 + 3.5 = tip + 7.5; clamp to w-MR+4.
    bodyR = w - MR + 4;
  } else if (type === "NOT") {
    // NOT triangle tip + bubble (r=5, cx=tip+2) → right edge ≈ tip+7.
    bodyR = w - MR + 4;
  }
  // AND, OR, XOR, BUF — body tip lands at w-MR; default bodyR is correct.

  // Inputs
  for (let i = 0; i < ni; i++) {
    const py = ni === 1 ? h / 2 : (h / (ni + 1)) * (i + 1);
    lines.push(<line key={`il${i}`} x1={0} y1={py} x2={bodyL} y2={py}
      stroke={col} strokeWidth={1.5} opacity={0.55} />);
  }
  // Outputs
  for (let i = 0; i < no; i++) {
    const py = no === 1 ? h / 2 : (h / (no + 1)) * (i + 1);
    lines.push(<line key={`ol${i}`} x1={bodyR} y1={py} x2={w} y2={py}
      stroke={col} strokeWidth={1.5} opacity={0.55} />);
  }
  return <>{lines}</>;
}

function PinLabels({ type, w, h }: { type: GateType; w: number; h: number }) {
  // Pin labels are shown only on macros (HA's A/B/S/C, JKFF's J/K/CLK/Q/Q̅, …)
  // because their pin assignments are non-obvious. Primitive gates inherit
  // the old HTML's clean look — no inline pin labels — so the curves read
  // exactly like the original.
  if (!isMacro(type)) return null;
  const { ins, outs } = defaultPinLabels(type);
  const labels: React.ReactNode[] = [];

  ins.forEach((lbl, i) => {
    const py = ins.length === 1 ? h / 2 : (h / (ins.length + 1)) * (i + 1);
    labels.push(
      <text key={`il${i}`} x={10} y={py + 2.5}
        fontSize={7.5} fontFamily="JetBrains Mono, monospace"
        fontWeight={600} fill="#7a8aa8" pointerEvents="none">
        {lbl}
      </text>
    );
  });

  outs.forEach((lbl, i) => {
    const py = outs.length === 1 ? h / 2 : (h / (outs.length + 1)) * (i + 1);
    labels.push(
      <text key={`ol${i}`} x={w - 10} y={py + 2.5}
        fontSize={7.5} fontFamily="JetBrains Mono, monospace"
        fontWeight={600} fill="#7a8aa8" textAnchor="end" pointerEvents="none">
        {lbl}
      </text>
    );
  });

  return <>{labels}</>;
}

/* ── I/O block detail overlays — toggle switch / bulb / clock / lamp ──────── */

function IODetails({
  type, w, h, value, label, col, isHigh, isLow,
}: {
  type: GateType; w: number; h: number; value: 0 | 1 | null | undefined;
  label?: string; col: string; isHigh: boolean; isLow: boolean;
}) {
  const cx = w / 2;
  const known = value !== undefined && value !== null;
  const onCol  = "#3ddc97";
  const offCol = "#ff5577";
  const unkCol = "#4a5a7a";
  const fc = isHigh ? onCol : isLow ? offCol : unkCol;

  // INPUT — toggle switch (ball moves to right when HIGH)
  if (type === "INPUT") {
    return (
      <>
        <text x={cx} y={13} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace"
          fontSize={7} fontWeight={700} letterSpacing={1} pointerEvents="none">
          {label || "INPUT"}
        </text>
        {/* Switch track */}
        <rect x={cx - 12} y={20} width={24} height={10} rx={5}
          fill="#0d0d18" stroke={fc} strokeWidth={1.2} />
        {/* Switch ball */}
        <circle cx={isHigh ? cx + 6 : cx - 6} cy={25} r={4} fill={fc} />
        <text x={cx} y={h - 4} textAnchor="middle"
          fill={fc} fontFamily="JetBrains Mono, monospace"
          fontSize={9} fontWeight={700} pointerEvents="none">
          {known ? value : "—"}
        </text>
      </>
    );
  }

  // OUTPUT — rounded rect already drawn; add label + bulb + HIGH/LOW
  if (type === "OUTPUT") {
    return (
      <>
        <text x={cx} y={13} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace"
          fontSize={7} fontWeight={700} letterSpacing={1} pointerEvents="none">
          {label || "OUTPUT"}
        </text>
        <circle cx={cx} cy={h / 2 + 2} r={6}
          fill={isHigh ? onCol : "#0d0d1a"} stroke={fc} strokeWidth={1.2} />
        <text x={cx} y={h - 4} textAnchor="middle"
          fill={fc} fontFamily="JetBrains Mono, monospace"
          fontSize={7} fontWeight={700} pointerEvents="none">
          {known ? (isHigh ? "HIGH" : "LOW") : "—"}
        </text>
      </>
    );
  }

  // CLOCK — square-wave polyline
  if (type === "CLOCK") {
    const points = `12,28 12,18 20,18 20,28 28,28 28,18 36,18 36,28 44,28 44,18 52,18 52,28 60,28 60,18`;
    return (
      <>
        <text x={cx} y={13} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace"
          fontSize={7} fontWeight={700} letterSpacing={1} pointerEvents="none">
          {label || "CLOCK"}
        </text>
        <polyline points={points} fill="none"
          stroke={isHigh ? col : col + "70"} strokeWidth={1.5} strokeLinecap="square" />
        <text x={cx} y={h - 4} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace"
          fontSize={7} pointerEvents="none">
          1Hz
        </text>
      </>
    );
  }

  // VCC — "VCC" + T symbol + "1"
  if (type === "VCC") {
    return (
      <>
        <text x={cx} y={14} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace"
          fontSize={9} fontWeight={700} pointerEvents="none">VCC</text>
        <text x={cx} y={h - 2} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace"
          fontSize={9} fontWeight={700} pointerEvents="none">1</text>
      </>
    );
  }

  // GND — "GND" + rake + "0"
  if (type === "GND") {
    return (
      <>
        <text x={cx} y={14} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace"
          fontSize={9} fontWeight={700} pointerEvents="none">GND</text>
        <text x={cx} y={h - 1} textAnchor="middle"
          fill={col} fontFamily="JetBrains Mono, monospace"
          fontSize={9} fontWeight={700} pointerEvents="none">0</text>
      </>
    );
  }

  // LED — lamp with glow when lit
  if (type === "LED") {
    return (
      <>
        <text x={cx} y={12} textAnchor="middle"
          fill={fc} fontFamily="JetBrains Mono, monospace"
          fontSize={7} fontWeight={700} letterSpacing={1} pointerEvents="none">
          {label || "LED"}
        </text>
        {isHigh && <circle cx={cx} cy={h / 2 + 2} r={14} fill={`${onCol}30`} />}
        <circle cx={cx} cy={h / 2 + 2} r={9}
          fill={isHigh ? onCol : "#0d0d1a"} stroke={fc} strokeWidth={1.2} />
        {/* Two parallel leads */}
        <line x1={cx - 2} y1={h / 2 - 4} x2={cx - 2} y2={h / 2 + 8}
          stroke={fc} strokeWidth={1.2} />
        <line x1={cx + 2} y1={h / 2 - 4} x2={cx + 2} y2={h / 2 + 8}
          stroke={fc} strokeWidth={1.2} />
        <text x={cx} y={h - 3} textAnchor="middle"
          fill={fc} fontFamily="JetBrains Mono, monospace"
          fontSize={7} fontWeight={700} pointerEvents="none">
          {known ? (isHigh ? "ON" : "OFF") : "—"}
        </text>
      </>
    );
  }

  return null;
}

/* ── Main exported gate ───────────────────────────────────────────────────── */

interface Props {
  type: GateType;
  label?: string;
  x: number;
  y: number;
  value?: 0 | 1 | null;
  simOutput?: 0 | 1 | null;
  selected?: boolean;
  hovered?: boolean;
}

export function GateShape({ type, label, x, y, value, simOutput, selected, hovered }: Props) {
  const { w, h } = gateDims(type);
  const col = strokeOf(type);

  const displayVal: 0 | 1 | null | undefined =
    type === "INPUT" || type === "CLOCK" ? value
    : type === "VCC" ? 1
    : type === "GND" ? 0
    : simOutput;
  const isHigh = displayVal === 1;
  const isLow  = displayVal === 0;

  return (
    <g transform={`translate(${x},${y})`} className="gate-group">
      {/* Selection highlight */}
      {selected && (
        <rect x={-5} y={-5} width={w + 10} height={h + 10} rx={8}
          fill="none" stroke="#7c5cff" strokeWidth={2}
          strokeDasharray="4 2" opacity={0.85} />
      )}
      {/* Hover glow */}
      {hovered && !selected && (
        <rect x={-3} y={-3} width={w + 6} height={h + 6} rx={7}
          fill="none" stroke={col} strokeWidth={1.5} opacity={0.5} />
      )}

      {/* Soft HIGH glow */}
      {isHigh && (
        <rect x={0} y={0} width={w} height={h} rx={5}
          fill="#3ddc9716" stroke="none" />
      )}

      <PinLines  type={type} w={w} h={h} />
      <GateBody  type={type} w={w} h={h} />
      <PinLabels type={type} w={w} h={h} />

      {/* Detail overlays for I/O blocks — ported from old templates/index.html */}
      <IODetails type={type} w={w} h={h} value={displayVal} label={label} col={col}
        isHigh={isHigh} isLow={isLow} />

      {/* Generic user label (placed above body) for primitive/macro gates only */}
      {label && !(type === "INPUT" || type === "OUTPUT" || type === "CLOCK" ||
                  type === "VCC"   || type === "GND"    || type === "LED") && (
        <text x={w / 2} y={-3} textAnchor="middle"
          fontSize={9} fontFamily="JetBrains Mono, monospace"
          fontWeight={600} fill="#6a7a9a" pointerEvents="none">
          {label}
        </text>
      )}

      {/* Signal value badge (HIGH/LOW) — only on primitive gates; I/O blocks
          draw their own value labels inside IODetails. */}
      {displayVal !== undefined && displayVal !== null &&
       !(type === "INPUT" || type === "OUTPUT" || type === "CLOCK" ||
         type === "VCC"   || type === "GND"    || type === "LED") && (
        <>
          <rect x={w - 16} y={h - 14} width={13} height={11} rx={2}
            fill={isHigh ? "#0d2e1e" : "#2e0d0d"}
            stroke={isHigh ? "#3ddc97" : "#ff5577"}
            strokeWidth={0.8} />
          <text x={w - 9.5} y={h - 6} textAnchor="middle"
            fontSize={8} fontFamily="JetBrains Mono, monospace"
            fontWeight={700} fill={isHigh ? "#3ddc97" : "#ff5577"}
            pointerEvents="none">
            {displayVal}
          </text>
        </>
      )}
    </g>
  );
}

export default GateShape;
