import { useEffect, useRef, useState } from "react";
import { Zap, Skull, Trophy, Timer } from "lucide-react";
import { BINARY_GATES, tableOf, GATE_GLYPH, type GateOp } from "./logic";

/** Override the Mainframe — arcade timer game.
 *
 *  A truth table is dropped on screen. The player has a few seconds to
 *  pick the matching gate from a small palette. Correct = streak, score
 *  bonus, +time. Wrong = lose time. Game ends when the timer hits zero.
 *  Combo multiplier rewards fast streaks. Best score persists locally. */

type State = "idle" | "playing" | "over";

interface Round {
  nIn: 2 | 3;
  bits: (0 | 1)[];
  answer: GateOp;
  choices: GateOp[];
}

function makeRound(level: number): Round {
  const nIn: 2 | 3 = level < 3 ? 2 : 3;
  const ans = BINARY_GATES[Math.floor(Math.random() * BINARY_GATES.length)];
  const bits = tableOf(nIn, ans);
  // Pick 3 distinct distractors
  const pool = BINARY_GATES.filter((g) => g !== ans);
  const ds: GateOp[] = [];
  while (ds.length < 3) {
    const c = pool[Math.floor(Math.random() * pool.length)];
    if (!ds.includes(c)) ds.push(c);
  }
  const choices = [...ds, ans].sort(() => Math.random() - 0.5);
  return { nIn, bits, answer: ans, choices };
}

const BEST = "logicgate.override.best";
const START_TIME = 20_000;       // ms
const CORRECT_BONUS = 2_500;
const WRONG_PENALTY = 4_000;

