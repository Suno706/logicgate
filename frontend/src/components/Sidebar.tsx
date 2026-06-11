import { useState } from "react";
import { Loader2, Square, Zap } from "lucide-react";
import type { GateType, MacroGate } from "../types";
import { buildQuestion } from "../api";
import { useCircuitDispatch } from "../store";
import { useToast } from "./Toast";

const GATE_GROUPS: { label: string; gates: { type: GateType; desc: string }[] }[] = [
  {
    label: "I/O",
    gates: [
      { type: "INPUT",  desc: "Signal input" },
      { type: "OUTPUT", desc: "Signal output" },
      { type: "CLOCK",  desc: "Clock source" },
      { type: "LED",    desc: "Indicator" },
      { type: "VCC",    desc: "Logic HIGH" },
      { type: "GND",    desc: "Logic LOW" },
    ],
  },
  {
    label: "Basic",
    gates: [
      { type: "AND",  desc: "All inputs high" },
      { type: "OR",   desc: "Any input high" },
      { type: "NOT",  desc: "Invert input" },
      { type: "BUF",  desc: "Buffer / driver" },
    ],
  },
  {
    label: "Universal",
    gates: [
      { type: "NAND", desc: "NOT AND (universal)" },
      { type: "NOR",  desc: "NOT OR  (universal)" },
    ],
  },
  {
    label: "Exclusive",
    gates: [
      { type: "XOR",  desc: "Exactly one high" },
      { type: "XNOR", desc: "Both same value" },
    ],
  },
];

interface MacroEntry {
  type:  MacroGate;
  name:  string;
  desc:  string;
  query: string;   // for "Expand to gates" mode
}

const MACROS: { label: string; items: MacroEntry[] }[] = [
  {
    label: "Arithmetic",
    items: [
      { type: "HA",   name: "Half Adder",  desc: "A,B → S,C",     query: "half adder" },
      { type: "FA",   name: "Full Adder",  desc: "A,B,Ci → S,Co", query: "full adder" },
      { type: "CMP2", name: "Comparator",  desc: "2-bit A == B",  query: "2 bit equality comparator" },
    ],
  },
  {
    label: "Mux / Decoder / Encoder",
    items: [
      { type: "MUX2",  name: "2:1 MUX",     desc: "A,B,S → Y",          query: "2 to 1 mux" },
      { type: "MUX4",  name: "4:1 MUX",     desc: "D0..D3,S0,S1 → Y",    query: "4 to 1 mux" },
      { type: "DEC24", name: "2:4 Decoder", desc: "A,B → Y0..Y3",        query: "2 to 4 decoder" },
      { type: "DEC38", name: "3:8 Decoder", desc: "A,B,C → Y0..Y7",      query: "3 to 8 decoder" },
      { type: "ENC42", name: "4:2 Encoder", desc: "Priority I0..I3 → Y", query: "4 to 2 priority encoder" },
    ],
  },
  {
    label: "Sequential",
    items: [
      { type: "DFF",     name: "D Flip-Flop",  desc: "D,CLK → Q,Q̅",   query: "D flip flop" },
      { type: "JKFF",    name: "JK Flip-Flop", desc: "J,K,CLK → Q,Q̅", query: "JK flip flop" },
      { type: "TFF",     name: "T Flip-Flop",  desc: "T,CLK → Q,Q̅",   query: "T flip flop" },
      { type: "SRLATCH", name: "SR Latch",     desc: "S,R → Q,Q̅",     query: "SR latch using NOR" },
      { type: "REG4",    name: "4-bit Register", desc: "D0..D3,CLK → Q0..Q3", query: "4 bit register" },
    ],
  },
];

