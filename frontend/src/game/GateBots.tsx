import { useEffect, useMemo, useRef, useState } from "react";
import {
  Swords, Shield, Zap, Heart, Crosshair, Wind, RotateCcw,
  ChevronRight, Trophy, Users, Bot, Lock, Check,
} from "lucide-react";

/**
 * Gate Bots — build a fighting robot out of logic gates.
 *
 * Every gate type contributes a different stat, so "what gates do I have"
 * becomes a build-craft puzzle:
 *
 *   AND  = Armor        (flat damage reduction)
 *   OR   = Attack       (more damage per hit)
 *   NOT  = Speed        (turn order + dodge chance)
 *   XOR  = Crit         (chance to double damage)
 *   NAND = HP           (universal gate = sturdy chassis)
 *   NOR  = Counter      (chance to strike back when hit)
 *   XNOR = Accuracy     (reduces enemy dodge)
 *   BUF  = Shield       (absorbs the first hits)
 *
 * Campaign: 10 stages. Each stage hands you a fixed, limited inventory —
 * you must build from only those gates. Bosses are predefined builds.
 * Versus: hot-seat 1v1. P1 builds, hand the device over, P2 builds, fight.
 *
 * Everything is client-side; campaign progress + wins persist in
 * localStorage. Battle is deterministic-with-seeded-rng per fight so the
 * log replay is stable.
 */

/* ── stats model ─────────────────────────────────────────────────────── */

type BotGate = "AND" | "OR" | "NOT" | "XOR" | "NAND" | "NOR" | "XNOR" | "BUF";

const GATE_INFO: Record<BotGate, {
  stat: string; desc: string; colour: string; icon: React.ReactNode;
}> = {
  AND:  { stat: "Armor",   desc: "-1.5 damage taken per AND",      colour: "#818cf8", icon: <Shield size={12} /> },
  OR:   { stat: "Attack",  desc: "+3 damage per OR",               colour: "#fb7185", icon: <Swords size={12} /> },
  NOT:  { stat: "Speed",   desc: "+6% dodge, turn order per NOT",  colour: "#2dd4bf", icon: <Wind size={12} /> },
  XOR:  { stat: "Crit",    desc: "+8% crit (2x damage) per XOR",   colour: "#fbbf24", icon: <Crosshair size={12} /> },
  NAND: { stat: "HP",      desc: "+14 max HP per NAND",            colour: "#34d399", icon: <Heart size={12} /> },
  NOR:  { stat: "Counter", desc: "+9% counter-attack per NOR",     colour: "#a78bfa", icon: <RotateCcw size={12} /> },
  XNOR: { stat: "Aim",     desc: "-5% enemy dodge per XNOR",       colour: "#f472b6", icon: <Crosshair size={12} /> },
  BUF:  { stat: "Shield",  desc: "+8 shield (absorbed first) per BUF", colour: "#60a5fa", icon: <Zap size={12} /> },
};

const ALL_BOT_GATES: BotGate[] = ["AND", "OR", "NOT", "XOR", "NAND", "NOR", "XNOR", "BUF"];
const MAX_SLOTS = 8;

interface Stats {
  hp: number; shield: number; atk: number; armor: number;
  dodge: number; crit: number; counter: number; aim: number;
}

function statsOf(build: BotGate[]): Stats {
  const c = (g: BotGate) => build.filter((x) => x === g).length;
  return {
    hp:      40 + c("NAND") * 14 + build.length * 2,
    shield:  c("BUF") * 8,
    atk:     8 + c("OR") * 3,
    armor:   c("AND") * 1.5,
    dodge:   Math.min(0.45, c("NOT") * 0.06),
    crit:    Math.min(0.6,  c("XOR") * 0.08),
    counter: Math.min(0.5,  c("NOR") * 0.09),
    aim:     c("XNOR") * 0.05,
  };
}

/* ── campaign stages ─────────────────────────────────────────────────── */

