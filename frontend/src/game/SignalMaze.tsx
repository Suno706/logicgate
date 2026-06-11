import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, RotateCcw, ChevronRight } from "lucide-react";
import { evalChain, BINARY_GATES, GATE_GLYPH, type GateOp } from "./logic";

/** Signal Maze — a hand-designed puzzle game.
 *
 *  Each puzzle is a linear chain of gate slots. The source bit feeds into
 *  the first gate; each subsequent gate takes the previous output plus a
 *  fixed "tap" bit pulled from a labelled input row. The player picks the
 *  gate type for each slot (from a small palette of allowed gates) such
 *  that the final output equals the goal bit — and the output LED lights up.
 *
 *  Levels gradually increase chain length and limit the palette. */

interface Puzzle {
  title:   string;
  hint:    string;
  source:  0 | 1;            // initial value into stage 0
  taps:    (0 | 1)[];        // length === slots; other input for each stage
  tapLabels: string[];       // human-readable name for each tap (A, B, …)
  palette: GateOp[];         // gates the player may pick from
  goal:    0 | 1;            // value the LED should land on
}

const PUZZLES: Puzzle[] = [
  {
    title: "Warm-up — flip a bit",
    hint:  "Source is HIGH. Pick a gate that lets HIGH through (or flips it as needed).",
    source: 1, taps: [0], tapLabels: ["—"],
    palette: ["AND", "OR", "XOR"],
    goal: 1,
  },
  {
    title: "Two-stage chain",
    hint:  "Get the LED to HIGH. Source = LOW. Tap A = HIGH, Tap B = HIGH.",
    source: 0, taps: [1, 1], tapLabels: ["A", "B"],
    palette: ["AND", "OR", "XOR", "NAND"],
    goal: 1,
  },
  {
    title: "Mixed taps",
    hint:  "Source = HIGH, taps alternate. Make LED = LOW.",
    source: 1, taps: [1, 0, 1], tapLabels: ["A", "B", "C"],
    palette: ["AND", "OR", "XOR", "XNOR", "NAND"],
    goal: 0,
  },
  {
    title: "Universal challenge",
    hint:  "Only NAND allowed in slot 1, only NOR in slot 3. Pick the middle gate.",
    source: 1, taps: [0, 1, 0], tapLabels: ["A", "B", "C"],
    palette: ["NAND", "NOR", "XOR"],
    goal: 1,
  },
  {
    title: "Four-deep",
    hint:  "Long chain. Source = LOW, taps = HIGH, LOW, HIGH, LOW. LED must be HIGH.",
    source: 0, taps: [1, 0, 1, 0], tapLabels: ["A", "B", "C", "D"],
    palette: ["AND", "OR", "XOR", "XNOR", "NAND", "NOR"],
    goal: 1,
  },
];

const STORAGE = "logicgate.maze.solved";

