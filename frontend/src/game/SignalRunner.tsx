import { useEffect, useRef, useState } from "react";
import {
  Heart, Trophy, Zap, RotateCcw, Play, Pause, ChevronUp, ChevronDown,
} from "lucide-react";

/* ───────────────────────────────────────────────────────────────────────
   Signal Runner
   ──────────────────────────────────────────────────────────────────────

   The player is a logic signal — a glowing pulse with a value of 0 or 1 —
   moving through a circuit at a fixed horizontal position. Gates scroll
   in from the right; each one specifies which value it lets through.
   Match the gate's requirement with your current lane and you pass it
   for points; mismatch and you lose HP.

   Design notes that matter:
     - Game state lives in a ref so the animation loop doesn't trigger a
       React re-render every frame. The HUD reads from React state which
       we update only when a value the player will actually see has
       changed (score, hp, combo).
     - The world is rendered at a fixed virtual resolution (WORLD_W ×
       WORLD_H). The canvas backing-store is sized for devicePixelRatio
       so it stays crisp on high-DPI screens; CSS size still matches the
       container so the layout flows naturally.
     - The combo system is what makes the scoring loop interesting: each
       consecutive matched gate increments a multiplier (capped at 5×).
       A single miss resets the combo. Wave announcements every ~20s
       give the runner a sense of escalation that pure speed scaling
       doesn't.

   What's intentionally NOT here:
     - Sound (would need user-gesture unlock + asset hosting; not worth
       it for a tiny side game).
     - Server leaderboards (best score is per-device localStorage; if
       this becomes popular we revisit).
   ─────────────────────────────────────────────────────────────────── */


/* ── world geometry ──────────────────────────────────────────────────── */

const WORLD_W   = 800;
const WORLD_H   = 360;
const FLOOR_Y   = WORLD_H * 0.7;       // LOW lane vertical centre
const ROOF_Y    = WORLD_H * 0.3;       // HIGH lane vertical centre
const PLAYER_X  = 120;
const PLAYER_R  = 20;
const GATE_R    = 30;

/* ── tuning ──────────────────────────────────────────────────────────── */

const BASE_SPEED       = 220;          // world units / second
const SPEED_PER_WAVE   = 30;           // +speed each new wave
const WAVE_DURATION    = 20;           // seconds per wave
const SPAWN_MIN_MS     = 700;
const SPAWN_MAX_MS     = 1400;
const COMBO_MAX        = 5;
const SLOWMO_DURATION  = 2500;         // ms
const SCORE_BASE       = 100;
const SCORE_BOOST      = 50;
const SCORE_MISS_LOSS  = 25;

/* ── inputs ──────────────────────────────────────────────────────────── */

const BEST_SCORE_KEY = "logicgate.runner.best";
const BEST_COMBO_KEY = "logicgate.runner.bestcombo";

/* ── types ───────────────────────────────────────────────────────────── */

type GateKind =
  | "AND" | "OR" | "XOR" | "NAND" | "NOR" | "XNOR"   // logic obstacles
  | "VCC" | "CLOCK" | "NOT";                          // power-ups

type EntityRole = "logic" | "boost";

interface Entity {
  id:        number;
  kind:      GateKind;
  role:      EntityRole;
  x:         number;
  lane:      0 | 1;
  needs:     0 | 1;      // only meaningful for logic gates
  spent:     boolean;    // has the player already interacted with it
}

interface Particle {
  x:       number;
  y:       number;
  vx:      number;
  vy:      number;
  life:    number;       // seconds remaining
  ttl:     number;       // initial life
  color:   string;
  size:    number;
}

interface FloatingText {
  x:        number;
  y:        number;
  text:     string;
  life:     number;
  ttl:      number;
  color:    string;
}

interface WaveLabel {
  text:  string;
  life:  number;
  ttl:   number;
}

type Phase = "idle" | "playing" | "paused" | "over";

/* ── helpers ─────────────────────────────────────────────────────────── */

let _entityId = 1;
const nextEntityId = () => _entityId++;

