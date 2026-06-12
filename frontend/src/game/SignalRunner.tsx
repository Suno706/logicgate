import { useEffect, useRef, useState } from "react";
import { Heart, Trophy, Zap, RotateCcw, Play } from "lucide-react";

/**
 * Signal Runner — 2D endless runner where the player is a HIGH/LOW signal
 * threading through logic gates that fly in from the right. Each gate has
 * a "required input" (0 or 1). Match it with the lane you're in to pass;
 * miss it and lose HP. Power-ups give bonuses (VCC = +HP, CLOCK = slow-mo,
 * NOT = flips your lane automatically).
 *
 * Pure HTML5 Canvas + requestAnimationFrame. No backend round-trips —
 * inputs/scores are local. Works on touch (tap top/bottom of canvas to
 * switch lanes) and keyboard (arrow keys / WASD).
 *
 * Drawn in HTML <canvas>, not SVG, because the game loop renders ~60 fps
 * with ~30 entities; SVG re-render churn is wasteful here.
 */

type GateKind = "AND" | "OR" | "XOR" | "NAND" | "NOR" | "XNOR"
              | "VCC" | "CLOCK" | "NOT";

interface Entity {
  id: number;
  kind: GateKind;
  x: number;
  lane: 0 | 1;          // 0 = LOW (bottom), 1 = HIGH (top)
  requirement: 0 | 1;   // which lane you must be in
  hit: boolean;
}

const W = 800;   // game world width — scaled to render-target size
const H = 360;
const LANE_Y = [H * 0.7, H * 0.3];           // [low, high]
const PLAYER_X = 110;
const PLAYER_R = 18;
const GATE_R   = 28;
const SPAWN_MIN = 700;     // ms
const SPAWN_MAX = 1400;

const BEST_KEY = "logicgate.runner.best";

let _id = 1;
const nextId = () => _id++;

function randomGate(_elapsedSec: number): GateKind {
  const r = Math.random();
  // The elapsed-time parameter is currently unused but kept so we can
  // tune spawn weights by difficulty later without changing call sites.
  if (r < 0.04) return "VCC";
  if (r < 0.08) return "CLOCK";
  if (r < 0.13) return "NOT";
  // Logic gates — pick from the standard set
  const pool: GateKind[] = ["AND", "OR", "XOR", "NAND", "NOR", "XNOR"];
  return pool[Math.floor(Math.random() * pool.length)];
}

// What lane (0/1) the player must be in to safely pass through this gate.
function requirement(kind: GateKind): 0 | 1 {
  switch (kind) {
    // Gates that "want" HIGH on its input
    case "AND":  return 1;
    case "OR":   return 1;
    case "XNOR": return 1;
    // Gates that "want" LOW
    case "NAND": return 0;
    case "NOR":  return 0;
    case "XOR":  return 0;
    // Boosts / specials — any lane is safe
    default: return Math.random() < 0.5 ? 0 : 1;
  }
}

