import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, RotateCcw, Dice5, ChevronRight } from "lucide-react";
import { BINARY_GATES, GATE_GLYPH, evalChain, type GateOp } from "./logic";

/** Build the Table — random truth-table matching game.
 *
 *  A target truth table is generated each round. The player picks gate
 *  types for N slots in series; output is compared against the target row
 *  by row. Match every row to win. The target is RANDOM, not predefined.
 *  Difficulty scales with the slot count.
 *
 *  Wiring shape (n inputs, k slots):
 *      Y = ((A op_0 B) op_1 C) op_2 ...   — left-fold
 *  With at most as many slots as (nIn - 1), then optional final operator
 *  on a tap from input A again (so the player still has choices). */

interface Round {
  nIn: 2 | 3;
  target: (0 | 1)[];   // length 2^nIn
  slots: number;       // number of operator slots
  palette: GateOp[];
  goalTable: string;   // pretty hex of target (for re-roll caching)
}

function randomTarget(nIn: 2 | 3): (0 | 1)[] {
  // Avoid trivial all-0 / all-1 tables.
  const rows = 1 << nIn;
  while (true) {
    const bits: (0 | 1)[] = Array.from({ length: rows }, () => (Math.random() < 0.5 ? 0 : 1));
    const sum = bits.reduce<number>((a, b) => a + b, 0);
    if (sum !== 0 && sum !== rows) return bits;
  }
}

function randomRound(level: number): Round {
  const nIn: 2 | 3 = level >= 3 && Math.random() < 0.4 ? 3 : 2;
  const target = randomTarget(nIn);
  const slots = nIn === 2 ? 1 + (Math.random() < 0.5 ? 0 : 1) : 2;
  // Wider palette = easier to find a match.
  const paletteSize = Math.min(BINARY_GATES.length, 4 + Math.floor(level / 2));
  // Shuffle + take a prefix
  const shuffled = [...BINARY_GATES].sort(() => Math.random() - 0.5);
  const palette = shuffled.slice(0, paletteSize);
  return { nIn, target, slots, palette, goalTable: target.join("") };
}

const BEST = "logicgate.buildtable.solved";