interface Stage {
  name: string;
  tagline: string;
  inventory: Partial<Record<BotGate, number>>;
  boss: { name: string; build: BotGate[] };
}

const STAGES: Stage[] = [
  { name: "Scrapyard",   tagline: "Two gates. Make them count.",
    inventory: { AND: 2, OR: 2 },
    boss: { name: "RUSTY",     build: ["OR", "OR", "AND"] } },
  { name: "Assembly",    tagline: "Speed enters the meta.",
    inventory: { AND: 2, OR: 2, NOT: 2 },
    boss: { name: "SPRINTER",  build: ["NOT", "NOT", "OR", "OR"] } },
  { name: "Foundry",     tagline: "NAND chassis unlocked.",
    inventory: { AND: 2, OR: 3, NOT: 2, NAND: 2 },
    boss: { name: "TANKER",    build: ["NAND", "NAND", "AND", "AND", "OR"] } },
  { name: "Crit Lab",    tagline: "XOR brings the spice.",
    inventory: { OR: 3, NOT: 2, XOR: 3 },
    boss: { name: "GAMBLER",   build: ["XOR", "XOR", "XOR", "OR", "OR"] } },
  { name: "Bunker",      tagline: "Counter-strike protocols.",
    inventory: { AND: 3, NAND: 2, NOR: 3 },
    boss: { name: "PORCUPINE", build: ["NOR", "NOR", "NOR", "AND", "NAND", "NAND"] } },
  { name: "Range",       tagline: "Accuracy beats evasion.",
    inventory: { OR: 3, XNOR: 3, XOR: 2 },
    boss: { name: "GHOST",     build: ["NOT", "NOT", "NOT", "NOT", "OR", "OR"] } },
  { name: "Shield Wall", tagline: "Buffers soak the alpha strike.",
    inventory: { BUF: 3, AND: 2, OR: 3, NAND: 2 },
    boss: { name: "BASTION",   build: ["BUF", "BUF", "BUF", "AND", "AND", "NAND", "OR"] } },
  { name: "Proving Grounds", tagline: "Full arsenal, tight budget.",
    inventory: { AND: 1, OR: 2, NOT: 1, XOR: 1, NAND: 1, NOR: 1, XNOR: 1 },
    boss: { name: "WARDEN",    build: ["NAND", "NAND", "AND", "OR", "OR", "XOR", "NOR"] } },
  { name: "Storm Spire", tagline: "The boss crits. A lot.",
    inventory: { AND: 2, OR: 3, NOT: 2, XOR: 2, NAND: 2 },
    boss: { name: "TEMPEST",   build: ["XOR", "XOR", "XOR", "XOR", "OR", "OR", "NOT", "NAND"] } },
  { name: "Core Vault",  tagline: "Everything. Beat the final form.",
    inventory: { AND: 2, OR: 3, NOT: 2, XOR: 2, NAND: 2, NOR: 2, XNOR: 2, BUF: 2 },
    boss: { name: "OMEGA",     build: ["NAND", "NAND", "OR", "OR", "OR", "XOR", "NOR", "BUF"] } },
];

/* ── battle engine ───────────────────────────────────────────────────── */

interface Fighter { name: string; build: BotGate[]; stats: Stats; }
interface LogEntry {
  text: string;
  kind: "hit" | "crit" | "dodge" | "counter" | "shield" | "info" | "win";
  hpA: number; hpB: number; shA: number; shB: number;
}

