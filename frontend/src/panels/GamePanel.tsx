import { useEffect, useMemo, useState } from "react";
import { RefreshCw, Trophy, Zap } from "lucide-react";

/** A small logic-puzzle game: a random truth table is generated and the
 *  player picks which gate (or NOT) matches it. Streaks earn points, a
 *  wrong answer resets the streak. Best-streak is kept in localStorage. */

type GateAnswer = "AND" | "OR" | "NAND" | "NOR" | "XOR" | "XNOR" | "NOT" | "BUF";
type Difficulty = "easy" | "medium" | "hard";

interface Puzzle {
  nIn: number;
  bits: (0 | 1)[];   // output for each input row (length 2^nIn)
  answer: GateAnswer;
  choices: GateAnswer[];
}

const ALL_2: GateAnswer[] = ["AND", "OR", "NAND", "NOR", "XOR", "XNOR"];
const ALL_1: GateAnswer[] = ["NOT", "BUF"];

function tableOf(nIn: number, op: GateAnswer): (0 | 1)[] {
  const out: (0 | 1)[] = [];
  for (let i = 0; i < (1 << nIn); i++) {
    const bits = Array.from({ length: nIn }, (_, k) => (i >> (nIn - 1 - k)) & 1);
    let v: number;
    if (nIn === 1) {
      const a = bits[0];
      v = op === "NOT" ? (1 - a) : a;
    } else {
      const reduce = (fn: (x: number, y: number) => number) => bits.reduce(fn);
      switch (op) {
        case "AND":  v = reduce((x, y) => x & y); break;
        case "OR":   v = reduce((x, y) => x | y); break;
        case "NAND": v = 1 - reduce((x, y) => x & y); break;
        case "NOR":  v = 1 - reduce((x, y) => x | y); break;
        case "XOR":  v = reduce((x, y) => x ^ y); break;
        case "XNOR": v = 1 - reduce((x, y) => x ^ y); break;
        default:     v = 0;
      }
    }
    out.push(v as 0 | 1);
  }
  return out;
}

function makePuzzle(diff: Difficulty): Puzzle {
  const nIn = diff === "easy" ? 1 : diff === "medium" ? 2 : 3;
  const pool = nIn === 1 ? ALL_1 : ALL_2;
  const answer = pool[Math.floor(Math.random() * pool.length)];
  const bits = tableOf(nIn, answer);
  // Pick 3 distractors (4 choices total) from the same pool
  const others = pool.filter((g) => g !== answer);
  const distractors: GateAnswer[] = [];
  while (distractors.length < Math.min(3, others.length)) {
    const c = others[Math.floor(Math.random() * others.length)];
    if (!distractors.includes(c)) distractors.push(c);
  }
  const choices = [...distractors, answer].sort(() => Math.random() - 0.5);
  return { nIn, bits, answer, choices };
}

const BEST_KEY = "logicgate.game.best";