export function BuildTable() {
  const [level, setLevel] = useState(1);
  const [round, setRound] = useState<Round>(() => randomRound(1));
  const [picks, setPicks] = useState<(GateOp | null)[]>([]);
  const [solved, setSolved] = useState(0);
  const [best, setBest] = useState<number>(() => {
    try { return Number(localStorage.getItem(BEST) || "0") || 0; }
    catch { return 0; }
  });

  useEffect(() => {
    setPicks(Array(round.slots).fill(null));
  }, [round]);

  // Compute the player's output for every input row.
  // Wiring: Y[row] = (((bit0 op_0 bit1) op_1 bit2) op_2 ...) — left-fold.
  // When slots > nIn-1, taps reuse bit0 cyclically so the player keeps
  // having gate choices.
  const playerColumn: (0 | 1 | null)[] = useMemo(() => {
    const rows = 1 << round.nIn;
    if (!picks.every((p): p is GateOp => p !== null)) {
      return Array.from({ length: rows }, () => null);
    }
    const ops = picks as GateOp[];
    const out: (0 | 1)[] = [];
    for (let i = 0; i < rows; i++) {
      const bits: (0 | 1)[] = Array.from({ length: round.nIn }, (_, k) =>
        ((i >> (round.nIn - 1 - k)) & 1) as 0 | 1
      );
      const taps: (0 | 1)[] = [];
      for (let k = 0; k < round.slots; k++) {
        // Stage k uses bits[k+1] if available, otherwise wraps to bits[0]
        const idx = (k + 1) % round.nIn;
        taps.push(bits[idx]);
      }
      out.push(evalChain(ops, bits[0], taps));
    }
    return out;
  }, [picks, round]);

  const allMatch = playerColumn.every((v, i) => v !== null && v === round.target[i]);

  useEffect(() => {
    if (allMatch && picks.every((p) => p !== null)) {
      // Mark this round solved exactly once per puzzle (round identity is
      // the goalTable + level; we just bump solved on any new win).
    }
  }, [allMatch, picks]);

  function setPickAt(i: number, op: GateOp) {
    setPicks((cur) => cur.map((v, k) => k === i ? op : v));
  }

  function reset() { setPicks(Array(round.slots).fill(null)); }

  function reroll() { setRound(randomRound(level)); }

  function nextLevel() {
    const newSolved = solved + 1;
    const newLevel = level + 1;
    setSolved(newSolved);
    setLevel(newLevel);
    setRound(randomRound(newLevel));
    if (newSolved > best) {
      setBest(newSolved);
      try { localStorage.setItem(BEST, String(newSolved)); } catch { /* */ }
    }
  }

  const inputLabels = "ABC".slice(0, round.nIn).split("");
  const rows = 1 << round.nIn;

  return (
    <div className="p-5 md:p-8">

      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <span className="px-2.5 py-1 rounded-md bg-accent/15 border border-accent/40 text-[12px] text-accent font-semibold tabular-nums">
            Level {level}
          </span>
          <span className="text-[12px] text-gray-500">
            Solved <span className="text-gray-300 font-semibold tabular-nums">{solved}</span>
            <span className="mx-1.5">·</span>
            Best <span className="text-gray-300 font-semibold tabular-nums">{best}</span>
          </span>
        </div>
        <button onClick={reroll}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-medium text-gray-400 bg-bg-700 border border-bg-600 hover:border-accent/50 hover:text-gray-100 transition-colors"
          title="Generate a different table at this level">
          <Dice5 size={13} /> Reroll
        </button>
      </div>

      <p className="text-[13px] text-gray-400 mb-5 max-w-2xl leading-relaxed">
        A random target truth table appears below. Pick gates so your output
        column matches the target on every row. The target changes every
        round — no two puzzles are the same.
      </p>

      {/* Target vs player columns */}
      <div className="rounded-xl border border-bg-600 bg-bg-800/70 overflow-hidden mb-6 max-w-md">
        <div className="px-3 py-2 text-[11px] text-gray-500 border-b border-bg-600">
          Match the <span className="text-accent">Target</span> column.
        </div>
        <table className="w-full text-[14px] font-mono tabular-nums">
          <thead className="bg-bg-700/40 text-gray-500 text-[11px]">
            <tr>
              {inputLabels.map((c) => (
                <th key={c} className="px-3 py-1.5 text-center font-medium">{c}</th>
              ))}
              <th className="px-3 py-1.5 text-center font-medium text-accent">Target</th>
              <th className="px-3 py-1.5 text-center font-medium text-gray-200">Yours</th>
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: rows }).map((_, i) => {
              const matches = playerColumn[i] !== null && playerColumn[i] === round.target[i];
              return (
                <tr key={i} className="border-t border-bg-600/50">
                  {Array.from({ length: round.nIn }).map((_, k) => (
                    <td key={k} className="px-3 py-1 text-center text-gray-400">
                      {(i >> (round.nIn - 1 - k)) & 1}
                    </td>
                  ))}
                  <td className="px-3 py-1 text-center font-semibold text-accent">
                    {round.target[i]}
                  </td>
                  <td className={`px-3 py-1 text-center font-semibold ${
                    playerColumn[i] === null ? "text-gray-600"
                    : matches ? "text-ok" : "text-err"
                  }`}>
                    {playerColumn[i] ?? "?"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Slot pickers */}
      <div className="grid gap-3 mb-5" style={{ gridTemplateColumns: `repeat(${round.slots}, minmax(0, 1fr))` }}>
        {Array.from({ length: round.slots }).map((_, slotIdx) => (
          <div key={slotIdx} className="flex flex-col gap-1">
            <div className="text-[11px] text-gray-500 text-center">
              Slot {slotIdx + 1}
              {picks[slotIdx] && <span className="text-accent ml-1">· {picks[slotIdx]}</span>}
            </div>
            <div className="flex flex-wrap justify-center gap-1">
              {round.palette.map((g) => (
                <button key={g} onClick={() => setPickAt(slotIdx, g)}
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

      {/* Result + controls */}
      <div className="flex items-center gap-3 flex-wrap">
        {picks.every((p) => p !== null) && (
          <div className={`flex items-center gap-2 px-3 py-2 rounded-md text-[12px] font-medium ${
            allMatch
              ? "bg-ok/10 border border-ok/40 text-ok"
              : "bg-err/10 border border-err/30 text-err"
          }`}>
            {allMatch ? <CheckCircle2 size={14} /> : null}
            <span>
              {allMatch
                ? "All rows match — table built!"
                : `${playerColumn.filter((v, i) => v !== null && v === round.target[i]).length} / ${rows} rows match.`}
            </span>
          </div>
        )}
        <button onClick={reset}
          className="flex items-center gap-1.5 px-3 py-2 rounded-md text-[12px] font-medium text-gray-300 bg-bg-700 border border-bg-600 hover:border-accent/40 transition-colors">
          <RotateCcw size={13} /> Reset
        </button>
        <button onClick={nextLevel} disabled={!allMatch}
          className="flex items-center gap-1.5 px-4 py-2 rounded-md text-[12px] font-semibold text-white bg-accent hover:bg-accent-hover transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
          Next round <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}