// Tiny seeded RNG so a battle replays identically while animating.
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function runBattle(A: Fighter, B: Fighter, seed: number): { log: LogEntry[]; winner: 0 | 1 } {
  const rng = mulberry32(seed);
  let hpA = A.stats.hp, hpB = B.stats.hp;
  let shA = A.stats.shield, shB = B.stats.shield;
  const log: LogEntry[] = [];
  const push = (text: string, kind: LogEntry["kind"]) =>
    log.push({ text, kind, hpA: Math.max(0, hpA), hpB: Math.max(0, hpB), shA, shB });

  push(`${A.name} vs ${B.name} — fight!`, "info");

  // Speed decides who acts first each round; ties go to A (the challenger).
  const speedA = A.build.filter((g) => g === "NOT").length;
  const speedB = B.build.filter((g) => g === "NOT").length;

  const doAttack = (att: Fighter, defF: Fighter, attIsA: boolean): boolean => {
    const a = att.stats, d = defF.stats;
    const dodge = Math.max(0, d.dodge - a.aim);
    if (rng() < dodge) {
      push(`${defF.name} dodges ${att.name}'s attack!`, "dodge");
      return false;
    }
    const isCrit = rng() < a.crit;
    let dmg = a.atk * (isCrit ? 2 : 1) * (0.85 + rng() * 0.3);
    dmg = Math.max(1, dmg - d.armor);
    dmg = Math.round(dmg);

    // Shields absorb first
    let absorbed = 0;
    if (attIsA) {
      if (shB > 0) { absorbed = Math.min(shB, dmg); shB -= absorbed; }
      hpB -= (dmg - absorbed);
    } else {
      if (shA > 0) { absorbed = Math.min(shA, dmg); shA -= absorbed; }
      hpA -= (dmg - absorbed);
    }
    if (absorbed > 0) {
      push(`${defF.name}'s shield absorbs ${absorbed}!`, "shield");
    }
    push(
      isCrit
        ? `CRIT! ${att.name} smashes ${defF.name} for ${dmg}!`
        : `${att.name} hits ${defF.name} for ${dmg}.`,
      isCrit ? "crit" : "hit",
    );
    // Counter chance
    const defAlive = attIsA ? hpB > 0 : hpA > 0;
    if (defAlive && rng() < d.counter) {
      let cdmg = Math.max(1, Math.round(d.atk * 0.6 - a.armor));
      if (attIsA) hpA -= cdmg; else hpB -= cdmg;
      push(`${defF.name} counters for ${cdmg}!`, "counter");
    }
    return attIsA ? hpB <= 0 : hpA <= 0;
  };

  for (let round = 1; round <= 30 && hpA > 0 && hpB > 0; round++) {
    const aFirst = speedA >= speedB;
    const order: Array<[Fighter, Fighter, boolean]> = aFirst
      ? [[A, B, true], [B, A, false]]
      : [[B, A, false], [A, B, true]];
    for (const [att, defF, attIsA] of order) {
      if (hpA <= 0 || hpB <= 0) break;
      doAttack(att, defF, attIsA);
    }
  }

  // Timeout tiebreak: higher remaining HP percentage wins.
  if (hpA > 0 && hpB > 0) {
    const fracA = hpA / A.stats.hp, fracB = hpB / B.stats.hp;
    if (fracA >= fracB) hpB = 0; else hpA = 0;
    push("Time! Judges score the remaining hull.", "info");
  }

  const winner: 0 | 1 = hpA > 0 ? 0 : 1;
  push(`${winner === 0 ? A.name : B.name} WINS!`, "win");
  return { log, winner };
}

/* ── persistence ─────────────────────────────────────────────────────── */

const PROGRESS_KEY = "logicgate.bots.progress";   // highest stage cleared (0-based count)

function loadProgress(): number {
  try { return Number(localStorage.getItem(PROGRESS_KEY) || "0") || 0; }
  catch { return 0; }
}

/* ── robot visual ────────────────────────────────────────────────────── */