export function SignalMaze() {
  const [lvl, setLvl] = useState(0);
  const [picks, setPicks] = useState<(GateOp | null)[]>([]);
  const [solved, setSolved] = useState<number[]>(() => {
    try { return JSON.parse(localStorage.getItem(STORAGE) || "[]"); }
    catch { return []; }
  });

  const puzzle = PUZZLES[lvl];

  useEffect(() => {
    setPicks(Array(puzzle.taps.length).fill(null));
  }, [lvl, puzzle.taps.length]);

  const filled = picks.every((p): p is GateOp => p !== null);
  const output: 0 | 1 | null = filled ? evalChain(picks as GateOp[], puzzle.source, puzzle.taps) : null;
  const won = filled && output === puzzle.goal;

  useEffect(() => {
    if (!won) return;
    setSolved((prev) => {
      if (prev.includes(lvl)) return prev;
      const next = [...prev, lvl];
      try { localStorage.setItem(STORAGE, JSON.stringify(next)); } catch { /* */ }
      return next;
    });
  }, [won, lvl]);

  // Compute per-stage outputs for the visualisation (whatever is filled so far)
  const stageValues = useMemo(() => {
    const vals: (0 | 1 | null)[] = [];
    let v: 0 | 1 = puzzle.source;
    for (let i = 0; i < puzzle.taps.length; i++) {
      const op = picks[i];
      if (op == null) { vals.push(null); v = 0; break; }
      v = evalChain([op], v, [puzzle.taps[i]]);
      vals.push(v);
    }
    return vals;
  }, [picks, puzzle]);

  function setPickAt(i: number, op: GateOp) {
    setPicks((cur) => cur.map((v, k) => k === i ? op : v));
  }

  function reset() { setPicks(Array(puzzle.taps.length).fill(null)); }
  function nextLevel() { setLvl((l) => (l + 1) % PUZZLES.length); }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto p-5 md:p-8">

      {/* Level header */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <span className="px-2 py-1 rounded bg-bg-700 border border-bg-600 text-[11px] text-gray-400 tabular-nums">
            Level {lvl + 1} / {PUZZLES.length}
          </span>
          <h2 className="text-[18px] font-semibold text-gray-100">{puzzle.title}</h2>
        </div>
        <div className="flex items-center gap-1.5">
          {PUZZLES.map((_, i) => (
            <button key={i} onClick={() => setLvl(i)}
              className={`w-7 h-7 rounded-full text-[11px] font-semibold transition-colors ${
                i === lvl
                  ? "bg-accent text-white"
                  : solved.includes(i)
                    ? "bg-ok/15 text-ok border border-ok/40"
                    : "bg-bg-700 text-gray-400 border border-bg-600 hover:border-accent/40"
              }`}>
              {i + 1}
            </button>
          ))}
        </div>
      </div>

      <p className="text-[13px] text-gray-400 mb-6 max-w-2xl leading-relaxed">{puzzle.hint}</p>

      {/* Circuit visualisation: source bulb → [gate slots] → output LED */}
      <div className="rounded-2xl bg-bg-800/70 border border-bg-600 px-4 md:px-8 py-6 mb-6">
        <div className="flex items-center justify-center flex-wrap gap-3 md:gap-4">
          <Bulb value={puzzle.source} label="SRC" />
          {puzzle.taps.map((_, i) => (
            <div key={i} className="flex items-center gap-3 md:gap-4">
              <Wire active={i === 0 ? puzzle.source === 1 : (stageValues[i - 1] === 1)} />
              <GateSlot
                op={picks[i]}
                tapValue={puzzle.taps[i]}
                tapLabel={puzzle.tapLabels[i]}
                output={stageValues[i]}
              />
            </div>
          ))}
          <Wire active={stageValues[stageValues.length - 1] === 1} />
          <Bulb value={output} label="LED" big highlight={won} />
        </div>

        <div className="mt-6 grid gap-3" style={{ gridTemplateColumns: `repeat(${puzzle.taps.length}, minmax(0, 1fr))` }}>
          {puzzle.taps.map((_, slotIdx) => (
            <div key={slotIdx} className="flex flex-col gap-1">
              <div className="text-[11px] text-gray-500 text-center">
                Gate {slotIdx + 1}
                {picks[slotIdx] && <span className="text-accent ml-1">· {picks[slotIdx]}</span>}
              </div>
              <div className="flex flex-wrap justify-center gap-1">
                {puzzle.palette.map((g) => (
                  <button key={g}
                    onClick={() => setPickAt(slotIdx, g)}
                    className={`px-2 py-1 rounded-md text-[11px] font-semibold border transition-colors ${
                      picks[slotIdx] === g
                        ? "bg-accent/15 border-accent text-accent"
                        : "bg-bg-700 border-bg-600 text-gray-300 hover:border-accent/40 hover:text-gray-100"
                    }`}>
                    <span className="mr-0.5 opacity-70">{GATE_GLYPH[g]}</span>{g}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Result + controls */}
      <div className="flex items-center gap-3 flex-wrap">
        {filled && (
          <div className={`flex items-center gap-2 px-3 py-2 rounded-md text-[12px] font-medium ${
            won
              ? "bg-ok/10 border border-ok/40 text-ok"
              : "bg-err/10 border border-err/30 text-err"
          }`}>
            {won ? <CheckCircle2 size={14} /> : null}
            <span>
              LED reads <span className="font-bold">{output}</span> · goal is <span className="font-bold">{puzzle.goal}</span>
              {won && " — solved!"}
            </span>
          </div>
        )}
        <button onClick={reset}
          className="flex items-center gap-1.5 px-3 py-2 rounded-md text-[12px] font-medium text-gray-300 bg-bg-700 border border-bg-600 hover:border-accent/40 transition-colors">
          <RotateCcw size={13} /> Reset
        </button>
        <button onClick={nextLevel} disabled={!won}
          className="flex items-center gap-1.5 px-4 py-2 rounded-md text-[12px] font-semibold text-white bg-accent hover:bg-accent-hover transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
          Next level <ChevronRight size={14} />
        </button>
        <div className="flex-1" />
        <span className="text-[11px] text-gray-500 tabular-nums">
          Solved {solved.length} / {PUZZLES.length}
        </span>
      </div>
    </div>
  );
}

/* ─── Visual primitives ──────────────────────────────────────────────── */

function Bulb({ value, label, big, highlight }: {
  value: 0 | 1 | null; label: string; big?: boolean; highlight?: boolean;
}) {
  const on = value === 1;
  const off = value === 0;
  const size = big ? "w-14 h-14 md:w-16 md:h-16" : "w-10 h-10 md:w-12 md:h-12";
  const baseClr = on
    ? "bg-ok/25 border-ok text-ok shadow-[0_0_18px_rgba(74,222,128,0.5)]"
    : off
      ? "bg-bg-700 border-bg-600 text-gray-500"
      : "bg-bg-700 border-bg-600 text-gray-600";
  return (
    <div className="flex flex-col items-center gap-1">
      <div className={`${size} rounded-full border-2 flex items-center justify-center text-[14px] font-bold transition-all ${baseClr} ${highlight ? "animate-pulse" : ""}`}>
        {value === null ? "?" : value}
      </div>
      <span className="text-[10px] uppercase text-gray-500 tracking-wider">{label}</span>
    </div>
  );
}

function GateSlot({ op, tapValue, tapLabel, output }: {
  op: GateOp | null; tapValue: 0 | 1; tapLabel: string; output: 0 | 1 | null;
}) {
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="flex items-center gap-2">
        <div className="text-[10px] text-gray-500 leading-tight text-right">
          tap<br /><span className={tapValue === 1 ? "text-ok font-bold" : "text-gray-400"}>{tapLabel}={tapValue}</span>
        </div>
        <div className={`w-12 h-12 md:w-14 md:h-14 rounded-xl border-2 flex flex-col items-center justify-center font-mono transition-colors ${
          op
            ? "bg-accent/10 border-accent/60 text-accent"
            : "bg-bg-700 border-dashed border-gray-600 text-gray-600"
        }`}>
          <span className="text-[20px] leading-none">{op ? GATE_GLYPH[op] : "?"}</span>
          {op && <span className="text-[9px] mt-0.5 opacity-80">{op}</span>}
        </div>
      </div>
      <div className="text-[10px] text-gray-500">
        out = <span className={output === 1 ? "text-ok font-bold" : output === 0 ? "text-err" : "text-gray-600"}>
          {output ?? "?"}
        </span>
      </div>
    </div>
  );
}

function Wire({ active }: { active: boolean }) {
  return (
    <div className={`h-0.5 w-6 md:w-8 transition-colors ${active ? "bg-ok shadow-[0_0_6px_rgba(74,222,128,0.6)]" : "bg-bg-600"}`} />
  );
}

// Keep BINARY_GATES import alive for tree-shaker silencing if palette becomes empty
void BINARY_GATES;