const clamp = (n: number, lo: number, hi: number) =>
  n < lo ? lo : n > hi ? hi : n;

const readNumber = (key: string): number => {
  try { return Number(localStorage.getItem(key) || "0") || 0; }
  catch { return 0; }
};

const writeNumber = (key: string, n: number) => {
  try { localStorage.setItem(key, String(n)); } catch { /* localStorage unavailable */ }
};

/** Which lane is "safe" for this gate? For boost gates the answer is
 *  "either" — they pick a random lane so the player has to position. */
function laneRequirement(kind: GateKind): 0 | 1 {
  switch (kind) {
    case "AND": case "OR": case "XNOR":  return 1;
    case "NAND": case "NOR": case "XOR": return 0;
    default: return Math.random() < 0.5 ? 0 : 1;
  }
}

function roleOf(kind: GateKind): EntityRole {
  return (kind === "VCC" || kind === "CLOCK" || kind === "NOT") ? "boost" : "logic";
}

/** Spawn weights tuned so boosts feel like rewards (~15% of total) without
 *  crowding out the logic gates that drive the core mechanic. */
function rollGate(): GateKind {
  const r = Math.random();
  if (r < 0.04) return "VCC";
  if (r < 0.08) return "CLOCK";
  if (r < 0.13) return "NOT";
  const logic: GateKind[] = ["AND", "OR", "XOR", "NAND", "NOR", "XNOR"];
  return logic[Math.floor(Math.random() * logic.length)];
}


/* ── component ──────────────────────────────────────────────────────── */