function RobotFigure({ build, facing = 1, hurt }: {
  build: BotGate[]; facing?: 1 | -1; hurt?: boolean;
}) {
  // The robot is literally assembled from its gates: head is the first
  // gate, torso the next 3, arms/legs from the rest. Empty slots render
  // as dim placeholders so a 2-gate bot looks appropriately scrappy.
  const head  = build[0];
  const torso = build.slice(1, 4);
  const armL  = build[4];
  const armR  = build[5];
  const legL  = build[6];
  const legR  = build[7];

  const Cell = ({ g, w = 34, h = 24 }: { g?: BotGate; w?: number; h?: number }) => (
    <div
      className="rounded-md border flex items-center justify-center text-[9px] font-bold font-mono transition-colors"
      style={{
        width: w, height: h,
        background: g ? `${GATE_INFO[g].colour}22` : "transparent",
        borderColor: g ? GATE_INFO[g].colour : "var(--lg-bg-600)",
        color: g ? GATE_INFO[g].colour : "var(--lg-fg-600)",
        borderStyle: g ? "solid" : "dashed",
      }}
    >
      {g ?? "·"}
    </div>
  );

  return (
    <div
      className={`flex flex-col items-center gap-1 transition-transform ${hurt ? "animate-pulse" : ""}`}
      style={{ transform: `scaleX(${facing})` }}
    >
      <Cell g={head} w={30} h={26} />
      <div className="flex items-center gap-1">
        <Cell g={armL} w={20} h={40} />
        <div className="flex flex-col gap-1">
          {([0, 1, 2] as const).map((i) => <Cell key={i} g={torso[i]} />)}
        </div>
        <Cell g={armR} w={20} h={40} />
      </div>
      <div className="flex gap-2">
        <Cell g={legL} w={20} h={26} />
        <Cell g={legR} w={20} h={26} />
      </div>
    </div>
  );
}

/* ── stat readout ────────────────────────────────────────────────────── */

function StatBar({ build }: { build: BotGate[] }) {
  const s = statsOf(build);
  const rows: Array<[string, string]> = [
    ["HP",      String(s.hp)],
    ["Shield",  String(s.shield)],
    ["Attack",  String(s.atk)],
    ["Armor",   s.armor.toFixed(1)],
    ["Dodge",   `${Math.round(s.dodge * 100)}%`],
    ["Crit",    `${Math.round(s.crit * 100)}%`],
    ["Counter", `${Math.round(s.counter * 100)}%`],
    ["Aim",     `+${Math.round(s.aim * 100)}%`],
  ];
  return (
    <div className="grid grid-cols-4 gap-x-3 gap-y-0.5 text-[10px] tabular-nums">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-1">
          <span className="text-gray-500">{k}</span>
          <span className="text-gray-200 font-semibold">{v}</span>
        </div>
      ))}
    </div>
  );
}

/* ── main component ──────────────────────────────────────────────────── */

type Screen =
  | { kind: "menu" }
  | { kind: "stages" }
  | { kind: "build"; stage: number }                      // campaign build
  | { kind: "vs-build"; player: 1 | 2; p1?: BotGate[] }   // hotseat build
  | { kind: "battle"; A: Fighter; B: Fighter; stage?: number };