export function GamePanel() {
  const [diff,      setDiff]      = useState<Difficulty>("medium");
  const [puzzle,    setPuzzle]    = useState<Puzzle>(() => makePuzzle("medium"));
  const [streak,    setStreak]    = useState(0);
  const [best,      setBest]      = useState<number>(() => {
    try { return Number(localStorage.getItem(BEST_KEY) || "0") || 0; }
    catch { return 0; }
  });
  const [last,      setLast]      = useState<{ correct: boolean; picked: GateAnswer } | null>(null);

  useEffect(() => { setPuzzle(makePuzzle(diff)); setLast(null); }, [diff]);

  function answer(pick: GateAnswer) {
    if (last) return;   // already answered — wait for Next
    const correct = pick === puzzle.answer;
    setLast({ correct, picked: pick });
    if (correct) {
      const s = streak + 1;
      setStreak(s);
      if (s > best) {
        setBest(s);
        try { localStorage.setItem(BEST_KEY, String(s)); } catch { /* */ }
      }
    } else {
      setStreak(0);
    }
  }

  function next() { setPuzzle(makePuzzle(diff)); setLast(null); }

  const inputLabels = useMemo(() => "ABC".slice(0, puzzle.nIn).split(""), [puzzle.nIn]);

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[14px] font-semibold text-gray-100">Guess the Gate</div>
          <div className="text-[11px] text-gray-500">Match the truth table to a logic gate.</div>
        </div>
        <button onClick={next} title="Skip / new puzzle"
          className="p-1.5 rounded-md text-gray-400 hover:text-accent hover:bg-bg-700">
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Score row */}
      <div className="flex items-center gap-2">
        <div className="flex-1 flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-bg-700/60 border border-bg-600">
          <Zap size={13} className="text-accent" />
          <span className="text-[11px] text-gray-500">Streak</span>
          <span className="ml-auto text-[14px] font-semibold text-gray-100 tabular-nums">{streak}</span>
        </div>
        <div className="flex-1 flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-bg-700/60 border border-bg-600">
          <Trophy size={13} className="text-warn" />
          <span className="text-[11px] text-gray-500">Best</span>
          <span className="ml-auto text-[14px] font-semibold text-gray-100 tabular-nums">{best}</span>
        </div>
      </div>

      {/* Difficulty */}
      <div className="flex items-center gap-1 text-[11px]">
        <span className="text-gray-500 mr-1">Difficulty</span>
        {(["easy", "medium", "hard"] as Difficulty[]).map((d) => (
          <button key={d} onClick={() => { setDiff(d); setStreak(0); }}
            className={`flex-1 py-1 rounded-md border transition-colors capitalize ${
              diff === d
                ? "bg-accent/15 border-accent/50 text-accent"
                : "bg-bg-700/40 border-bg-600 text-gray-400 hover:text-gray-100"
            }`}>
            {d}
          </button>
        ))}
      </div>

      {/* Truth table */}
      <div className="rounded-lg border border-bg-600 bg-bg-800/60 overflow-hidden">
        <div className="px-3 py-1.5 text-[11px] text-gray-500 border-b border-bg-600">
          What gate produces this output?
        </div>
        <table className="w-full text-[13px] font-mono tabular-nums">
          <thead className="bg-bg-700/30 text-gray-500 text-[11px]">
            <tr>
              {inputLabels.map((c) => (
                <th key={c} className="px-2 py-1 text-center font-medium">{c}</th>
              ))}
              <th className="px-2 py-1 text-center font-medium text-accent">Y</th>
            </tr>
          </thead>
          <tbody>
            {puzzle.bits.map((b, i) => (
              <tr key={i} className="border-t border-bg-600/50">
                {Array.from({ length: puzzle.nIn }).map((_, k) => (
                  <td key={k} className="px-2 py-1 text-center text-gray-400">
                    {(i >> (puzzle.nIn - 1 - k)) & 1}
                  </td>
                ))}
                <td className="px-2 py-1 text-center font-semibold text-gray-100">
                  {b}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Choices */}
      <div className="grid grid-cols-2 gap-2">
        {puzzle.choices.map((c) => {
          const isPicked     = last?.picked  === c;
          const isAnswer     = puzzle.answer === c;
          const showCorrect  = last && isAnswer;
          const showWrong    = last && isPicked && !last.correct;
          const cls = showCorrect
            ? "bg-ok/15 border-ok text-ok"
            : showWrong
              ? "bg-err/15 border-err text-err"
              : last
                ? "bg-bg-700/40 border-bg-600 text-gray-500"
                : "bg-bg-700/60 border-bg-600 text-gray-100 hover:border-accent/60 hover:text-accent";
          return (
            <button key={c} onClick={() => answer(c)} disabled={!!last}
              className={`py-2 rounded-md border text-[13px] font-semibold transition-colors ${cls}`}>
              {c}
            </button>
          );
        })}
      </div>

      {/* Result line */}
      {last && (
        <div className={`rounded-md px-3 py-2 text-[12px] ${
          last.correct
            ? "bg-ok/10 border border-ok/30 text-ok"
            : "bg-err/10 border border-err/30 text-err"
        }`}>
          {last.correct
            ? <>Correct — that's <span className="font-semibold">{puzzle.answer}</span>.</>
            : <>Not quite — that was <span className="font-semibold">{puzzle.answer}</span>.</>}
        </div>
      )}

      <button onClick={next}
        className="w-full py-2 rounded-md bg-accent hover:bg-accent-hover text-white text-[13px] font-semibold transition-colors disabled:opacity-50"
        disabled={!last}
      >
        Next puzzle →
      </button>

      <div className="text-[10px] text-gray-600 text-center pt-1">
        Best streak is saved on this device.
      </div>
    </div>
  );
}