export function SignalRunner() {

  /* refs that drive the rAF loop without triggering re-renders */
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stageRef  = useRef<HTMLDivElement   | null>(null);

  /* HUD state — re-rendered only when the numbers the user sees change */
  const [hp,        setHp]        = useState(3);
  const [score,     setScore]     = useState(0);
  const [combo,     setCombo]     = useState(0);
  const [phase,     setPhase]     = useState<Phase>("idle");
  const [waveLabel, setWaveLabel] = useState<string | null>(null);
  const [bestScore, setBestScore] = useState<number>(() => readNumber(BEST_SCORE_KEY));
  const [bestCombo, setBestCombo] = useState<number>(() => readNumber(BEST_COMBO_KEY));

  /* mutable game state */
  const game = useRef({
    lane:         1 as 0 | 1,
    hp:           3,
    score:        0,
    combo:        0,
    bestCombo:    0,
    wave:         1,
    waveTimer:    0,             // seconds since last wave change
    slowmoUntil:  0,             // performance.now() ms
    flash:        0,             // overlay tint, decays to 0
    flashKind:    "none" as "good" | "bad" | "shock" | "none",
    shake:        0,             // 0..1, decays
    entities:     [] as Entity[],
    particles:    [] as Particle[],
    trail:        [] as Particle[],
    floaters:     [] as FloatingText[],
    waveLabels:   [] as WaveLabel[],
    lastSpawn:    0,             // performance.now()
    lastTime:     0,
    startedAt:    0,
  });

  /* ── lifecycle ─────────────────────────────────────────────────── */

  function startNewRun() {
    const g = game.current;
    g.lane = 1; g.hp = 3; g.score = 0; g.combo = 0; g.bestCombo = 0;
    g.wave = 1; g.waveTimer = 0;
    g.slowmoUntil = 0;
    g.flash = 0; g.flashKind = "none"; g.shake = 0;
    g.entities = []; g.particles = []; g.trail = []; g.floaters = [];
    g.waveLabels = [{ text: "WAVE 1 — GET READY", life: 1.6, ttl: 1.6 }];
    g.lastSpawn = 0; g.lastTime = 0; g.startedAt = performance.now();
    setHp(3); setScore(0); setCombo(0); setPhase("playing"); setWaveLabel(null);
  }

  function togglePause() {
    setPhase((p) => p === "playing" ? "paused" : p === "paused" ? "playing" : p);
  }

  function setLane(l: 0 | 1) {
    game.current.lane = l;
  }

  /* ── input wiring ──────────────────────────────────────────────── */

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (phase === "idle" || phase === "over") {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          startNewRun();
        }
        return;
      }
      if (e.key === "p" || e.key === "P" || e.key === "Escape") {
        togglePause();
        return;
      }
      if (phase !== "playing") return;
      if (e.key === "ArrowUp"   || e.key === "w" || e.key === "W") setLane(1);
      if (e.key === "ArrowDown" || e.key === "s" || e.key === "S") setLane(0);
      if (e.key === " ") {
        e.preventDefault();
        setLane((game.current.lane ? 0 : 1) as 0 | 1);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase]);

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    function onPointer(e: PointerEvent) {
      if (phase !== "playing") return;
      const rect = el!.getBoundingClientRect();
      const yFrac = (e.clientY - rect.top) / rect.height;
      setLane((yFrac < 0.5 ? 1 : 0) as 0 | 1);
    }
    el.addEventListener("pointerdown", onPointer);
    return () => el.removeEventListener("pointerdown", onPointer);
  }, [phase]);

  /* ── animation loop ────────────────────────────────────────────── */

  useEffect(() => {
    if (phase !== "playing") return;
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx) return;
    let raf = 0;

    function loop(now: number) {
      const g = game.current;
      const dt = g.lastTime ? Math.min(0.05, (now - g.lastTime) / 1000) : 0;
      g.lastTime = now;

      stepGame(g, now, dt);
      drawWorld(ctx!, g, now);
      syncHud(g);

      if (g.hp <= 0) {
        finishRun(g);
        return;
      }
      raf = requestAnimationFrame(loop);
    }
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  /** Cheap rate-limited HUD update — react only fires a re-render when a
   *  visible number changes, not every frame. */
  function syncHud(g: typeof game.current) {
    if (g.hp     !== hp)    setHp(g.hp);
    if (g.score  !== score) setScore(g.score);
    if (g.combo  !== combo) setCombo(g.combo);
    if (g.waveLabels[0]) {
      const lbl = g.waveLabels[0].text;
      if (lbl !== waveLabel) setWaveLabel(lbl);
    } else if (waveLabel) {
      setWaveLabel(null);
    }
  }

  function finishRun(g: typeof game.current) {
    setHp(0); setScore(g.score); setCombo(g.combo);
    setPhase("over");
    if (g.score > bestScore) {
      setBestScore(g.score);
      writeNumber(BEST_SCORE_KEY, g.score);
    }
    if (g.bestCombo > bestCombo) {
      setBestCombo(g.bestCombo);
      writeNumber(BEST_COMBO_KEY, g.bestCombo);
    }
  }

  /* ── render ────────────────────────────────────────────────────── */

  return (
    <div className="flex flex-col gap-3 p-3 md:p-5"
         style={{ minHeight: "calc(100vh - 3rem)" }}>

      <RunnerHud
        hp={hp} score={score} combo={combo}
        bestScore={bestScore} bestCombo={bestCombo}
        phase={phase}
        onPauseToggle={togglePause}
      />

      <div ref={stageRef}
           className="flex-1 min-h-0 relative rounded-2xl border border-bg-600 bg-bg-900 overflow-hidden select-none shadow-inner">

        <canvas
          ref={canvasRef}
          style={{ width: "100%", height: "100%", display: "block",
                   touchAction: "none" }}
        />

        {waveLabel && phase === "playing" && (
          <div className="absolute top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-accent/15 border border-accent/40 text-accent text-[11px] font-semibold tracking-wider uppercase pointer-events-none animate-pulse">
            {waveLabel}
          </div>
        )}

        {/* Lane tap-zone affordances — visible only while playing, mobile only */}
        {phase === "playing" && (
          <div className="absolute inset-0 grid grid-rows-2 pointer-events-none md:hidden">
            <div className="flex items-start justify-center pt-2 text-[10px] text-gray-500 gap-1">
              <ChevronUp size={11} /> tap = HIGH lane
            </div>
            <div className="flex items-end justify-center pb-2 text-[10px] text-gray-500 gap-1">
              <ChevronDown size={11} /> tap = LOW lane
            </div>
          </div>
        )}

        {phase === "idle" && (
          <Splash
            title="Signal Runner"
            body={<IdleHelp />}
            cta={<><Play size={14} /> Start run</>}
            onCta={startNewRun}
          />
        )}

        {phase === "paused" && (
          <Splash
            title="Paused"
            body="Catch your breath."
            cta={<><Play size={14} /> Resume</>}
            onCta={togglePause}
          />
        )}

        {phase === "over" && (
          <Splash
            title="Signal lost"
            body={<OverRecap score={score} combo={combo} bestScore={bestScore} />}
            cta={<><RotateCcw size={14} /> Run again</>}
            onCta={startNewRun}
          />
        )}
      </div>
    </div>
  );
}