const SYNTHESIS_ONLY: { name: string; query: string; desc: string }[] = [
  // ── Arithmetic ──
  { name: "2-bit Adder",        query: "2 bit adder",                desc: "A1A0 + B1B0" },
  { name: "4-bit Adder",        query: "4 bit ripple carry adder",   desc: "Ripple carry" },
  { name: "8-bit Adder",        query: "8 bit adder",                desc: "Wide ripple" },
  { name: "Half Subtractor",    query: "half subtractor",            desc: "A - B" },
  { name: "Full Subtractor",    query: "full subtractor",            desc: "A - B - Bin" },
  { name: "4-bit Subtractor",   query: "4 bit subtractor",           desc: "2's complement" },
  { name: "2-bit Comparator",   query: "2 bit comparator",           desc: "<, =, >" },
  { name: "4-bit Comparator",   query: "4 bit comparator",           desc: "Wide compare" },
  { name: "2-bit Multiplier",   query: "2 bit multiplier",           desc: "A × B → 4 bits" },
  // ── Mux / Demux / Decoder / Encoder ──
  { name: "8:1 MUX",            query: "8 to 1 mux",                 desc: "3-select MUX" },
  { name: "1:4 DEMUX",          query: "1 to 4 demux",               desc: "Single in" },
  { name: "1:8 DEMUX",          query: "1 to 8 demux",               desc: "3-select demux" },
  { name: "BCD → 7-seg",        query: "bcd to 7 segment decoder",   desc: "Display driver" },
  { name: "8:3 Encoder",        query: "8 to 3 priority encoder",    desc: "Priority encoder" },
  { name: "Priority encoder",   query: "priority encoder valid",     desc: "With valid bit" },
  { name: "Parity",             query: "parity",                     desc: "Even parity" },
  { name: "Majority gate",      query: "majority gate",              desc: "3-input majority" },
  // ── Latches & flip-flops alternates ──
  { name: "SR Latch (NAND)",    query: "sr latch nand",              desc: "Active-low S,R" },
  { name: "Gated D Latch",      query: "gated d latch",              desc: "Level-sensitive" },
  { name: "Master-slave FF",    query: "master slave flip flop",     desc: "Edge-triggered D" },
  // ── Registers / counters ──
  { name: "4-bit Shift Reg",    query: "4 bit shift register",       desc: "Parallel-out" },
  { name: "4-bit Counter",      query: "4 bit counter",              desc: "Mod-16 ripple" },
  // ── Composed from macro blocks (sub-circuits stay visible) ──
  { name: "FA using HA",        query: "full adder using half adder", desc: "2 HA + OR" },
  { name: "4-bit Adder (FA)",   query: "4 bit adder using full adder", desc: "4× FA chained" },
  { name: "8-bit Adder (FA)",   query: "8 bit adder using full adder", desc: "8× FA chained" },
  { name: "4-bit Sub (FA)",     query: "4 bit subtractor using full adder", desc: "FA + 2's comp" },
  { name: "4-bit Reg (DFF)",    query: "4 bit register using d flip flop", desc: "4× DFF parallel" },
  { name: "8-bit Reg (DFF)",    query: "8 bit register using d flip flop", desc: "8× DFF parallel" },
  { name: "Shift Reg (DFF)",    query: "4 bit shift register using d flip flop", desc: "Serial-in/parallel-out" },
  { name: "Counter (TFF)",      query: "4 bit counter using t flip flop", desc: "4× TFF ripple" },
  { name: "Ring Counter",       query: "4 bit ring counter",          desc: "4× DFF in ring" },
  { name: "4:1 MUX (MUX2)",     query: "4 to 1 mux using 2 to 1 mux", desc: "3× MUX2 tree" },
];

const COLORS: Record<string, string> = {
  INPUT:  "#7c5cff", OUTPUT: "#3ddc97", CLOCK:  "#ffb454",
  LED:    "#ff5577", VCC:    "#3ddc97", GND:    "#9aa6bf",
  AND:    "#4a8fff", OR:     "#4abb4a", NOT:    "#ff8844",
  BUF:    "#44ffaa", NAND:   "#ff6b6b", NOR:    "#ffaa44",
  XOR:    "#bb77ff", XNOR:   "#44aaff",
};

interface Props {
  selected: GateType | null;
  onSelect: (type: GateType) => void;
}

