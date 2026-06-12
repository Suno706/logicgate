import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, RotateCcw, ChevronRight, Dice5 } from "lucide-react";
import { evalChain, BINARY_GATES, GATE_GLYPH, type GateOp } from "./logic";

/** Signal Maze — procedural puzzle game.
 *
 *  Every level is freshly generated, not pulled from a hand-built list.
 *  The puzzle gives the player a source bit, a chain of gate slots each
 *  fed by a "tap" bit (A, B, C…), a goal bit for the output LED, and a
 *  palette of allowed gates. The player picks one gate per slot until the
 *  chain evaluates to the goal. Difficulty (chain length, palette size,
 *  number of distinct taps) scales with the level counter. */

interface Puzzle {
  source: 0 | 1;
  taps: (0 | 1)[];
  tapLabels: string[];
  palette: GateOp[];
  goal: 0 | 1;
}

function pickN<T>(arr: T[], n: number): T[] {
  const copy = [...arr];
  const out: T[] = [];
  while (out.length < n && copy.length) {
    out.push(copy.splice(Math.floor(Math.random() * copy.length), 1)[0]);
  }
  return out;
}

function randomPuzzle(level: number): Puzzle {
  // Length: 1 slot at level 0, growing toward 4 by ~level 6.
  const len = Math.min(4, 1 + Math.floor(level / 2) + (Math.random() < 0.5 ? 0 : 1));
  const paletteSize = Math.min(BINARY_GATES.length, 3 + Math.floor(level / 3));
  const palette = pickN(BINARY_GATES, paletteSize);
  const taps: (0 | 1)[] = Array.from({ length: len }, () => (Math.random() < 0.5 ? 0 : 1));
  const tapLabels = Array.from({ length: len }, (_, i) => "ABCD"[i]);
  const source: 0 | 1 = Math.random() < 0.5 ? 0 : 1;

  // Confirm the puzzle is solvable with the given palette by brute force.
  // If not (rare), regenerate with a wider palette.
  for (let attempt = 0; attempt < 4; attempt++) {
    const goal: 0 | 1 = Math.random() < 0.5 ? 0 : 1;
    if (isSolvable({ source, taps, tapLabels, palette, goal })) {
      return { source, taps, tapLabels, palette, goal };
    }
    // Try the other goal before regenerating
    const otherGoal: 0 | 1 = goal === 1 ? 0 : 1;
    if (isSolvable({ source, taps, tapLabels, palette, goal: otherGoal })) {
      return { source, taps, tapLabels, palette, goal: otherGoal };
    }
  }
  // Final fallback: include every binary gate so at least one solution exists.
  return { source, taps, tapLabels, palette: [...BINARY_GATES], goal: 1 };
}

/** Brute-force solvability check: ≤ 6^4 = 1296 combinations, instant. */
function isSolvable(p: Puzzle): boolean {
  const n = p.taps.length;
  const total = Math.pow(p.palette.length, n);
  for (let i = 0; i < total; i++) {
    const ops: GateOp[] = [];
    let x = i;
    for (let k = 0; k < n; k++) {
      ops.push(p.palette[x % p.palette.length]);
      x = Math.floor(x / p.palette.length);
    }
    if (evalChain(ops, p.source, p.taps) === p.goal) return true;
  }
  return false;
}

const BEST_KEY = "logicgate.maze.best";

export function SignalMaze() {
  const [level, setLevel] = useState(1);
  const [puzzle, setPuzzle] = useState<Puzzle>(() => randomPuzzle(1));
  const [picks, setPicks] = useState<(GateOp | null)[]>([]);
  const [best, setBest] = useState<number>(() => {
    try { return Number(localStorage.getItem(BEST_KEY) || "0") || 0; }
    catch { return 0; }
  });

  useEffect(() => {
    setPicks(Array(puzzle.taps.length).fill(null));
  }, [puzzle]);

  const filled = picks.every((p): p is GateOp => p !== null);
  const output: 0 | 1 | null = filled
    ? evalChain(picks as GateOp[], puzzle.source, puzzle.taps)
    : null;
  const won = filled && output === puzzle.goal;

  useEffect(() => {
    if (!won) return;
    if (level > best) {
      setBest(level);
      try { localStorage.setItem(BEST_KEY, String(level)); } catch { /* */ }
    }
  }, [won, level, best]);

  // Stage-by-stage output for the visualisation
  const stageValues = useMemo(() => {
    const vals: (0 | 1 | null)[] = [];
    let v: 0 | 1 = puzzle.source;
    for (let i = 0; i < puzzle.taps.length; i++) {
      const op = picks[i];
      if (op == null) { vals.push(null); break; }
      v = evalChain([op], v, [puzzle.taps[i]]);
      vals.push(v);
    }
    return vals;
  }, [picks, puzzle]);

  function setPickAt(i: number, op: GateOp) {
    setPicks((cur) => cur.map((v, k) => k === i ? op : v));
  }
  function reset() { setPicks(Array(puzzle.taps.length).fill(null)); }
  function nextLevel() {
    const nl = level + 1;
    setLevel(nl);
    setPuzzle(randomPuzzle(nl));
  }
  function reroll() { setPuzzle(randomPuzzle(level)); }

  return (
    <div className="p-5 md:p-8">

      {/* Level header */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <span className="px-2.5 py-1 rounded-md bg-accent/15 border border-accent/40 text-[12px] text-accent font-semibold tabular-nums">
            Level {level}
          </span>
          <span className="text-[12px] text-gray-500">
            Best <span className="text-gray-300 font-semibold tabular-nums">{best}</span>
          </span>
        </div>
        <button onClick={reroll}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-medium text-gray-400 bg-bg-700 border border-bg-600 hover:border-accent/50 hover:text-gray-100 transition-colors"
          title="Generate a different puzzle at this level">
          <Dice5 size={13} /> Reroll
        </button>
      </div>

      <p className="text-[13px] text-gray-400 mb-6 max-w-2xl leading-relaxed">
        Pick a gate for each slot so the chain produces the goal output. Every
        level is freshly generated — no two runs are the same.
      </p>

      {/* Circuit visualisation */}
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
                output={stageValues[i] ?? null}
              />
            </div>
          ))}
          <Wire active={stageValues[stageValues.length - 1] === 1} />
          <Bulb value={output} label="LED" big highlight={won} />
        </div>

        <div className="mt-2 text-center text-[11px] text-gray-500">
          Goal: LED = <span className={puzzle.goal === 1 ? "text-ok font-semibold" : "text-err font-semibold"}>{puzzle.goal}</span>
        </div>

        {/* Gate palette per slot */}
        <div className="mt-5 grid gap-3" style={{ gridTemplateColumns: `repeat(${puzzle.taps.length}, minmax(0, 1fr))` }}>
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