/* ─────────────────────────────────────────────────────────────────────
   Step — pure-ish game logic (mutates g; no React calls).
   ─────────────────────────────────────────────────────────────────── */

function stepGame(g: any, now: number, dt: number) {
  const inSlowmo  = now < g.slowmoUntil;
  const slowScale = inSlowmo ? 0.45 : 1;
  const speed     = (BASE_SPEED + (g.wave - 1) * SPEED_PER_WAVE) * slowScale;

  /* ── advance the wave clock ─────────────────────────────────── */
  g.waveTimer += dt * slowScale;
  if (g.waveTimer >= WAVE_DURATION) {
    g.waveTimer = 0;
    g.wave += 1;
    g.waveLabels.push({
      text: `WAVE ${g.wave} — FASTER`,
      life: 1.6, ttl: 1.6,
    });
  }

  /* ── spawn new entities ────────────────────────────────────── */
  const spawnInterval = (SPAWN_MIN_MS + Math.random() * (SPAWN_MAX_MS - SPAWN_MIN_MS)) / slowScale;
  if (now - g.lastSpawn > spawnInterval) {
    g.lastSpawn = now;
    const kind = rollGate();
    g.entities.push({
      id:    nextEntityId(),
      kind,
      role:  roleOf(kind),
      x:     WORLD_W + GATE_R,
      lane:  Math.random() < 0.5 ? 0 : 1,
      needs: laneRequirement(kind),
      spent: false,
    });
  }

  /* ── update entities, detect player interactions ─────────────── */
  for (const e of g.entities) {
    e.x -= speed * dt;
    if (e.spent) continue;
    const overlapping =
      e.x < PLAYER_X + PLAYER_R + GATE_R * 0.55 &&
      e.x > PLAYER_X - PLAYER_R - GATE_R * 0.55 &&
      e.lane === g.lane;
    if (overlapping) interact(g, e);
  }
  g.entities = g.entities.filter((e: Entity) => e.x > -GATE_R * 2);

  /* ── trail particles behind player ───────────────────────────── */
  const py = g.lane === 1 ? ROOF_Y : FLOOR_Y;
  g.trail.push({
    x:     PLAYER_X - PLAYER_R * 0.5,
    y:     py,
    vx:    -60,
    vy:    (Math.random() - 0.5) * 30,
    life:  0.45, ttl: 0.45,
    color: g.lane === 1 ? "#2dd4bf" : "#5eead4",
    size:  PLAYER_R * 0.7,
  });

  /* ── decay particles / floaters / wave labels ────────────────── */
  for (const p of g.trail)    { p.x += p.vx * dt; p.y += p.vy * dt; p.life -= dt; }
  for (const p of g.particles){ p.x += p.vx * dt; p.y += p.vy * dt; p.vy += 250 * dt; p.life -= dt; }
  for (const f of g.floaters) { f.y -= 60 * dt; f.life -= dt; }
  for (const l of g.waveLabels) { l.life -= dt; }
  g.trail      = g.trail.filter((p: Particle) => p.life > 0);
  g.particles  = g.particles.filter((p: Particle) => p.life > 0);
  g.floaters   = g.floaters.filter((f: FloatingText) => f.life > 0);
  g.waveLabels = g.waveLabels.filter((l: WaveLabel) => l.life > 0);

  /* ── flash / shake decay ─────────────────────────────────────── */
  if (g.flash > 0) g.flash = Math.max(0, g.flash - dt * 3);
  if (g.shake > 0) g.shake = Math.max(0, g.shake - dt * 4);
}