export function GateBots() {
  const [screen, setScreen]     = useState<Screen>({ kind: "menu" });
  const [progress, setProgress] = useState<number>(loadProgress);

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto p-4 md:p-6">
      {screen.kind === "menu" && (
        <Menu progress={progress}
          onCampaign={() => setScreen({ kind: "stages" })}
          onVersus={() => setScreen({ kind: "vs-build", player: 1 })} />
      )}
      {screen.kind === "stages" && (
        <StageSelect progress={progress}
          onPick={(i) => setScreen({ kind: "build", stage: i })}
          onBack={() => setScreen({ kind: "menu" })} />
      )}
      {screen.kind === "build" && (
        <Builder
          title={`Stage ${screen.stage + 1} — ${STAGES[screen.stage].name}`}
          subtitle={STAGES[screen.stage].tagline}
          inventory={STAGES[screen.stage].inventory}
          enemyPreview={STAGES[screen.stage].boss}
          onBack={() => setScreen({ kind: "stages" })}
          onFight={(build) => {
            const stage = STAGES[screen.stage];
            setScreen({
              kind: "battle", stage: screen.stage,
              A: { name: "YOUR BOT", build, stats: statsOf(build) },
              B: { name: stage.boss.name, build: stage.boss.build, stats: statsOf(stage.boss.build) },
            });
          }}
        />
      )}
      {screen.kind === "vs-build" && (
        <Builder
          title={`Player ${screen.player} — build your bot`}
          subtitle={screen.player === 1
            ? "Build, then pass the device to Player 2."
            : "Player 1 is locked in. Your turn."}
          inventory={{ AND: 3, OR: 3, NOT: 3, XOR: 3, NAND: 3, NOR: 3, XNOR: 3, BUF: 3 }}
          hideEnemy
          onBack={() => setScreen({ kind: "menu" })}
          onFight={(build) => {
            if (screen.player === 1) {
              setScreen({ kind: "vs-build", player: 2, p1: build });
            } else {
              const p1 = screen.p1!;
              setScreen({
                kind: "battle",
                A: { name: "PLAYER 1", build: p1,   stats: statsOf(p1) },
                B: { name: "PLAYER 2", build, stats: statsOf(build) },
              });
            }
          }}
        />
      )}
      {screen.kind === "battle" && (
        <Battle
          A={screen.A} B={screen.B}
          onDone={(winner) => {
            if (screen.stage !== undefined && winner === 0 && screen.stage >= progress) {
              const np = screen.stage + 1;
              setProgress(np);
              try { localStorage.setItem(PROGRESS_KEY, String(np)); } catch { /* */ }
            }
          }}
          onExit={() => setScreen(screen.stage !== undefined ? { kind: "stages" } : { kind: "menu" })}
          onRematch={() => {
            // Re-enter the same battle with a fresh seed (new state object).
            setScreen({ ...screen });
          }}
        />
      )}
    </div>
  );
}

/* ── menu ───────────────────────────────────────────────────────────── */