export function Sidebar({ selected, onSelect }: Props) {
  const dispatch = useCircuitDispatch();
  const toast    = useToast();
  const [loading, setLoading] = useState<string | null>(null);

  async function expand(name: string, query: string) {
    if (loading) return;
    setLoading(query);
    try {
      const r = await buildQuestion(query);
      if (r.circuit && r.circuit.gates.length > 0) {
        dispatch({ type: "SET_CIRCUIT", circuit: r.circuit });
        toast.success(`Built ${name} — ${r.circuit.gates.length} gates`);
      } else {
        toast.error(r.answer || `Could not build "${name}"`);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Backend offline");
    } finally {
      setLoading(null);
    }
  }

  return (
    <aside className="w-[200px] flex-shrink-0 bg-bg-800 border-r border-bg-600 flex flex-col overflow-y-auto">

      {/* ─── Primitive gates ─── */}
      <div className="px-3 py-2 border-b border-bg-600 flex-shrink-0">
        <span className="text-[9px] font-mono uppercase tracking-widest text-gray-600">Gates</span>
      </div>
      {GATE_GROUPS.map((group) => (
        <div key={group.label}>
          <div className="px-3 pt-3 pb-1 text-[8px] font-mono uppercase tracking-widest text-gray-600">
            {group.label}
          </div>
          <div className="px-2 pb-1 space-y-0.5">
            {group.gates.map(({ type, desc }) => {
              const isActive = selected === type;
              const col = COLORS[type] ?? "#7c5cff";
              return (
                <button
                  key={type}
                  title={desc}
                  onClick={() => onSelect(type)}
                  className={`w-full flex items-center gap-2.5 px-2.5 py-2.5 md:py-1.5 rounded text-left transition-all min-h-[44px] md:min-h-0 ${
                    isActive ? "bg-bg-600 border border-current" : "hover:bg-bg-700 border border-transparent"
                  }`}
                  style={{ color: isActive ? col : "#6a7a9a" }}
                >
                  <GateIcon type={type} color={col} />
                  <div className="min-w-0">
                    <div className="text-[12px] md:text-[10px] font-mono font-bold leading-tight">{type}</div>
                    <div className="text-[10px] md:text-[8px] text-gray-600 leading-tight truncate">{desc}</div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      ))}

      {/* ─── Macro components: Place / Expand toggle ─── */}
      <div className="px-3 pt-4 pb-2 mt-2 border-t border-bg-600 flex items-center gap-1.5 flex-shrink-0">
        <Square size={10} className="text-accent" />
        <span className="text-[9px] font-mono uppercase tracking-widest text-gray-500">Components</span>
      </div>

      {MACROS.map((group) => (
        <div key={group.label}>
          <div className="px-3 pt-2 pb-1 text-[8px] font-mono uppercase tracking-widest text-gray-600">
            {group.label}
          </div>
          <div className="px-2 pb-1 space-y-1">
            {group.items.map((m) => {
              const isLoading = loading === m.query;
              const isSel     = selected === m.type;
              return (
                <div key={m.type}
                  className={`rounded border transition-all ${
                    isSel
                      ? "bg-bg-600 border-accent"
                      : "bg-bg-700/50 border-bg-600 hover:border-gray-500"
                  }`}>
                  <div className="px-2 pt-1.5 pb-0.5">
                    <div className="text-[10px] font-mono font-bold leading-tight text-gray-200">{m.name}</div>
                    <div className="text-[8px] text-gray-600 leading-tight truncate">{m.desc}</div>
                  </div>
                  <div className="flex gap-px px-1 pb-1">
                    <button
                      title={`Place ${m.name} as a single block`}
                      onClick={() => { onSelect(m.type); }}
                      className={`flex-1 flex items-center justify-center gap-1 py-1 rounded-l text-[8px] font-mono font-bold transition-colors ${
                        isSel
                          ? "bg-accent/20 text-accent"
                          : "bg-bg-800 text-gray-500 hover:bg-bg-700 hover:text-gray-300"
                      }`}>
                      <Square size={8} />
                      Place
                    </button>
                    <button
                      title={`Replace canvas with ${m.name} synthesized from primitives`}
                      disabled={!!loading}
                      onClick={() => expand(m.name, m.query)}
                      className="flex-1 flex items-center justify-center gap-1 py-1 rounded-r text-[8px] font-mono font-bold bg-bg-800 text-gray-500 hover:bg-bg-700 hover:text-gray-300 disabled:opacity-40 transition-colors">
                      {isLoading ? <Loader2 size={8} className="animate-spin" /> : <Zap size={8} />}
                      Expand
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {/* ─── Synthesis-only templates (MUX, decoder, BCD) ─── */}
      <div className="px-3 pt-4 pb-1 text-[8px] font-mono uppercase tracking-widest text-gray-600">
        Build from scratch
      </div>
      <div className="px-2 pb-2 space-y-0.5">
        {SYNTHESIS_ONLY.map((s) => {
          const isLoading = loading === s.query;
          return (
            <button
              key={s.name}
              title={`Build ${s.name}: ${s.desc}`}
              disabled={!!loading}
              onClick={() => expand(s.name, s.query)}
              className="w-full flex items-center gap-2.5 px-2.5 py-2.5 md:py-1.5 rounded text-left hover:bg-bg-700 border border-transparent hover:border-accent/30 transition-all disabled:opacity-40 disabled:cursor-wait group min-h-[44px] md:min-h-0">
              <div className="w-6 h-6 md:w-5 md:h-5 rounded bg-bg-700 border border-bg-600 group-hover:border-accent/40 flex items-center justify-center flex-shrink-0">
                {isLoading
                  ? <Loader2 size={11} className="animate-spin text-accent" />
                  : <Zap size={11} className="text-gray-600 group-hover:text-accent transition-colors" />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-[12px] md:text-[10px] font-mono font-bold leading-tight text-gray-300 group-hover:text-gray-100">{s.name}</div>
                <div className="text-[10px] md:text-[8px] text-gray-600 leading-tight truncate">{s.desc}</div>
              </div>
            </button>
          );
        })}
      </div>

      <div className="flex-1" />
      <div className="p-3 border-t border-bg-600 text-[8px] text-gray-600 font-mono leading-relaxed flex-shrink-0">
        <span className="text-accent">Place</span> drops a single labeled box.<br />
        <span className="text-accent">Expand</span> rebuilds it from primitives.<br />
        Drag output pin → input pin to wire.<br />
        Double-click INPUT to toggle.
      </div>
    </aside>
  );
}

function GateIcon({ type, color }: { type: GateType; color: string }) {
  const w = 28, h = 18;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="flex-shrink-0">
      <GateIconShape type={type} w={w} h={h} color={color} />
    </svg>
  );
}

function GateIconShape({ type, w, h, color }: { type: GateType; w: number; h: number; color: string }) {
  const sw = 1.2;
  const fill = `${color}20`;

  if (type === "INPUT" || type === "OUTPUT" || type === "CLOCK" ||
      type === "VCC"   || type === "GND"    || type === "LED") {
    return <rect x={1} y={2} width={w - 2} height={h - 4} rx={(h - 4) / 2}
      fill={fill} stroke={color} strokeWidth={sw} />;
  }
  if (type === "NOT" || type === "BUF") {
    const tip = w - 5;
    return <>
      <path d={`M 2,2 L 2,${h - 2} L ${tip},${h / 2} Z`} fill={fill} stroke={color} strokeWidth={sw} />
      {type === "NOT" && <circle cx={tip + 3} cy={h / 2} r={2.5} fill={fill} stroke={color} strokeWidth={sw} />}
    </>;
  }
  if (type === "AND" || type === "NAND") {
    const r = (h - 4) / 2;
    const cx = 6 + r;
    return <>
      <path d={`M 2,2 L ${cx},2 A ${r},${r} 0 0 1 ${cx},${h - 2} L 2,${h - 2} Z`} fill={fill} stroke={color} strokeWidth={sw} />
      {type === "NAND" && <circle cx={cx + r + 3} cy={h / 2} r={2.5} fill={fill} stroke={color} strokeWidth={sw} />}
    </>;
  }
  const tip = w - 5;
  const path = `M 3,2 Q ${tip * 0.5},2 ${tip},${h / 2} Q ${tip * 0.5},${h - 2} 3,${h - 2} Q 10,${h / 2} 3,2 Z`;
  const xline = `M 0,2 Q 7,${h / 2} 0,${h - 2}`;
  return <>
    <path d={path} fill={fill} stroke={color} strokeWidth={sw} />
    {(type === "XOR" || type === "XNOR") && <path d={xline} fill="none" stroke={color} strokeWidth={sw} />}
    {(type === "NOR" || type === "XNOR") && <circle cx={tip + 3} cy={h / 2} r={2.5} fill={fill} stroke={color} strokeWidth={sw} />}
  </>;
}