export function OverrideMode() {
  const [state, setState] = useState<State>("idle");
  const [round, setRound] = useState<Round>(() => makeRound(0));
  const [solved, setSolved] = useState(0);
  const [score, setScore] = useState(0);
  const [combo, setCombo] = useState(0);
  const [maxCombo, setMaxCombo] = useState(0);
  const [timeLeft, setTimeLeft] = useState(START_TIME);
  const [best, setBest] = useState<number>(() => {
    try { return Number(localStorage.getItem(BEST) || "0") || 0; }
    catch { return 0; }
  });
  const [flash, setFlash] = useState<"good" | "bad" | null>(null);

  const startedAt = useRef<number>(0);
  const lastTick  = useRef<number>(0);

  // Tick the clock while playing
  useEffect(() => {
    if (state !== "playing") return;
    let raf = 0;
    const loop = (now: number) => {
      const dt = lastTick.current ? now - lastTick.current : 0;
      lastTick.current = now;
      setTimeLeft((t) => {
        const n = t - dt;
        if (n <= 0) {
          endGame();
          return 0;
        }
        return n;
      });
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  function start() {
    setSolved(0); setScore(0); setCombo(0); setMaxCombo(0);
    setTimeLeft(START_TIME);
    startedAt.current = performance.now();
    lastTick.current  = 0;
    setRound(makeRound(0));
    setFlash(null);
    setState("playing");
  }

  function endGame() {
    setState("over");
    setBest((b) => {
      if (score > b) {
        try { localStorage.setItem(BEST, String(score)); } catch { /* */ }
        return score;
      }
      return b;
    });
  }

  function pick(g: GateOp) {
    if (state !== "playing") return;
    if (g === round.answer) {
      const c = combo + 1;
      const points = 100 + c * 25;
      setSolved((s) => s + 1);
      setCombo(c);
      setMaxCombo((m) => Math.max(m, c));
      setScore((s) => s + points);
      setTimeLeft((t) => Math.min(t + CORRECT_BONUS, 30_000));
      setRound(makeRound(solved + 1));
      setFlash("good");
      setTimeout(() => setFlash((f) => f === "good" ? null : f), 200);
    } else {
      setCombo(0);
      setTimeLeft((t) => Math.max(t - WRONG_PENALTY, 0));
      setFlash("bad");
      setTimeout(() => setFlash((f) => f === "bad" ? null : f), 250);
    }
  }

  const inputLabels = "ABC".slice(0, round.nIn).split("");
  const timePct = Math.max(0, Math.min(1, timeLeft / 30_000));

  return (
    <div className={`flex-1 flex flex-col min-h-0 overflow-y-auto p-5 md:p-8 transition-all ${
      flash === "good" ? "bg-ok/5" : flash === "bad" ? "bg-err/5" : ""
    }`}>

      {/* HUD */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-5">
        <Stat icon={<Timer size={14} />} label="Time" value={(timeLeft / 1000).toFixed(1) + "s"} accent={timeLeft < 5000 ? "err" : "accent"} />
        <Stat icon={<Zap size={14} />}   label="Combo" value={`x${combo}`} accent={combo >= 5 ? "warn" : "accent"} />
        <Stat icon={<Trophy size={14} />} label="Score" value={String(score)} />
        <Stat icon={<Skull size={14} />}  label="Best"  value={String(best)}  />
      </div>

      {/* Timer bar */}
      <div className="h-2 rounded-full bg-bg-700 mb-6 overflow-hidden">
        <div className={`h-full transition-all ${timeLeft < 5000 ? "bg-err" : timeLeft < 10_000 ? "bg-warn" : "bg-accent"}`}
             style={{ width: `${timePct * 100}%` }} />
      </div>

      {state === "idle" && (
        <Splash
          title="Override the Mainframe"
          body="Match the truth table to the right gate before time runs out. Fast streaks earn bonus time and combo points."
          cta="Start"
          onCta={start}
        />
      )}

      {state === "over" && (
        <Splash
          title="Connection lost"
          body={
            <>
              Score <span className="text-accent font-bold">{score}</span> · longest combo x{maxCombo} · puzzles solved {solved}
              {score >= best && score > 0 && <div className="mt-2 text-warn">⚡ New best!</div>}
            </>
          }
          cta="Run again"
          onCta={start}
        />
      )}

      {state === "playing" && (
        <>
          <div className="text-[12px] text-gray-500 mb-2">
            Round {solved + 1} · {round.nIn} inputs
          </div>
          <div className="rounded-xl border border-bg-600 bg-bg-800/70 overflow-hidden mb-5 max-w-md">
            <div className="px-3 py-2 text-[11px] text-gray-500 border-b border-bg-600">
              What gate produces this output?
            </div>
            <table className="w-full text-[14px] font-mono tabular-nums">
              <thead className="bg-bg-700/40 text-gray-500 text-[11px]">
                <tr>
                  {inputLabels.map((c) => (
                    <th key={c} className="px-3 py-1.5 text-center font-medium">{c}</th>
                  ))}
                  <th className="px-3 py-1.5 text-center font-medium text-accent">Y</th>
                </tr>
              </thead>
              <tbody>
                {round.bits.map((b, i) => (
                  <tr key={i} className="border-t border-bg-600/50">
                    {Array.from({ length: round.nIn }).map((_, k) => (
                      <td key={k} className="px-3 py-1 text-center text-gray-400">
                        {(i >> (round.nIn - 1 - k)) & 1}
                      </td>
                    ))}
                    <td className="px-3 py-1 text-center font-semibold text-gray-100">
                      {b}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {round.choices.map((g) => (
              <button key={g} onClick={() => pick(g)}
                className="py-3 rounded-lg border border-bg-600 bg-bg-800 hover:bg-accent/10 hover:border-accent text-gray-100 text-[14px] font-semibold transition-colors">
                <span className="opacity-70 mr-1">{GATE_GLYPH[g]}</span>{g}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ icon, label, value, accent = "accent" }: {
  icon: React.ReactNode; label: string; value: string; accent?: "accent" | "warn" | "err";
}) {
  const valClr = accent === "warn" ? "text-warn" : accent === "err" ? "text-err" : "text-gray-100";
  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-bg-800/60 border border-bg-600">
      <span className="text-gray-500">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div>
        <div className={`text-[14px] font-semibold tabular-nums ${valClr}`}>{value}</div>
      </div>
    </div>
  );
}

function Splash({ title, body, cta, onCta }: {
  title: string; body: React.ReactNode; cta: string; onCta: () => void;
}) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center py-10 gap-4">
      <h2 className="text-[24px] font-bold text-gray-100">{title}</h2>
      <div className="text-[13px] text-gray-400 max-w-md leading-relaxed">{body}</div>
      <button onClick={onCta}
        className="px-6 py-2.5 rounded-lg bg-accent hover:bg-accent-hover text-white text-[14px] font-semibold transition-colors">
        {cta}
      </button>
    </div>
  );
}