/** Handle the moment the player touches a gate. */
function interact(g: any, e: Entity) {
  e.spent = true;
  const px = PLAYER_X, py = e.lane === 1 ? ROOF_Y : FLOOR_Y;

  if (e.kind === "VCC") {
    g.hp = Math.min(g.hp + 1, 5);
    pushFloat(g, px, py, "+1 ♥", "#34d399");
    addScore(g, SCORE_BOOST);
    burst(g, px, py, "#34d399", 12);
    flashGood(g);
    return;
  }
  if (e.kind === "CLOCK") {
    g.slowmoUntil = performance.now() + SLOWMO_DURATION;
    pushFloat(g, px, py, "SLOW-MO", "#2dd4bf");
    addScore(g, SCORE_BOOST + 25);
    burst(g, px, py, "#2dd4bf", 12);
    flashGood(g);
    return;
  }
  if (e.kind === "NOT") {
    g.lane = (g.lane ? 0 : 1) as 0 | 1;
    pushFloat(g, px, py, "FLIP", "#a78bfa");
    addScore(g, 25);
    burst(g, px, py, "#a78bfa", 10);
    return;
  }

  /* logic gates: match or miss */
  if (e.needs === g.lane) {
    g.combo = Math.min(g.combo + 1, COMBO_MAX);
    if (g.combo > g.bestCombo) g.bestCombo = g.combo;
    const points = SCORE_BASE * g.combo;
    addScore(g, points);
    pushFloat(g, px, py, `+${points}`, "#a5f3fc");
    burst(g, px, py, "#67e8f9", 8);
    flashGood(g);
  } else {
    g.combo = 0;
    g.hp -= 1;
    g.score = Math.max(0, g.score - SCORE_MISS_LOSS);
    pushFloat(g, px, py, "MISS", "#fb7185");
    burst(g, px, py, "#fb7185", 14);
    flashBad(g);
    g.shake = 1;
  }
}

function pushFloat(g: any, x: number, y: number, text: string, color: string) {
  g.floaters.push({ x, y, text, life: 0.9, ttl: 0.9, color });
}

function addScore(g: any, n: number) { g.score += n; }

function flashGood(g: any) { g.flash = 0.35; g.flashKind = "good"; }
function flashBad(g: any)  { g.flash = 0.6;  g.flashKind = "bad";  }

function burst(g: any, x: number, y: number, color: string, count: number) {
  for (let i = 0; i < count; i++) {
    const ang = Math.random() * Math.PI * 2;
    const speed = 60 + Math.random() * 240;
    g.particles.push({
      x, y,
      vx: Math.cos(ang) * speed,
      vy: Math.sin(ang) * speed - 50,
      life:  0.6 + Math.random() * 0.2,
      ttl:   0.8,
      color,
      size:  2 + Math.random() * 2,
    });
  }
}


/* ─────────────────────────────────────────────────────────────────────
   Render — pure draw, no game-state mutation.
   ─────────────────────────────────────────────────────────────────── */

function drawWorld(ctx: CanvasRenderingContext2D, g: any, now: number) {
  const canvas = ctx.canvas;
  const dpr    = window.devicePixelRatio || 1;
  const cssW   = canvas.clientWidth  || WORLD_W;
  const cssH   = canvas.clientHeight || WORLD_H;
  const wantW  = Math.round(cssW * dpr);
  const wantH  = Math.round(cssH * dpr);
  if (canvas.width !== wantW || canvas.height !== wantH) {
    canvas.width  = wantW;
    canvas.height = wantH;
  }
  const sx = cssW / WORLD_W;
  const sy = cssH / WORLD_H;
  ctx.setTransform(dpr * sx, 0, 0, dpr * sy, 0, 0);

  /* screen-shake offset */
  if (g.shake > 0) {
    ctx.translate(
      (Math.random() - 0.5) * 10 * g.shake,
      (Math.random() - 0.5) * 10 * g.shake,
    );
  }

  drawBackground(ctx, g, now);
  drawLanes(ctx);
  drawEntities(ctx, g);
  drawTrail(ctx, g);
  drawPlayer(ctx, g, now);
  drawParticles(ctx, g);
  drawFloaters(ctx, g);
  drawFlashOverlay(ctx, g);
}