export function SignalRunner() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef   = useRef<HTMLDivElement | null>(null);

  const [state,  setState]  = useState<"idle" | "playing" | "over">("idle");
  const [hp,     setHp]     = useState(3);
  const [score,  setScore]  = useState(0);
  const [best,   setBest]   = useState<number>(() => {
    try { return Number(localStorage.getItem(BEST_KEY) || "0") || 0; }
    catch { return 0; }
  });

  // Mutable game state lives in refs so the rAF loop doesn't re-render
  // on every frame — only the HUD pieces above re-render when they change.
  const gameRef = useRef({
    lane:      1 as 0 | 1,
    hp:        3,
    score:     0,
    speed:     220,         // world units per second
    slowmoUntil: 0,
    entities:  [] as Entity[],
    lastSpawn: 0,
    lastTime:  0,
    startedAt: 0,
    flashUntil: 0,
    flashKind: "" as "boost" | "hit" | "",
  });

  function reset() {
    gameRef.current = {
      lane: 1, hp: 3, score: 0, speed: 220,
      slowmoUntil: 0, entities: [], lastSpawn: 0,
      lastTime: 0, startedAt: performance.now(),
      flashUntil: 0, flashKind: "",
    };
    setHp(3); setScore(0);
  }

  function start() {
    reset();
    setState("playing");
  }

  // Switch the player's lane. Wrapped so both keyboard and touch can call it.
  function setLane(l: 0 | 1) {
    gameRef.current.lane = l;
  }

  // ── input wiring ───────────────────────────────────────────────────
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (state !== "playing") return;
      if (e.key === "ArrowUp"   || e.key === "w" || e.key === "W") setLane(1);
      if (e.key === "ArrowDown" || e.key === "s" || e.key === "S") setLane(0);
      if (e.key === " ")        setLane((gameRef.current.lane ? 0 : 1) as 0 | 1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state]);

  // Touch: tap top half = HIGH, bottom half = LOW
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    function onPointer(e: PointerEvent) {
      if (state !== "playing") return;
      const rect = wrap!.getBoundingClientRect();
      const y    = e.clientY - rect.top;
      setLane((y < rect.height / 2 ? 1 : 0) as 0 | 1);
    }
    wrap.addEventListener("pointerdown", onPointer);
    return () => wrap.removeEventListener("pointerdown", onPointer);
  }, [state]);

  // ── game loop ──────────────────────────────────────────────────────
  useEffect(() => {
    if (state !== "playing") return;
    let raf = 0;
    const ctx = canvasRef.current?.getContext("2d") ?? null;
    if (!ctx) return;

    function loop(now: number) {
      const g = gameRef.current;
      const dt = g.lastTime ? Math.min(0.05, (now - g.lastTime) / 1000) : 0;
      g.lastTime = now;

      const inSlowmo = now < g.slowmoUntil;
      const speedFactor = inSlowmo ? 0.45 : 1;
      const elapsed = (now - g.startedAt) / 1000;
      // Gentle difficulty curve — speed grows by 30 every 20 seconds.
      const baseSpeed = 220 + Math.floor(elapsed / 20) * 30;
      const speed = baseSpeed * speedFactor;
      g.speed = baseSpeed;

      // Spawn entities at randomised intervals.
      if (now - g.lastSpawn >
          (SPAWN_MIN + Math.random() * (SPAWN_MAX - SPAWN_MIN)) / speedFactor) {
        g.lastSpawn = now;
        const k = randomGate(elapsed);
        const lane: 0 | 1 = Math.random() < 0.5 ? 0 : 1;
        g.entities.push({
          id: nextId(),
          kind: k,
          x: W + GATE_R,
          lane,
          requirement: requirement(k),
          hit: false,
        });
      }

      // Advance entities and detect collisions.
      for (const e of g.entities) {
        e.x -= speed * dt;
        if (e.hit) continue;
        // Collision when entity x is within player x range and lanes overlap.
        if (e.x < PLAYER_X + PLAYER_R + GATE_R / 2 &&
            e.x > PLAYER_X - PLAYER_R - GATE_R / 2 &&
            e.lane === g.lane) {
          e.hit = true;
          // Score + power-up handling
          if (e.kind === "VCC") {
            g.hp = Math.min(g.hp + 1, 5);
            g.score += 50;
            g.flashKind = "boost"; g.flashUntil = now + 250;
          } else if (e.kind === "CLOCK") {
            g.slowmoUntil = now + 2500;
            g.score += 75;
            g.flashKind = "boost"; g.flashUntil = now + 250;
          } else if (e.kind === "NOT") {
            // Flip the player's lane automatically (intentional inversion)
            g.lane = (g.lane ? 0 : 1) as 0 | 1;
            g.score += 25;
            g.flashKind = "boost"; g.flashUntil = now + 200;
          } else {
            // Logic gate: required-input match check
            if (e.requirement === g.lane) {
              g.score += 100;
              g.flashKind = "boost"; g.flashUntil = now + 150;
            } else {
              g.hp -= 1;
              g.score = Math.max(0, g.score - 25);
              g.flashKind = "hit"; g.flashUntil = now + 300;
            }
          }
          // Sync HUD
          setHp(g.hp); setScore(g.score);
          if (g.hp <= 0) {
            setState("over");
            setBest((b) => {
              const ns = Math.max(b, g.score);
              try { localStorage.setItem(BEST_KEY, String(ns)); } catch { /* */ }
              return ns;
            });
          }
        }
      }
      // Drop offscreen
      g.entities = g.entities.filter((e) => e.x > -GATE_R * 2);

      render(ctx!, g, now);
      raf = requestAnimationFrame(loop);
    }

    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  // ── render ─────────────────────────────────────────────────────────
  function render(ctx: CanvasRenderingContext2D, g: typeof gameRef.current, now: number) {
    const c   = ctx.canvas;
    const dpr = window.devicePixelRatio || 1;
    if (c.width !== W * dpr || c.height !== H * dpr) {
      c.width  = W * dpr;
      c.height = H * dpr;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    // Background
    ctx.fillStyle = "#0f1117";
    ctx.fillRect(0, 0, W, H);

    // Lane bands
    ctx.fillStyle = "#1c1f27";
    ctx.fillRect(0, LANE_Y[1] - 40, W, 80);   // high lane band
    ctx.fillStyle = "#16181f";
    ctx.fillRect(0, LANE_Y[0] - 40, W, 80);   // low lane band

    // Mid-line
    ctx.strokeStyle = "#262932";
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.moveTo(0, H / 2);  ctx.lineTo(W, H / 2);
    ctx.stroke();

    // Lane labels
    ctx.fillStyle = "#6a6757";
    ctx.font = "12px 'JetBrains Mono', monospace";
    ctx.fillText("HIGH (1)", 8, LANE_Y[1] - 22);
    ctx.fillText("LOW  (0)", 8, LANE_Y[0] - 22);

    // Slow-mo tint
    if (now < g.slowmoUntil) {
      ctx.fillStyle = "rgba(45, 212, 191, 0.06)";
      ctx.fillRect(0, 0, W, H);
    }

    // Entities
    for (const e of g.entities) {
      const y = LANE_Y[e.lane];
      drawGate(ctx, e.x, y, e.kind, e.requirement, e.hit);
    }

    // Player
    const px = PLAYER_X;
    const py = LANE_Y[g.lane];
    const flash = now < g.flashUntil;
    ctx.fillStyle =
      flash && g.flashKind === "hit"   ? "#fb7185"
    : flash && g.flashKind === "boost" ? "#34d399"
    :                                    "#2dd4bf";
    ctx.beginPath();
    ctx.arc(px, py, PLAYER_R, 0, Math.PI * 2);
    ctx.fill();
    // Inner state digit
    ctx.fillStyle = "#0f1117";
    ctx.font      = "bold 18px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(g.lane), px, py + 1);
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
  }

  function drawGate(
    ctx: CanvasRenderingContext2D,
    x: number, y: number,
    kind: GateKind,
    req: 0 | 1,
    hit: boolean,
  ) {
    const isBoost = kind === "VCC" || kind === "CLOCK" || kind === "NOT";
    const colourMap: Record<GateKind, string> = {
      AND:  "#818cf8", OR:   "#818cf8", XNOR: "#818cf8",
      NAND: "#fbbf24", NOR:  "#fbbf24", XOR:  "#fbbf24",
      VCC:  "#34d399", CLOCK: "#2dd4bf", NOT:  "#a78bfa",
    };
    const stroke = colourMap[kind];
    const fill   = hit ? "rgba(80,80,80,0.2)" : "rgba(34,38,49,0.85)";

    ctx.beginPath();
    ctx.arc(x, y, GATE_R, 0, Math.PI * 2);
    ctx.fillStyle   = fill;
    ctx.fill();
    ctx.strokeStyle = stroke;
    ctx.lineWidth   = 2.5;
    ctx.stroke();

    // Gate kind label
    ctx.fillStyle    = stroke;
    ctx.font         = "bold 12px 'JetBrains Mono', monospace";
    ctx.textAlign    = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(kind, x, y - 2);

    // Required input indicator below — only for logic gates
    if (!isBoost) {
      ctx.fillStyle = "#8a8675";
      ctx.font      = "10px 'JetBrains Mono', monospace";
      ctx.fillText(`need ${req}`, x, y + 14);
    }
    ctx.textAlign    = "left";
    ctx.textBaseline = "alphabetic";
  }

  // ── HUD ────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col p-3 md:p-5 gap-3"
         style={{ minHeight: "calc(100vh - 3rem)" }}>

      <div className="flex items-center gap-2 flex-wrap">
        <Stat icon={<Heart size={14} />}  label="HP"    value={"♥".repeat(hp) || "·"} colour="text-err" />
        <Stat icon={<Trophy size={14} />} label="Score" value={String(score)} />
        <Stat icon={<Zap size={14} />}    label="Best"  value={String(best)} colour="text-accent" />
      </div>

      <div ref={wrapRef}
           className="flex-1 min-h-0 relative rounded-xl border border-bg-600 bg-bg-800/60 overflow-hidden select-none">
        <canvas
          ref={canvasRef}
          style={{ width: "100%", height: "100%", display: "block", touchAction: "none" }}
        />

        {/* Tap zones overlay — only when playing, so splash screens are not blocked. */}
        {state === "playing" && (
          <div className="absolute inset-0 grid grid-rows-2 pointer-events-none md:hidden">
            <div className="border-b border-bg-600/40 flex items-start justify-end p-2 text-[10px] text-gray-500">
              tap top = HIGH
            </div>
            <div className="flex items-end justify-end p-2 text-[10px] text-gray-500">
              tap bottom = LOW
            </div>
          </div>
        )}

        {state === "idle" && (
          <Splash
            title="Signal Runner"
            body={
              <div className="space-y-2">
                <p>Race through logic gates. Match the gate's required input by switching lanes.</p>
                <p className="text-gray-500 text-[12px]">
                  <span className="text-accent">↑ / W</span> = HIGH lane ·
                  <span className="text-accent"> ↓ / S</span> = LOW lane ·
                  <span className="text-accent"> Space</span> = flip · on phone, tap top/bottom of the board.
                </p>
                <p className="text-gray-500 text-[12px]">
                  <span className="text-ok">VCC</span> = +HP ·
                  <span className="text-accent ml-1">CLOCK</span> = slow-mo ·
                  <span className="text-violet-400 ml-1">NOT</span> = auto-flip.
                </p>
              </div>
            }
            cta={<><Play size={14} /> Start run</>}
            onCta={start}
          />
        )}

        {state === "over" && (
          <Splash
            title="Signal lost"
            body={
              <>
                Final score: <span className="text-accent font-bold">{score}</span>
                {score >= best && score > 0 && (
                  <div className="mt-1 text-warn">⚡ New best!</div>
                )}
              </>
            }
            cta={<><RotateCcw size={14} /> Try again</>}
            onCta={start}
          />
        )}
      </div>
    </div>
  );
}

// ── Subcomponents ─────────────────────────────────────────────────────

function Stat({ icon, label, value, colour }: {
  icon: React.ReactNode; label: string; value: string; colour?: string;
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-bg-800/70 border border-bg-600">
      <span className={colour || "text-gray-400"}>{icon}</span>
      <span className="text-[10px] uppercase tracking-wider text-gray-500">{label}</span>
      <span className={`text-[14px] font-semibold tabular-nums ${colour || "text-gray-100"}`}>
        {value}
      </span>
    </div>
  );
}

function Splash({ title, body, cta, onCta }: {
  title: string; body: React.ReactNode;
  cta: React.ReactNode; onCta: () => void;
}) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center text-center gap-3 px-5 bg-bg-900/80 backdrop-blur-sm">
      <h2 className="text-[22px] font-bold text-gray-100">{title}</h2>
      <div className="text-[13px] text-gray-300 max-w-md leading-relaxed">
        {body}
      </div>
      <button onClick={onCta}
        className="mt-1 px-5 py-2.5 rounded-lg bg-accent hover:bg-accent-hover text-white text-[14px] font-semibold inline-flex items-center gap-2 transition-colors">
        {cta}
      </button>
    </div>
  );
}
