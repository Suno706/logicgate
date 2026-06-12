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
  // Who is the active actor for this entry. For "hit"/"crit", it's the
  // attacker. For "dodge"/"counter", it's the defender (who just dodged
  // or just countered). For "shield", it's the defender whose shield
  // absorbed the hit. Null for narrative entries. The animator uses this
  // to pick which fighter lunges, recoils, etc.
  actor: 0 | 1 | null;
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
  const push = (text: string, kind: LogEntry["kind"], actor: 0 | 1 | null = null) =>
    log.push({ text, kind, hpA: Math.max(0, hpA), hpB: Math.max(0, hpB), shA, shB, actor });

  push(`${A.name} vs ${B.name} — fight!`, "info");

  // Speed decides who acts first each round; ties go to A (the challenger).
  const speedA = A.build.filter((g) => g === "NOT").length;
  const speedB = B.build.filter((g) => g === "NOT").length;

  const doAttack = (att: Fighter, defF: Fighter, attIsA: boolean): boolean => {
    const a = att.stats, d = defF.stats;
    const attackerSide: 0 | 1 = attIsA ? 0 : 1;
    const defenderSide: 0 | 1 = attIsA ? 1 : 0;
    const dodge = Math.max(0, d.dodge - a.aim);
    if (rng() < dodge) {
      push(`${defF.name} dodges ${att.name}'s attack!`, "dodge", defenderSide);
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
      push(`${defF.name}'s shield absorbs ${absorbed}!`, "shield", defenderSide);
    }
    push(
      isCrit
        ? `CRIT! ${att.name} smashes ${defF.name} for ${dmg}!`
        : `${att.name} hits ${defF.name} for ${dmg}.`,
      isCrit ? "crit" : "hit",
      attackerSide,
    );
    // Counter chance
    const defAlive = attIsA ? hpB > 0 : hpA > 0;
    if (defAlive && rng() < d.counter) {
      let cdmg = Math.max(1, Math.round(d.atk * 0.6 - a.armor));
      if (attIsA) hpA -= cdmg; else hpB -= cdmg;
      push(`${defF.name} counters for ${cdmg}!`, "counter", defenderSide);
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

/* ── animated battle ─────────────────────────────────────────────────
   Each LogEntry triggers an animation that lasts ENTRY_MS. The rAF loop
   tracks the elapsed time inside the current entry and interpolates
   each fighter's pose (translateX, rotation, flash tint, opacity) so
   the bots actually lunge, take hits, dodge, recoil. HP bars tween
   smoothly toward their target value rather than snapping. Particles
   spawn on hit/crit and decay with their own life timer. */

interface Pose {
  tx:    number;   // px offset from base position
  tilt:  number;   // deg
  flash: number;   // 0..1, red overlay
  dim:   number;   // 0..1 opacity multiplier (for defeat)
  scale: number;
}

interface Particle {
  id:    number;
  x:     number;   // px relative to arena
  y:     number;
  vx:    number;
  vy:    number;
  life:  number;   // seconds remaining
  ttl:   number;   // initial life
  color: string;
  size:  number;
}

const REST_POSE: Pose = { tx: 0, tilt: 0, flash: 0, dim: 1, scale: 1 };
const ENTRY_MS = 700;

// Easing
const easeOutQuad = (t: number) => 1 - (1 - t) * (1 - t);
const easeInQuad  = (t: number) => t * t;

let _pid = 1;
const newPid = () => _pid++;

function Battle({ A, B, onDone, onExit, onRematch }: {
  A: Fighter; B: Fighter;
  onDone: (winner: 0 | 1) => void;
  onExit: () => void;
  onRematch: () => void;
}) {
  // Computed once with a random seed; the log is the script we animate.
  const [result] = useState(() => runBattle(A, B, Math.floor(Math.random() * 1e9)));

  // Displayed HP (smoothly tweened) — separate from logical HP at each entry.
  const [hpA, setHpA] = useState(A.stats.hp);
  const [hpB, setHpB] = useState(B.stats.hp);
  const [shA, setShA] = useState(A.stats.shield);
  const [shB, setShB] = useState(B.stats.shield);

  const [poseA, setPoseA] = useState<Pose>(REST_POSE);
  const [poseB, setPoseB] = useState<Pose>(REST_POSE);

  const [shake,     setShake]     = useState(0);
  const [particles, setParticles] = useState<Particle[]>([]);
  const [logIndex,  setLogIndex]  = useState(0);
  const [finished,  setFinished]  = useState(false);
  const [skipped,   setSkipped]   = useState(false);

  // refs for the rAF loop to read without re-rendering churn
  const stateRef = useRef({
    idx:        0,
    entryStart: 0,
    lastT:      0,
    hpA:        A.stats.hp, hpB: B.stats.hp,
    shA:        A.stats.shield, shB: B.stats.shield,
    targetHpA:  A.stats.hp, targetHpB: B.stats.hp,
    targetShA:  A.stats.shield, targetShB: B.stats.shield,
    particles:  [] as Particle[],
    shake:      0,
    defeatedA:  false,
    defeatedB:  false,
  });
  const doneRef = useRef(false);

  // Spawn particles on hit/crit; colour + count varies by kind.
  function burst(side: 0 | 1, kind: "hit" | "crit" | "shield") {
    const xBase = side === 0 ? 150 : -150;     // toward defender
    const count = kind === "crit" ? 14 : kind === "hit" ? 8 : 5;
    const colour =
      kind === "crit"   ? "#fbbf24"
    : kind === "shield" ? "#60a5fa"
    :                     "#fb7185";
    const out: Particle[] = [];
    for (let i = 0; i < count; i++) {
      const ang = (Math.random() - 0.5) * Math.PI;
      const sp  = 120 + Math.random() * (kind === "crit" ? 220 : 120);
      out.push({
        id: newPid(),
        x: xBase + (Math.random() - 0.5) * 30,
        y: (Math.random() - 0.5) * 60,
        vx: Math.cos(ang) * sp * (side === 0 ? 1 : -1),
        vy: Math.sin(ang) * sp - 40,
        life: 0.55, ttl: 0.55,
        color: colour,
        size: kind === "crit" ? 5 : 3,
      });
    }
    stateRef.current.particles.push(...out);
  }

  // Apply an entry's pose/shake/particles at progress p (0..1).
  function applyAnim(entry: LogEntry, p: number) {
    const s = stateRef.current;
    let pA: Pose = { ...REST_POSE, dim: s.defeatedA ? 0.35 : 1, tilt: s.defeatedA ? -75 : 0 };
    let pB: Pose = { ...REST_POSE, dim: s.defeatedB ? 0.35 : 1, tilt: s.defeatedB ? 75 : 0 };

    // direction multipliers — bot 0 faces right, bot 1 faces left
    const dirA = 1, dirB = -1;
    // distance the attacker travels in one lunge, pixels
    const LUNGE = entry.kind === "crit" ? 110 : 80;
    const RECOIL = entry.kind === "crit" ? 32 : 18;

    if (entry.kind === "hit" || entry.kind === "crit") {
      const att = entry.actor === 0 ? pA : pB;
      const def = entry.actor === 0 ? pB : pA;
      const dir = entry.actor === 0 ? dirA : dirB;

      if (p < 0.45) {
        // wind up + lunge forward
        const t = easeOutQuad(p / 0.45);
        att.tx   = LUNGE * dir * t;
        att.tilt = (entry.actor === 0 ? -10 : 10) * t;
      } else if (p < 0.6) {
        // contact frame — attacker held at extension, defender recoils
        att.tx   = LUNGE * dir;
        att.tilt = (entry.actor === 0 ? -10 : 10);
        const tc = (p - 0.45) / 0.15;
        def.tx   = -RECOIL * dir * easeOutQuad(tc);
        def.flash = 1 - tc * 0.5;
        def.tilt  = (entry.actor === 0 ? 14 : -14) * tc;
        // Trigger burst + HP commit at the moment of contact (first frame in this window)
        if (s.lastT < s.entryStart + ENTRY_MS * 0.45) {
          burst(entry.actor as 0 | 1, entry.kind);
          if (entry.kind === "crit") s.shake = 1;
          s.targetHpA = entry.hpA;
          s.targetHpB = entry.hpB;
          s.targetShA = entry.shA;
          s.targetShB = entry.shB;
        }
      } else {
        // recover
        const t = (p - 0.6) / 0.4;
        att.tx   = LUNGE * dir * (1 - easeInQuad(t));
        att.tilt = (entry.actor === 0 ? -10 : 10) * (1 - t);
        def.tx   = -RECOIL * dir * (1 - t);
        def.flash = 0.5 * (1 - t);
        def.tilt  = (entry.actor === 0 ? 14 : -14) * (1 - t);
      }
    } else if (entry.kind === "dodge") {
      // The defender (actor) sidesteps; the attacker (1 - actor) lunges into empty air.
      const def = entry.actor === 0 ? pA : pB;
      const att = entry.actor === 0 ? pB : pA;
      const dirAtt = entry.actor === 0 ? dirB : dirA;
      const dirDef = entry.actor === 0 ? dirA : dirB;

      if (p < 0.45) {
        const t = easeOutQuad(p / 0.45);
        att.tx = 80 * dirAtt * t;
        att.tilt = (entry.actor === 0 ? 10 : -10) * t;
      } else if (p < 0.65) {
        att.tx = 80 * dirAtt;
        att.tilt = (entry.actor === 0 ? 10 : -10);
        const t = (p - 0.45) / 0.2;
        def.tx = -40 * dirDef * easeOutQuad(t);
        def.scale = 1 - 0.05 * t;
      } else {
        const t = (p - 0.65) / 0.35;
        att.tx = 80 * dirAtt * (1 - easeInQuad(t));
        att.tilt = (entry.actor === 0 ? 10 : -10) * (1 - t);
        def.tx = -40 * dirDef * (1 - t);
        def.scale = 1 - 0.05 * (1 - t);
      }
    } else if (entry.kind === "counter") {
      // Defender (actor) strikes back at the attacker (1 - actor).
      const ctr = entry.actor === 0 ? pA : pB;
      const opp = entry.actor === 0 ? pB : pA;
      const dirC = entry.actor === 0 ? dirA : dirB;
      if (p < 0.45) {
        const t = easeOutQuad(p / 0.45);
        ctr.tx = 70 * dirC * t;
      } else if (p < 0.6) {
        ctr.tx = 70 * dirC;
        const t = (p - 0.45) / 0.15;
        opp.tx = -16 * dirC * easeOutQuad(t);
        opp.flash = 1 - t * 0.4;
        if (s.lastT < s.entryStart + ENTRY_MS * 0.45) {
          burst(entry.actor as 0 | 1, "hit");
          s.targetHpA = entry.hpA;
          s.targetHpB = entry.hpB;
        }
      } else {
        const t = (p - 0.6) / 0.4;
        ctr.tx = 70 * dirC * (1 - easeInQuad(t));
        opp.tx = -16 * dirC * (1 - t);
        opp.flash = 0.4 * (1 - t);
      }
    } else if (entry.kind === "shield") {
      const def = entry.actor === 0 ? pA : pB;
      def.scale = 1.05;
      // Use flash as a "blue glow" channel — render layer interprets shield via colour swap below
      def.flash = 0.4;
      if (s.lastT < s.entryStart + ENTRY_MS * 0.2) {
        burst(entry.actor as 0 | 1, "shield");
        s.targetShA = entry.shA;
        s.targetShB = entry.shB;
      }
    } else if (entry.kind === "win") {
      // The loser tips over once (HP already at 0).
      if (entry.hpA <= 0 && !s.defeatedA) s.defeatedA = true;
      if (entry.hpB <= 0 && !s.defeatedB) s.defeatedB = true;
      pA.dim  = s.defeatedA ? 0.35 : 1;
      pA.tilt = s.defeatedA ? -75 : 0;
      pB.dim  = s.defeatedB ? 0.35 : 1;
      pB.tilt = s.defeatedB ? 75 : 0;
    }

    setPoseA(pA);
    setPoseB(pB);
  }

  // Skip to the end: instantly apply final HP + winner state.
  function skipToEnd() {
    setSkipped(true);
    setLogIndex(result.log.length - 1);
    const last = result.log[result.log.length - 1];
    stateRef.current.hpA = last.hpA;
    stateRef.current.hpB = last.hpB;
    stateRef.current.shA = last.shA;
    stateRef.current.shB = last.shB;
    stateRef.current.defeatedA = last.hpA <= 0;
    stateRef.current.defeatedB = last.hpB <= 0;
    setHpA(last.hpA); setHpB(last.hpB);
    setShA(last.shA); setShB(last.shB);
    setFinished(true);
  }

  // rAF loop driving the timeline
  useEffect(() => {
    if (skipped || finished) return;
    let raf = 0;
    function loop(now: number) {
      const s = stateRef.current;
      const dt = s.lastT ? Math.min(0.05, (now - s.lastT) / 1000) : 0;
      s.lastT = now;
      if (!s.entryStart) s.entryStart = now;

      const entry = result.log[s.idx];
      const elapsed = now - s.entryStart;
      const p = Math.min(1, elapsed / ENTRY_MS);

      applyAnim(entry, p);

      // Smoothly tween displayed HP / shield toward targets
      const tween = (cur: number, tgt: number) =>
        Math.abs(cur - tgt) < 0.5 ? tgt : cur + (tgt - cur) * Math.min(1, dt * 8);
      s.hpA = tween(s.hpA, s.targetHpA);
      s.hpB = tween(s.hpB, s.targetHpB);
      s.shA = tween(s.shA, s.targetShA);
      s.shB = tween(s.shB, s.targetShB);
      setHpA(Math.round(s.hpA));
      setHpB(Math.round(s.hpB));
      setShA(Math.round(s.shA));
      setShB(Math.round(s.shB));

      // Particles
      if (s.particles.length) {
        for (const pt of s.particles) {
          pt.x += pt.vx * dt;
          pt.y += pt.vy * dt;
          pt.vy += 380 * dt;        // gravity
          pt.life -= dt;
        }
        s.particles = s.particles.filter((pt) => pt.life > 0);
        setParticles([...s.particles]);
      } else if (particles.length) {
        setParticles([]);
      }

      // Screen-shake decay
      if (s.shake > 0) {
        s.shake = Math.max(0, s.shake - dt * 4);
        setShake(s.shake);
      } else if (shake !== 0) setShake(0);

      // Advance to next entry
      if (p >= 1) {
        if (s.idx >= result.log.length - 1) {
          setFinished(true);
          if (!doneRef.current) { doneRef.current = true; onDone(result.winner); }
          return;
        }
        s.idx += 1;
        setLogIndex(s.idx);
        s.entryStart = now;
      }
      raf = requestAnimationFrame(loop);
    }
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skipped, finished]);

  const hpPctA = Math.max(0, hpA / A.stats.hp) * 100;
  const hpPctB = Math.max(0, hpB / B.stats.hp) * 100;
  const shakeStyle = shake > 0 ? {
    transform: `translate(${(Math.random() - 0.5) * 10 * shake}px, ${(Math.random() - 0.5) * 10 * shake}px)`,
  } : undefined;

  return (
    <div className="max-w-3xl mx-auto w-full">
      {/* Health bars */}
      <div className="grid grid-cols-2 gap-4 mb-3">
        {[
          { f: A, pct: hpPctA, hp: hpA, sh: shA },
          { f: B, pct: hpPctB, hp: hpB, sh: shB },
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
              <div className={`h-full transition-[width] duration-150 ease-out ${
                pct > 50 ? "bg-ok" : pct > 25 ? "bg-warn" : "bg-err"
              }`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        ))}
      </div>

      {/* Arena — fixed-height stage with absolutely positioned fighters */}
      <div className="relative rounded-2xl border border-bg-600 bg-gradient-to-b from-bg-800/40 to-bg-900/60 overflow-hidden mb-3"
           style={{ height: 230, ...shakeStyle }}>
        {/* Floor line */}
        <div className="absolute left-0 right-0 bottom-12 h-px bg-bg-600/60" />

        {/* Fighter A — left side, faces right */}
        <FighterStage
          build={A.build}
          pose={poseA}
          side="left"
        />
        {/* Fighter B — right side, faces left */}
        <FighterStage
          build={B.build}
          pose={poseB}
          side="right"
        />

        {/* Particles */}
        {particles.map((pt) => (
          <div key={pt.id}
            className="absolute rounded-full pointer-events-none"
            style={{
              left: `calc(50% + ${pt.x}px)`,
              top:  `calc(50% + ${pt.y}px)`,
              width:  pt.size, height: pt.size,
              background: pt.color,
              opacity: Math.max(0, pt.life / pt.ttl),
              boxShadow: `0 0 ${pt.size * 2}px ${pt.color}`,
            }}
          />
        ))}

        {/* Round number / current action label */}
        <div className="absolute top-2 left-1/2 -translate-x-1/2 text-[10px] font-mono uppercase tracking-widest text-gray-500">
          {finished ? "FIGHT OVER" : `Round ${Math.floor(logIndex / 4) + 1}`}
        </div>
      </div>

      {/* Battle log — last 3 lines */}
      <div className="rounded-xl border border-bg-600 bg-bg-800/60 p-3 mb-3 min-h-[80px]">
        {result.log.slice(Math.max(0, logIndex - 2), logIndex + 1).map((e, i) => (
          <div key={`${logIndex}-${i}`} className={`text-[12px] py-0.5 ${
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
          <button onClick={skipToEnd}
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

/** A single fighter rendered with its current pose. Positioned absolutely
 *  within the arena container. */
function FighterStage({ build, pose, side }: {
  build: BotGate[]; pose: Pose; side: "left" | "right";
}) {
  const sideX = side === "left" ? "22%" : "78%";
  const facing = side === "left" ? 1 : -1;
  return (
    <div
      className="absolute bottom-6"
      style={{
        left: sideX,
        transform: `translate(calc(-50% + ${pose.tx}px), 0) rotate(${pose.tilt}deg) scale(${pose.scale})`,
        opacity: pose.dim,
        filter: pose.flash > 0
          ? `drop-shadow(0 0 ${10 * pose.flash}px rgba(248, 113, 113, ${pose.flash * 0.9})) saturate(${1 + pose.flash})`
          : undefined,
        transition: "transform 16ms linear, filter 80ms linear",
        transformOrigin: "bottom center",
      }}
    >
      <RobotFigure build={build} facing={facing as 1 | -1} />
    </div>
  );
}