function Menu({ progress, onCampaign, onVersus }: {
  progress: number; onCampaign: () => void; onVersus: () => void;
}) {
  return (
    <div className="max-w-2xl mx-auto w-full">
      <div className="text-center mb-6">
        <h2 className="text-[26px] font-bold text-gray-100 mb-1">Gate Bots</h2>
        <p className="text-[13px] text-gray-400">
          Build a robot out of logic gates. Every gate type is a different stat —
          your inventory is your build budget.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-4 mb-6">
        <button onClick={onCampaign}
          className="text-left rounded-2xl border border-accent/50 bg-accent/10 hover:bg-accent/15 p-5 transition-colors">
          <div className="flex items-center gap-2 mb-1">
            <Bot size={18} className="text-accent" />
            <span className="text-[16px] font-semibold text-gray-100">Campaign</span>
          </div>
          <p className="text-[12px] text-gray-400 mb-2">
            10 stages. Limited gates each. Predefined bosses that escalate.
          </p>
          <span className="text-[11px] text-accent font-medium">
            {progress >= STAGES.length ? "All stages cleared 🏆" : `Progress: ${progress} / ${STAGES.length}`}
          </span>
        </button>

        <button onClick={onVersus}
          className="text-left rounded-2xl border border-bg-600 bg-bg-800/70 hover:bg-bg-800 hover:border-accent/40 p-5 transition-colors">
          <div className="flex items-center gap-2 mb-1">
            <Users size={18} className="text-warn" />
            <span className="text-[16px] font-semibold text-gray-100">1 v 1 — Hot-seat</span>
          </div>
          <p className="text-[12px] text-gray-400 mb-2">
            Both players build on this device (builds stay hidden), then the bots fight.
          </p>
          <span className="text-[11px] text-warn font-medium">Same screen · 2 players</span>
        </button>
      </div>

      {/* Gate legend */}
      <div className="rounded-xl border border-bg-600 bg-bg-800/60 p-4">
        <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-2">Gate → stat guide</div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {ALL_BOT_GATES.map((g) => (
            <div key={g} className="flex items-center gap-2 text-[11px]">
              <span className="w-12 px-1.5 py-0.5 rounded text-center font-mono font-bold"
                style={{ background: `${GATE_INFO[g].colour}22`, color: GATE_INFO[g].colour }}>
                {g}
              </span>
              <span className="text-gray-400">{GATE_INFO[g].stat}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── stage select ───────────────────────────────────────────────────── */

function StageSelect({ progress, onPick, onBack }: {
  progress: number; onPick: (i: number) => void; onBack: () => void;
}) {
  return (
    <div className="max-w-3xl mx-auto w-full">
      <div className="flex items-center gap-3 mb-4">
        <button onClick={onBack} className="text-[12px] text-gray-400 hover:text-accent">← Back</button>
        <h2 className="text-[20px] font-semibold text-gray-100">Campaign</h2>
        <span className="text-[12px] text-gray-500">{progress} / {STAGES.length} cleared</span>
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        {STAGES.map((s, i) => {
          const unlocked = i <= progress;
          const cleared  = i < progress;
          return (
            <button key={s.name} disabled={!unlocked}
              onClick={() => onPick(i)}
              className={`text-left rounded-xl border p-4 transition-colors ${
                unlocked
                  ? "border-bg-600 bg-bg-800/70 hover:border-accent/50 hover:bg-bg-800"
                  : "border-bg-600/50 bg-bg-800/30 opacity-50 cursor-not-allowed"
              }`}>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[12px] font-mono text-gray-500">#{i + 1}</span>
                <span className="text-[14px] font-semibold text-gray-100">{s.name}</span>
                <div className="flex-1" />
                {cleared && <Check size={14} className="text-ok" />}
                {!unlocked && <Lock size={13} className="text-gray-600" />}
              </div>
              <p className="text-[11px] text-gray-500 mb-2">{s.tagline}</p>
              <div className="flex flex-wrap gap-1">
                {Object.entries(s.inventory).map(([g, n]) => (
                  <span key={g} className="px-1.5 py-0.5 rounded text-[10px] font-mono"
                    style={{ background: `${GATE_INFO[g as BotGate].colour}18`,
                             color: GATE_INFO[g as BotGate].colour }}>
                    {n}× {g}
                  </span>
                ))}
              </div>
              <div className="mt-2 text-[10px] text-gray-600">
                Boss: <span className="text-err font-semibold">{s.boss.name}</span>
                {" "}({s.boss.build.length} gates)
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ── builder ────────────────────────────────────────────────────────── */

function Builder({ title, subtitle, inventory, enemyPreview, hideEnemy, onFight, onBack }: {
  title: string; subtitle: string;
  inventory: Partial<Record<BotGate, number>>;
  enemyPreview?: { name: string; build: BotGate[] };
  hideEnemy?: boolean;
  onFight: (build: BotGate[]) => void;
  onBack: () => void;
}) {
  const [build, setBuild] = useState<BotGate[]>([]);

  const remaining = useMemo(() => {
    const r: Partial<Record<BotGate, number>> = { ...inventory };
    for (const g of build) r[g] = (r[g] ?? 0) - 1;
    return r;
  }, [build, inventory]);

  function add(g: BotGate) {
    if (build.length >= MAX_SLOTS) return;
    if ((remaining[g] ?? 0) <= 0) return;
    setBuild((b) => [...b, g]);
  }
  function removeAt(i: number) {
    setBuild((b) => b.filter((_, k) => k !== i));
  }

  return (
    <div className="max-w-3xl mx-auto w-full">
      <div className="flex items-center gap-3 mb-1 flex-wrap">
        <button onClick={onBack} className="text-[12px] text-gray-400 hover:text-accent">← Back</button>
        <h2 className="text-[18px] font-semibold text-gray-100">{title}</h2>
      </div>
      <p className="text-[12px] text-gray-500 mb-4">{subtitle}</p>

      <div className="grid md:grid-cols-[1fr_auto_1fr] gap-4 items-start">
        {/* Inventory + slots */}
        <div className="space-y-3">
          <div className="rounded-xl border border-bg-600 bg-bg-800/60 p-3">
            <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-2">
              Inventory — tap to install ({build.length}/{MAX_SLOTS} slots)
            </div>
            <div className="flex flex-wrap gap-1.5">
              {ALL_BOT_GATES.filter((g) => (inventory[g] ?? 0) > 0).map((g) => {
                const left = remaining[g] ?? 0;
                return (
                  <button key={g} disabled={left <= 0 || build.length >= MAX_SLOTS}
                    onClick={() => add(g)}
                    title={GATE_INFO[g].desc}
                    className="px-2.5 py-2 rounded-lg border text-[12px] font-mono font-bold transition-all disabled:opacity-30 min-h-[40px]"
                    style={{
                      background: `${GATE_INFO[g].colour}15`,
                      borderColor: `${GATE_INFO[g].colour}60`,
                      color: GATE_INFO[g].colour,
                    }}>
                    {g} <span className="opacity-70">×{left}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="rounded-xl border border-bg-600 bg-bg-800/60 p-3">
            <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-2">
              Installed — tap to remove
            </div>
            {build.length === 0 ? (
              <div className="text-[11px] text-gray-600 italic py-2">
                No gates installed. Your bot is a sad empty frame.
              </div>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {build.map((g, i) => (
                  <button key={i} onClick={() => removeAt(i)}
                    className="px-2.5 py-1.5 rounded-lg border text-[12px] font-mono font-bold min-h-[36px]"
                    style={{
                      background: `${GATE_INFO[g].colour}22`,
                      borderColor: GATE_INFO[g].colour,
                      color: GATE_INFO[g].colour,
                    }}>
                    {g} ✕
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-xl border border-bg-600 bg-bg-800/60 p-3">
            <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-2">Your stats</div>
            <StatBar build={build} />
          </div>
        </div>

        {/* Robot preview */}
        <div className="flex flex-col items-center gap-2 py-2 mx-auto">
          <RobotFigure build={build} />
          <span className="text-[10px] text-gray-500">your bot</span>
        </div>

        {/* Enemy preview */}
        <div className="space-y-3">
          {!hideEnemy && enemyPreview && (
            <div className="rounded-xl border border-err/30 bg-err/5 p-3">
              <div className="text-[11px] uppercase tracking-wider text-err mb-2 flex items-center gap-1.5">
                <Swords size={11} /> Boss: {enemyPreview.name}
              </div>
              <div className="flex justify-center mb-2">
                <RobotFigure build={enemyPreview.build} facing={-1} />
              </div>
              <StatBar build={enemyPreview.build} />
            </div>
          )}
          {hideEnemy && (
            <div className="rounded-xl border border-bg-600 bg-bg-800/40 p-3 text-[11px] text-gray-500 italic">
              Opponent's build is hidden — you'll see it in the arena.
            </div>
          )}

          <button onClick={() => onFight(build)} disabled={build.length === 0}
            className="w-full py-3 rounded-xl bg-accent hover:bg-accent-hover text-white text-[14px] font-bold transition-colors disabled:opacity-40 flex items-center justify-center gap-2">
            <Swords size={15} /> FIGHT <ChevronRight size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── battle ─────────────────────────────────────────────────────────── */

function Battle({ A, B, onDone, onExit, onRematch }: {
  A: Fighter; B: Fighter;
  onDone: (winner: 0 | 1) => void;
  onExit: () => void;
  onRematch: () => void;
}) {
  // Battle is fully computed up-front with a random seed, then the log is
  // revealed entry-by-entry on a timer. Replays smoothly, no rAF needed.
  const [result] = useState(() => runBattle(A, B, Math.floor(Math.random() * 1e9)));
  const [step, setStep] = useState(0);
  const doneRef = useRef(false);

  const total = result.log.length;
  const cur   = result.log[Math.min(step, total - 1)];
  const finished = step >= total - 1;

  useEffect(() => {
    if (finished) {
      if (!doneRef.current) { doneRef.current = true; onDone(result.winner); }
      return;
    }
    const t = setTimeout(() => setStep((s) => s + 1), 650);
    return () => clearTimeout(t);
  }, [step, finished, onDone, result.winner]);

  const hpPctA = Math.max(0, cur.hpA / A.stats.hp) * 100;
  const hpPctB = Math.max(0, cur.hpB / B.stats.hp) * 100;

  return (
    <div className="max-w-3xl mx-auto w-full">
      {/* Health bars */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        {[
          { f: A, pct: hpPctA, hp: cur.hpA, sh: cur.shA },
          { f: B, pct: hpPctB, hp: cur.hpB, sh: cur.shB },
        ].map(({ f, pct, hp, sh }, i) => (
          <div key={i}>
            <div className="flex items-center justify-between text-[12px] mb-1">
              <span className="font-semibold text-gray-100">{f.name}</span>
              <span className="text-gray-400 tabular-nums">
                {Math.max(0, hp)} / {f.stats.hp}
                {sh > 0 && <span className="text-blue-400 ml-1">+{sh}🛡</span>}
              </span>
            </div>
            <div className="h-3 rounded-full bg-bg-700 overflow-hidden">
              <div className={`h-full transition-all duration-500 ${
                pct > 50 ? "bg-ok" : pct > 25 ? "bg-warn" : "bg-err"
              }`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        ))}
      </div>

      {/* Arena */}
      <div className="rounded-2xl border border-bg-600 bg-bg-800/50 px-6 py-6 mb-4 flex items-center justify-around min-h-[180px]">
        <RobotFigure build={A.build}
          hurt={cur.kind === "hit" || cur.kind === "crit" ? cur.hpA < (result.log[Math.max(0, step - 1)]?.hpA ?? Infinity) : false} />
        <div className="text-[22px] font-black text-gray-600">VS</div>
        <RobotFigure build={B.build} facing={-1}
          hurt={cur.kind === "hit" || cur.kind === "crit" ? cur.hpB < (result.log[Math.max(0, step - 1)]?.hpB ?? Infinity) : false} />
      </div>

      {/* Battle log (last 5 entries) */}
      <div className="rounded-xl border border-bg-600 bg-bg-800/60 p-3 mb-4 min-h-[120px]">
        {result.log.slice(Math.max(0, step - 4), step + 1).map((e, i) => (
          <div key={i} className={`text-[12px] py-0.5 ${
            e.kind === "crit"    ? "text-warn font-semibold"
            : e.kind === "dodge"   ? "text-accent"
            : e.kind === "counter" ? "text-violet-400"
            : e.kind === "shield"  ? "text-blue-400"
            : e.kind === "win"     ? "text-ok font-bold text-[14px]"
            : e.kind === "info"    ? "text-gray-500 italic"
            : "text-gray-300"
          }`}>
            {e.text}
          </div>
        ))}
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2 flex-wrap">
        {!finished && (
          <button onClick={() => setStep(total - 1)}
            className="px-3 py-2 rounded-md text-[12px] font-medium text-gray-300 bg-bg-700 border border-bg-600 hover:border-accent/40">
            Skip to result
          </button>
        )}
        {finished && (
          <>
            <div className={`flex items-center gap-2 px-3 py-2 rounded-md text-[13px] font-semibold ${
              result.winner === 0 ? "bg-ok/10 border border-ok/40 text-ok" : "bg-err/10 border border-err/30 text-err"
            }`}>
              <Trophy size={14} />
              {result.winner === 0 ? `${A.name} wins!` : `${B.name} wins!`}
            </div>
            <button onClick={onRematch}
              className="px-3 py-2 rounded-md text-[12px] font-medium text-gray-300 bg-bg-700 border border-bg-600 hover:border-accent/40">
              <RotateCcw size={12} className="inline mr-1" /> Rematch
            </button>
            <button onClick={onExit}
              className="px-4 py-2 rounded-md text-[12px] font-semibold text-white bg-accent hover:bg-accent-hover">
              Continue →
            </button>
          </>
        )}
      </div>
    </div>
  );
}