function drawBackground(ctx: CanvasRenderingContext2D, g: any, now: number) {
  /* solid dark wash + slowly drifting grid for a sense of motion */
  ctx.fillStyle = "#0f1117";
  ctx.fillRect(0, 0, WORLD_W, WORLD_H);

  const speed = (BASE_SPEED + (g.wave - 1) * SPEED_PER_WAVE) * 0.5;
  const offset = -((now / 1000) * speed) % 60;
  ctx.strokeStyle = "#1c1f27";
  ctx.lineWidth   = 1;
  ctx.beginPath();
  for (let x = offset; x < WORLD_W; x += 60) {
    ctx.moveTo(x, 0);
    ctx.lineTo(x, WORLD_H);
  }
  for (let y = 0; y < WORLD_H; y += 40) {
    ctx.moveTo(0, y);
    ctx.lineTo(WORLD_W, y);
  }
  ctx.stroke();

  /* slow-mo tint */
  if (now < g.slowmoUntil) {
    ctx.fillStyle = "rgba(45, 212, 191, 0.07)";
    ctx.fillRect(0, 0, WORLD_W, WORLD_H);
  }
}

function drawLanes(ctx: CanvasRenderingContext2D) {
  /* lane bands with subtle tint so the active vertical region reads */
  const bandH = 90;
  ctx.fillStyle = "rgba(45, 212, 191, 0.04)";
  ctx.fillRect(0, ROOF_Y - bandH / 2, WORLD_W, bandH);
  ctx.fillStyle = "rgba(45, 212, 191, 0.02)";
  ctx.fillRect(0, FLOOR_Y - bandH / 2, WORLD_W, bandH);

  /* lane labels */
  ctx.fillStyle = "#4a4f63";
  ctx.font      = "11px 'JetBrains Mono', monospace";
  ctx.fillText("HIGH · 1", 12, ROOF_Y - bandH / 2 + 16);
  ctx.fillText("LOW  · 0", 12, FLOOR_Y - bandH / 2 + 16);

  /* dotted midline */
  ctx.strokeStyle = "#262932";
  ctx.lineWidth   = 1;
  ctx.setLineDash([6, 8]);
  ctx.beginPath();
  ctx.moveTo(0, WORLD_H / 2); ctx.lineTo(WORLD_W, WORLD_H / 2);
  ctx.stroke();
  ctx.setLineDash([]);
}

const ENTITY_COLOR: Record<GateKind, string> = {
  AND:  "#818cf8", OR:   "#818cf8", XNOR: "#818cf8",      // want HIGH — indigo
  NAND: "#fbbf24", NOR:  "#fbbf24", XOR:  "#fbbf24",      // want LOW  — amber
  VCC:  "#34d399",                                        // heal
  CLOCK: "#2dd4bf",                                       // slow-mo
  NOT:  "#a78bfa",                                        // flip
};

function drawEntities(ctx: CanvasRenderingContext2D, g: any) {
  for (const e of g.entities) {
    const y = e.lane === 1 ? ROOF_Y : FLOOR_Y;
    drawEntity(ctx, e, y);
  }
}

function drawEntity(ctx: CanvasRenderingContext2D, e: Entity, y: number) {
  const color  = ENTITY_COLOR[e.kind];
  const isSpent = e.spent;
  const alpha   = isSpent ? 0.25 : 1;

  /* outer glow */
  ctx.save();
  ctx.globalAlpha = alpha * 0.45;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(e.x, y, GATE_R * 1.25, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  /* body */
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.fillStyle   = "#161922";
  ctx.beginPath();
  ctx.arc(e.x, y, GATE_R, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.lineWidth   = 2.5;
  ctx.stroke();

  /* label */
  ctx.fillStyle    = color;
  ctx.font         = "bold 13px 'JetBrains Mono', monospace";
  ctx.textAlign    = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(e.kind, e.x, y - 2);

  /* required-input pill below logic gates */
  if (e.role === "logic") {
    ctx.fillStyle = "#0f1117";
    ctx.beginPath();
    ctx.roundRect(e.x - 18, y + 12, 36, 14, 7);
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1;
    ctx.stroke();
    ctx.fillStyle    = color;
    ctx.font         = "10px 'JetBrains Mono', monospace";
    ctx.fillText(`need ${e.needs}`, e.x, y + 21);
  }

  ctx.textAlign    = "left";
  ctx.textBaseline = "alphabetic";
  ctx.restore();
}

function drawTrail(ctx: CanvasRenderingContext2D, g: any) {
  for (const p of g.trail) {
    const a = p.life / p.ttl;
    ctx.save();
    ctx.globalAlpha = a * 0.5;
    ctx.fillStyle   = p.color;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.size * a, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
}

function drawPlayer(ctx: CanvasRenderingContext2D, g: any, now: number) {
  const y = g.lane === 1 ? ROOF_Y : FLOOR_Y;
  /* subtle vertical bob keeps it feeling alive */
  const bob = Math.sin(now * 0.008) * 2;

  /* halo */
  ctx.save();
  ctx.globalAlpha = 0.5;
  ctx.fillStyle = "#2dd4bf";
  ctx.beginPath();
  ctx.arc(PLAYER_X, y + bob, PLAYER_R * 1.8, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  /* body */
  ctx.fillStyle = "#2dd4bf";
  ctx.beginPath();
  ctx.arc(PLAYER_X, y + bob, PLAYER_R, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = "#0f1117";
  ctx.lineWidth   = 2;
  ctx.stroke();

  /* state digit */
  ctx.fillStyle    = "#0f1117";
  ctx.font         = "bold 20px 'JetBrains Mono', monospace";
  ctx.textAlign    = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(String(g.lane), PLAYER_X, y + bob + 1);
  ctx.textAlign    = "left";
  ctx.textBaseline = "alphabetic";
}

function drawParticles(ctx: CanvasRenderingContext2D, g: any) {
  for (const p of g.particles) {
    const a = clamp(p.life / p.ttl, 0, 1);
    ctx.save();
    ctx.globalAlpha = a;
    ctx.fillStyle   = p.color;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
}

function drawFloaters(ctx: CanvasRenderingContext2D, g: any) {
  ctx.font         = "bold 14px 'JetBrains Mono', monospace";
  ctx.textAlign    = "center";
  ctx.textBaseline = "middle";
  for (const f of g.floaters) {
    const a = clamp(f.life / f.ttl, 0, 1);
    ctx.save();
    ctx.globalAlpha = a;
    ctx.fillStyle   = f.color;
    ctx.fillText(f.text, f.x, f.y);
    ctx.restore();
  }
  ctx.textAlign    = "left";
  ctx.textBaseline = "alphabetic";
}

function drawFlashOverlay(ctx: CanvasRenderingContext2D, g: any) {
  if (g.flash <= 0) return;
  const colour = g.flashKind === "bad" ? "248, 113, 113" : "52, 211, 153";
  ctx.fillStyle = `rgba(${colour}, ${g.flash * 0.18})`;
  ctx.fillRect(0, 0, WORLD_W, WORLD_H);
}


/* ─────────────────────────────────────────────────────────────────────
   HUD / splash sub-components.
   ─────────────────────────────────────────────────────────────────── */

function RunnerHud({
  hp, score, combo, bestScore, bestCombo, phase, onPauseToggle,
}: {
  hp: number; score: number; combo: number;
  bestScore: number; bestCombo: number;
  phase: Phase; onPauseToggle: () => void;
}) {
  const hearts = "♥".repeat(Math.max(0, hp)) || "·";
  const comboLabel = combo >= 2 ? `×${combo}` : "—";
  const comboHot   = combo >= 3;
  return (
    <div className="flex items-stretch gap-2 flex-wrap">
      <HudCell icon={<Heart size={14} />}  label="HP"
        value={hearts} colour="text-err" />
      <HudCell icon={<Trophy size={14} />} label="Score"
        value={String(score)} sub={bestScore > 0 ? `Best ${bestScore}` : undefined} />
      <HudCell icon={<Zap size={14} />}    label="Combo"
        value={comboLabel}
        colour={comboHot ? "text-warn" : "text-gray-100"}
        sub={bestCombo > 0 ? `Best ×${bestCombo}` : undefined} />
      {(phase === "playing" || phase === "paused") && (
        <button onClick={onPauseToggle}
          className="ml-auto px-3 rounded-md text-[12px] font-medium border border-bg-600 bg-bg-800/70 text-gray-300 hover:border-accent/40 hover:text-gray-100 transition-colors flex items-center gap-1.5"
          title="Pause (P)">
          {phase === "playing" ? <Pause size={13} /> : <Play size={13} />}
          {phase === "playing" ? "Pause" : "Resume"}
        </button>
      )}
    </div>
  );
}

function HudCell({ icon, label, value, sub, colour = "text-gray-100" }: {
  icon: React.ReactNode; label: string; value: string; sub?: string; colour?: string;
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-bg-800/70 border border-bg-600 min-w-[100px]">
      <span className="text-gray-400">{icon}</span>
      <div className="flex flex-col leading-tight">
        <span className="text-[10px] uppercase tracking-wider text-gray-500">{label}</span>
        <span className={`text-[14px] font-semibold tabular-nums ${colour}`}>
          {value}
        </span>
        {sub && (
          <span className="text-[9px] text-gray-600 tabular-nums">{sub}</span>
        )}
      </div>
    </div>
  );
}

function Splash({ title, body, cta, onCta }: {
  title: string; body: React.ReactNode;
  cta:   React.ReactNode; onCta: () => void;
}) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center text-center gap-3 px-5 bg-bg-900/85 backdrop-blur-sm">
      <h2 className="text-[22px] font-bold text-gray-100">{title}</h2>
      <div className="text-[13px] text-gray-300 max-w-md leading-relaxed">{body}</div>
      <button onClick={onCta}
        className="mt-1 px-5 py-2.5 rounded-lg bg-accent hover:bg-accent-hover text-white text-[14px] font-semibold inline-flex items-center gap-2 transition-colors">
        {cta}
      </button>
    </div>
  );
}

function IdleHelp() {
  return (
    <div className="space-y-2 text-left max-w-sm">
      <p>You're a logic signal. Switch lanes so the gate's required input
        matches your current state, or take damage.</p>
      <ul className="text-gray-500 text-[12px] space-y-0.5 mt-1">
        <li><span className="text-accent">↑ / W / tap top</span> — HIGH lane (1)</li>
        <li><span className="text-accent">↓ / S / tap bottom</span> — LOW lane (0)</li>
        <li><span className="text-accent">P / Esc</span> — pause</li>
      </ul>
      <p className="text-[12px] text-gray-500">
        <span className="text-ok">VCC</span> heals,
        <span className="text-accent ml-1">CLOCK</span> slows time,
        <span className="text-violet-400 ml-1">NOT</span> flips your lane.
        Consecutive matches build a combo — up to <span className="text-warn font-semibold">×5</span> score multiplier.
      </p>
    </div>
  );
}

function OverRecap({ score, combo, bestScore }: {
  score: number; combo: number; bestScore: number;
}) {
  const newBest = score > 0 && score >= bestScore;
  return (
    <div className="space-y-1">
      <div>Final score: <span className="text-accent font-bold">{score}</span></div>
      <div className="text-gray-400 text-[12px]">
        Last combo: <span className="text-warn">×{combo}</span>
      </div>
      {newBest && <div className="mt-1 text-warn">⚡ New best!</div>}
    </div>
  );
}
