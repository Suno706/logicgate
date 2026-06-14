import { useEffect, useRef, useState } from "react";
import { Heart, Trophy, Zap, RotateCcw, Play, Pause, ArrowUp, ArrowDown, ArrowLeft, ArrowRight } from "lucide-react";

/* ─────────────────────────────────────────────────────────────────────
   Signal Snake — Snake × Runner hybrid

   You're a logic signal slithering through a circuit on a grid. The
   snake auto-moves in its current direction (Runner DNA), you change
   direction with arrow keys or swipes (Snake DNA). Eat 1-bits and
   0-bits to grow; passing through a logic gate scores big if your
   current value matches its required input, hurts you if it doesn't.
   Crashing into a wall or your own tail ends the run.

   Mechanics:
     - Grid: 24 cols × 14 rows (anything beyond ~280 cells gets crowded)
     - Snake moves one cell per tick, ~7 Hz baseline (CLOCK = slow-mo)
     - Direction queue so a quick double-tap of (down, right) doesn't
       lose the second input mid-tick
     - Food: a 0-bit or 1-bit spawned in an empty cell at all times
     - Gates: stay on the board until the snake passes over them; they
       carry a required-input chip (0 or 1) and damage on mismatch
     - HP: starts at 3, max 5. Mismatch a gate → -1 HP. Wall / self → 0.
     - Score: bit = +10; gate match = +50 × (1 + lengthBonus / 20);
       perfect chain combo applies if you match 3 gates in a row.

   Why this isn't the previous SignalRunner:
     - That one was a flat two-lane side-scroller. This is a 2D grid
       with direction control and a growing body, which feels much
       more like an actual game.
     - Snake's "your own length is your worst enemy" tension is now
       the core of the difficulty curve, not the gradually rising
       scroll speed.
   ─────────────────────────────────────────────────────────────────── */


/* ── grid & timing constants ────────────────────────────────────── */

const COLS = 24;
const ROWS = 14;
const BASE_TICK_MS  = 150;            // snake step rate
const MIN_TICK_MS   = 70;             // hard cap on speed
const SPEED_GAIN_MS = 4;              // shaved per length-of-5

const BEST_KEY        = "logicgate.snake.best";
const BEST_LENGTH_KEY = "logicgate.snake.bestlen";


/* ── types ──────────────────────────────────────────────────────── */

type Cell = { x: number; y: number };
type Direction = "up" | "down" | "left" | "right";
type LogicGateKind = "AND" | "OR" | "XOR" | "NAND" | "NOR" | "XNOR";

interface Bit       { kind: "bit";   value: 0 | 1; cell: Cell; }
interface LogicGate { kind: "gate";  gateKind: LogicGateKind; needs: 0 | 1; cell: Cell; }
interface PowerUp   { kind: "power"; effect: "vcc" | "clock"; cell: Cell; }
type Pickup = Bit | LogicGate | PowerUp;

type Phase = "idle" | "playing" | "paused" | "over";


/* ── helpers ────────────────────────────────────────────────────── */

const eq = (a: Cell, b: Cell) => a.x === b.x && a.y === b.y;

function opposite(a: Direction, b: Direction): boolean {
  return (a === "up" && b === "down")    || (a === "down"  && b === "up")
      || (a === "left" && b === "right") || (a === "right" && b === "left");
}

function oppositeDir(d: Direction): Direction {
  switch (d) {
    case "up":    return "down";
    case "down":  return "up";
    case "left":  return "right";
    case "right": return "left";
  }
}

function step(c: Cell, d: Direction): Cell {
  switch (d) {
    case "up":    return { x: c.x,     y: c.y - 1 };
    case "down":  return { x: c.x,     y: c.y + 1 };
    case "left":  return { x: c.x - 1, y: c.y     };
    case "right": return { x: c.x + 1, y: c.y     };
  }
}

function randomEmptyCell(taken: Cell[]): Cell {
  // Generous upper bound; with COLS*ROWS=336 cells and a body of a few
  // dozen at most, this almost never iterates twice.
  for (let i = 0; i < 200; i++) {
    const c = { x: Math.floor(Math.random() * COLS),
                y: Math.floor(Math.random() * ROWS) };
    if (!taken.some((t) => eq(t, c))) return c;
  }
  return { x: 0, y: 0 };
}

function rollLogicGate(): LogicGateKind {
  const all: LogicGateKind[] = ["AND", "OR", "XOR", "NAND", "NOR", "XNOR"];
  return all[Math.floor(Math.random() * all.length)];
}

function gateNeeds(kind: LogicGateKind): 0 | 1 {
  // AND/OR/XNOR want HIGH; NAND/NOR/XOR want LOW. Same convention as
  // the previous side-scroller so muscle memory transfers.
  return (kind === "AND" || kind === "OR" || kind === "XNOR") ? 1 : 0;
}

const readN = (k: string) => {
  try { return Number(localStorage.getItem(k) || "0") || 0; }
  catch { return 0; }
};
const writeN = (k: string, n: number) => {
  try { localStorage.setItem(k, String(n)); } catch { /* unavailable */ }
};


/* ── component ──────────────────────────────────────────────────── */

export function SignalRunner() {
  /* refs that drive rAF without React re-renders every frame */
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stageRef  = useRef<HTMLDivElement   | null>(null);

  /* HUD state — re-renders only when the displayed numbers change */
  const [hp,        setHp]        = useState(3);
  const [score,     setScore]     = useState(0);
  const [length,    setLength]    = useState(4);
  const [combo,     setCombo]     = useState(0);
  const [value,     setValue]     = useState<0 | 1>(1);
  const [phase,     setPhase]     = useState<Phase>("idle");
  const [bestScore, setBest]      = useState<number>(() => readN(BEST_KEY));
  const [bestLen,   setBestLen]   = useState<number>(() => readN(BEST_LENGTH_KEY));

  /* mutable game state */
  const game = useRef({
    snake:      [] as Cell[],            // head at index 0
    prevSnake:  [] as Cell[],            // snapshot at last tick start, for smooth interpolation between cells
    dir:        "right" as Direction,
    dirQueue:   [] as Direction[],
    value:      1 as 0 | 1,
    pickups:    [] as Pickup[],
    hp:         3,
    score:      0,
    combo:      0,
    bestCombo:  0,
    slowmoUntil: 0,
    lastTickAt: 0,
    tickInterval: BASE_TICK_MS,          // updated each tick for the renderer
    bannerCombo: 0,                      // last combo we showed a banner for
    bannerLife:  0,                      // seconds remaining on combo banner
    flash:      0,
    flashKind:  "none" as "good" | "bad" | "shock" | "none",
    floaters:   [] as { x: number; y: number; text: string; color: string; life: number; ttl: number }[],
    particles:  [] as { x: number; y: number; vx: number; vy: number; color: string; life: number; ttl: number; size: number }[],
  });

  /* ── lifecycle helpers ─────────────────────────────────────── */

  function startNewRun() {
    const g = game.current;
    // Seed snake horizontally, head at index 0
    const startY = Math.floor(ROWS / 2);
    const startX = 4;
    g.snake = [
      { x: startX,     y: startY },
      { x: startX - 1, y: startY },
      { x: startX - 2, y: startY },
      { x: startX - 3, y: startY },
    ];
    g.dir = "right"; g.dirQueue = []; g.value = 1;
    g.hp = 3; g.score = 0; g.combo = 0; g.bestCombo = 0;
    g.slowmoUntil = 0;
    g.lastTickAt = 0;
    g.flash = 0; g.flashKind = "none";
    g.floaters = [];
    g.pickups  = [];
    spawnInitialPickups(g);
    setHp(3); setScore(0); setLength(g.snake.length); setCombo(0); setValue(1);
    setPhase("playing");
  }

  function togglePause() {
    setPhase((p) => p === "playing" ? "paused" : p === "paused" ? "playing" : p);
  }

  function queueDir(d: Direction) {
    const g = game.current;
    const last = g.dirQueue[g.dirQueue.length - 1] ?? g.dir;
    if (opposite(last, d) || last === d) return;
    if (g.dirQueue.length < 2) g.dirQueue.push(d);
  }

  /* ── inputs ────────────────────────────────────────────────── */

  // Keyboard
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
      if (e.key === "ArrowUp"    || e.key === "w" || e.key === "W") queueDir("up");
      if (e.key === "ArrowDown"  || e.key === "s" || e.key === "S") queueDir("down");
      if (e.key === "ArrowLeft"  || e.key === "a" || e.key === "A") queueDir("left");
      if (e.key === "ArrowRight" || e.key === "d" || e.key === "D") queueDir("right");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase]);

  // Touch: swipe gestures map to direction; tap = pause toggle
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    let startX = 0, startY = 0, valid = false;
    const MIN_SWIPE = 25;

    function onDown(e: PointerEvent) {
      startX = e.clientX; startY = e.clientY;
      valid = true;
    }
    function onUp(e: PointerEvent) {
      if (!valid) return;
      valid = false;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      const adx = Math.abs(dx), ady = Math.abs(dy);
      if (adx < MIN_SWIPE && ady < MIN_SWIPE) return; // taps ignored
      if (phase !== "playing") return;
      if (adx > ady) queueDir(dx > 0 ? "right" : "left");
      else           queueDir(dy > 0 ? "down"  : "up");
    }
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointerup",   onUp);
    return () => {
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointerup",   onUp);
    };
  }, [phase]);

  /* ── game loop ─────────────────────────────────────────────── */

  useEffect(() => {
    if (phase !== "playing") return;
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx) return;
    let raf = 0;

    function loop(now: number) {
      const g = game.current;
      const slow = now < g.slowmoUntil;
      const tickInterval = Math.max(
        MIN_TICK_MS,
        BASE_TICK_MS - Math.floor((g.snake.length - 4) / 5) * SPEED_GAIN_MS,
      ) * (slow ? 1.6 : 1);

      g.tickInterval = tickInterval;
      if (now - g.lastTickAt >= tickInterval) {
        g.lastTickAt = now;
        // Capture where the snake WAS so the renderer can interpolate
        // each segment from its prev cell to its new cell. This is the
        // single biggest "video game" visual upgrade: the snake slides
        // smoothly between grid cells instead of teleporting.
        g.prevSnake = g.snake.map((c: Cell) => ({ x: c.x, y: c.y }));
        if (!stepSnake(g)) {
          finishRun(g);
          return;
        }
        syncHud(g);
      }

      // Decay flash/floaters/particles/banner every frame
      const dt = 1 / 60;
      if (g.flash > 0)       g.flash = Math.max(0, g.flash - dt * 3);
      if (g.bannerLife > 0)  g.bannerLife = Math.max(0, g.bannerLife - dt);
      for (const f of g.floaters)  f.life -= dt;
      for (const p of g.particles) {
        p.x += p.vx * dt;  p.y += p.vy * dt;
        p.vy += 12 * dt;                      // gravity in cell units
        p.life -= dt;
      }
      g.floaters  = g.floaters .filter((f: any) => f.life > 0);
      g.particles = g.particles.filter((p: any) => p.life > 0);

      drawWorld(ctx!, g, now);

      raf = requestAnimationFrame(loop);
    }
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  function syncHud(g: typeof game.current) {
    if (g.hp           !== hp)     setHp(g.hp);
    if (g.score        !== score)  setScore(g.score);
    if (g.snake.length !== length) setLength(g.snake.length);
    if (g.combo        !== combo)  setCombo(g.combo);
    if (g.value        !== value)  setValue(g.value);
  }

  function finishRun(g: typeof game.current) {
    setHp(0); setScore(g.score); setLength(g.snake.length);
    setPhase("over");
    if (g.score > bestScore) {
      setBest(g.score); writeN(BEST_KEY, g.score);
    }
    if (g.snake.length > bestLen) {
      setBestLen(g.snake.length); writeN(BEST_LENGTH_KEY, g.snake.length);
    }
  }

  /* ── render ────────────────────────────────────────────────── */

  return (
    <div className="flex flex-col gap-3 p-3 md:p-5"
         style={{ minHeight: "calc(100vh - 3rem)" }}>

      <Hud
        hp={hp} score={score} length={length} combo={combo}
        bestScore={bestScore} bestLen={bestLen} value={value}
        phase={phase} onPauseToggle={togglePause}
      />

      <div ref={stageRef}
           className="flex-1 min-h-0 relative rounded-2xl border border-bg-600 bg-bg-900 overflow-hidden select-none shadow-inner">

        <canvas
          ref={canvasRef}
          style={{ width: "100%", height: "100%", display: "block", touchAction: "none" }}
        />

        {phase === "playing" && (
          <DirPad onDir={queueDir} />
        )}

        {phase === "idle"   && <Splash title="Signal Snake" body={<IdleHelp />}     cta={<><Play size={14} /> Start</>}   onCta={startNewRun} />}
        {phase === "paused" && <Splash title="Paused"        body="Take a breath."  cta={<><Play size={14} /> Resume</>}  onCta={togglePause} />}
        {phase === "over"   && <Splash title="Crashed"       body={<OverRecap score={score} length={length} bestScore={bestScore} />} cta={<><RotateCcw size={14} /> Run again</>} onCta={startNewRun} />}
      </div>
    </div>
  );
}


/* ─────────────────────────────────────────────────────────────────
   Game logic — pure mutators on the game state ref.
   ───────────────────────────────────────────────────────────────── */

function spawnInitialPickups(g: any) {
  const taken = [...g.snake];
  // Always exactly one 1-bit and one 0-bit on the board so the player
  // has somewhere to go regardless of current value.
  g.pickups.push({ kind: "bit", value: 1, cell: randomEmptyCell(taken) });
  taken.push((g.pickups[g.pickups.length - 1] as Bit).cell);
  g.pickups.push({ kind: "bit", value: 0, cell: randomEmptyCell(taken) });
  taken.push((g.pickups[g.pickups.length - 1] as Bit).cell);
  // Two starting gates
  for (let i = 0; i < 2; i++) {
    const kind = rollLogicGate();
    const cell = randomEmptyCell(taken);
    g.pickups.push({ kind: "gate", gateKind: kind, needs: gateNeeds(kind), cell });
    taken.push(cell);
  }
}

/** One movement tick. Returns false if the snake died (HP exhausted). */
function stepSnake(g: any): boolean {
  // Apply queued direction change (one per tick)
  if (g.dirQueue.length > 0) {
    const next = g.dirQueue.shift();
    if (!opposite(g.dir, next)) g.dir = next;
  }

  const head = step(g.snake[0], g.dir);

  // Wall collision — used to be instant-death, but HP was decorative.
  // Now it costs 1 HP + shortens the snake by 3 segments, and the snake
  // reverses direction so the next tick takes you back into the field.
  // When HP hits 0 you're properly out.
  const hitWall = head.x < 0 || head.x >= COLS || head.y < 0 || head.y >= ROWS;
  const checkBody = g.snake.slice(0, -1);
  const hitSelf   = checkBody.some((c: Cell) => eq(c, head));
  if (hitWall || hitSelf) {
    g.hp -= 1;
    g.combo = 0;
    g.score = Math.max(0, g.score - 30);
    pushFloat(g, g.snake[0], "CRASH", "#fb7185");
    g.flash = 0.7; g.flashKind = "bad";
    if (g.hp <= 0) return false;
    // Survival recovery: lose tail length and bounce away from the obstacle.
    while (g.snake.length > 3 && g.snake.length > g.snake.length - 3) {
      g.snake.pop();
    }
    g.snake = g.snake.slice(0, Math.max(3, g.snake.length - 3));
    g.dir = oppositeDir(g.dir);
    g.dirQueue = [];
    return true;
  }

  // Move
  g.snake.unshift(head);

  // Check pickup at the new head
  const idx = g.pickups.findIndex((p: Pickup) => eq(p.cell, head));
  let grew = false;
  if (idx >= 0) {
    const p = g.pickups[idx];
    grew = applyPickup(g, p);
    g.pickups.splice(idx, 1);
    // Replenish so the field stays populated
    refillPickups(g);
  }

  if (!grew) g.snake.pop();

  // Death from gate mismatch dropping HP to 0
  return g.hp > 0;
}

function applyPickup(g: any, p: Pickup): boolean {
  const head = g.snake[0];
  if (p.kind === "bit") {
    g.value = p.value;
    g.score += 10;
    pushFloat(g, head, `${p.value}`, p.value === 1 ? "#34d399" : "#60a5fa");
    burst(g, head, p.value === 1 ? "#34d399" : "#60a5fa", 8);
    g.flash = 0.25; g.flashKind = "good";
    return true;                       // grow
  }
  if (p.kind === "power") {
    if (p.effect === "vcc") {
      g.hp = Math.min(g.hp + 1, 5);
      g.score += 30;
      pushFloat(g, head, "+1 HP", "#34d399");
      burst(g, head, "#34d399", 16);
    } else {
      g.slowmoUntil = performance.now() + 3000;
      g.score += 30;
      pushFloat(g, head, "SLOW", "#2dd4bf");
      burst(g, head, "#2dd4bf", 16);
    }
    g.flash = 0.25; g.flashKind = "good";
    return true;
  }
  // logic gate
  if (p.needs === g.value) {
    g.combo += 1;
    if (g.combo > g.bestCombo) g.bestCombo = g.combo;
    const points = 50 + Math.floor(g.snake.length / 2) + g.combo * 10;
    g.score += points;
    pushFloat(g, head, `+${points}`, "#a5f3fc");
    burst(g, head, "#67e8f9", 14);
    g.flash = 0.3; g.flashKind = "good";
    // Combo banner fires on 3+ — that's where the run feels good and
    // the player deserves an arcade-style call-out.
    if (g.combo >= 3 && g.combo !== g.bannerCombo) {
      g.bannerCombo = g.combo;
      g.bannerLife  = 1.2;
    }
  } else {
    g.combo = 0;
    g.hp -= 1;
    g.score = Math.max(0, g.score - 20);
    pushFloat(g, head, "MISS", "#fb7185");
    burst(g, head, "#fb7185", 18);
    g.flash = 0.5; g.flashKind = "bad";
  }
  return false;                        // gates don't grow you
}

/** Spawn `count` particles at a cell with a hot fountain. Velocities are
 *  in *cell units per second* so the renderer can position them on the
 *  same grid as everything else without unit conversion. */
function burst(g: any, c: Cell, color: string, count: number) {
  for (let i = 0; i < count; i++) {
    const ang = Math.random() * Math.PI * 2;
    const sp  = 4 + Math.random() * 7;
    g.particles.push({
      x: c.x + 0.5, y: c.y + 0.5,
      vx: Math.cos(ang) * sp,
      vy: Math.sin(ang) * sp - 4,
      life: 0.6 + Math.random() * 0.3, ttl: 0.9,
      color,
      size: 2 + Math.random() * 2,
    });
  }
}

function pushFloat(g: any, c: Cell, text: string, color: string) {
  g.floaters.push({ x: c.x, y: c.y, text, color, life: 0.9, ttl: 0.9 });
}

function refillPickups(g: any) {
  const taken = [...g.snake, ...g.pickups.map((p: Pickup) => p.cell)];
  const hasBit0 = g.pickups.some((p: Pickup) => p.kind === "bit" && (p as Bit).value === 0);
  const hasBit1 = g.pickups.some((p: Pickup) => p.kind === "bit" && (p as Bit).value === 1);

  if (!hasBit0) g.pickups.push({ kind: "bit", value: 0, cell: randomEmptyCell(taken) });
  if (!hasBit1) g.pickups.push({ kind: "bit", value: 1, cell: randomEmptyCell(taken) });
  while (gateCountNow(g) < 2) {
    const kind = rollLogicGate();
    g.pickups.push({ kind: "gate", gateKind: kind, needs: gateNeeds(kind),
                     cell: randomEmptyCell([...g.snake, ...g.pickups.map((p: Pickup) => p.cell)]) });
  }
  // Sparse power-ups — ~5% of refills
  if (Math.random() < 0.05) {
    const effect: PowerUp["effect"] = Math.random() < 0.5 ? "vcc" : "clock";
    g.pickups.push({ kind: "power", effect,
                     cell: randomEmptyCell([...g.snake, ...g.pickups.map((p: Pickup) => p.cell)]) });
  }
}

function gateCountNow(g: any): number {
  return g.pickups.filter((p: Pickup) => p.kind === "gate").length;
}


/* ─────────────────────────────────────────────────────────────────
   Rendering — canvas drawing functions, no state mutation.
   ───────────────────────────────────────────────────────────────── */

function drawWorld(ctx: CanvasRenderingContext2D, g: any, now: number) {
  const canvas = ctx.canvas;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth  || 1;
  const cssH = canvas.clientHeight || 1;
  const wantW = Math.round(cssW * dpr);
  const wantH = Math.round(cssH * dpr);
  if (canvas.width !== wantW || canvas.height !== wantH) {
    canvas.width = wantW; canvas.height = wantH;
  }

  // Compute cell size that fills the available area, keeping the grid
  // proportions. Maximum aspect: COLS:ROWS = 24:14.
  const cellSize = Math.floor(Math.min(cssW / COLS, cssH / ROWS));
  const gridW = cellSize * COLS;
  const gridH = cellSize * ROWS;
  const offX  = Math.floor((cssW - gridW) / 2);
  const offY  = Math.floor((cssH - gridH) / 2);

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  /* Background — radial gradient + subtle drifting grid scanlines for a
     CRT / arcade vibe. The drift speed is tied to wall-clock so it
     reads as movement even when the snake hasn't ticked yet. */
  const grad = ctx.createRadialGradient(cssW / 2, cssH / 2, 50, cssW / 2, cssH / 2, Math.max(cssW, cssH));
  grad.addColorStop(0, "#181b25");
  grad.addColorStop(1, "#0a0c12");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, cssW, cssH);

  /* Faint scanlines for the video-game feel */
  ctx.fillStyle = "rgba(255,255,255,0.012)";
  for (let y = 0; y < cssH; y += 3) ctx.fillRect(0, y, cssW, 1);

  /* Grid lines drifting subtly with time */
  const drift = (now / 18) % cellSize;
  ctx.strokeStyle = "#1a1d27";
  ctx.lineWidth   = 1;
  ctx.beginPath();
  for (let i = 0; i <= COLS + 1; i++) {
    const x = offX + i * cellSize - drift;
    if (x < offX || x > offX + gridW) continue;
    ctx.moveTo(x, offY); ctx.lineTo(x, offY + gridH);
  }
  for (let j = 0; j <= ROWS; j++) {
    ctx.moveTo(offX,         offY + j * cellSize);
    ctx.lineTo(offX + gridW, offY + j * cellSize);
  }
  ctx.stroke();

  /* Border — accent glow around the playfield */
  ctx.save();
  ctx.shadowColor = "#2dd4bf";
  ctx.shadowBlur  = 14;
  ctx.strokeStyle = "#2a2f3d";
  ctx.lineWidth   = 2;
  ctx.strokeRect(offX, offY, gridW, gridH);
  ctx.restore();

  /* Pickups — drawn with a subtle bob synced to clock */
  for (const p of g.pickups) drawPickup(ctx, p, offX, offY, cellSize, now);

  /* Snake — interpolate each segment from its previous cell to its
     current cell based on how far into this tick we are. Renders the
     whole body sliding smoothly between grid positions. Tail-to-head
     paint order keeps the glowing head on top. */
  const tickProgress = Math.min(1, (now - g.lastTickAt) / Math.max(1, g.tickInterval));
  for (let i = g.snake.length - 1; i >= 0; i--) {
    const cur  = g.snake[i];
    const prev = g.prevSnake[i] ?? cur;
    const ix = prev.x + (cur.x - prev.x) * tickProgress;
    const iy = prev.y + (cur.y - prev.y) * tickProgress;
    drawSnakeCell(ctx, ix, iy, i, g.snake.length, g.value, offX, offY, cellSize, now);
  }

  /* Particle bursts on top of the snake */
  for (const p of g.particles) {
    const a = Math.max(0, p.life / p.ttl);
    const cx = offX + p.x * cellSize;
    const cy = offY + p.y * cellSize;
    ctx.save();
    ctx.globalAlpha = a;
    ctx.fillStyle   = p.color;
    ctx.shadowColor = p.color;
    ctx.shadowBlur  = 8;
    ctx.beginPath();
    ctx.arc(cx, cy, p.size * a, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  /* Floating score popups */
  for (const f of g.floaters) {
    const a = Math.max(0, f.life / f.ttl);
    const cx = offX + f.x * cellSize + cellSize / 2;
    const cy = offY + f.y * cellSize + cellSize / 2 - (1 - a) * 30;
    ctx.save();
    ctx.globalAlpha    = a;
    ctx.fillStyle      = f.color;
    ctx.font           = "bold 14px 'JetBrains Mono', monospace";
    ctx.textAlign      = "center";
    ctx.textBaseline   = "middle";
    ctx.shadowColor    = f.color;
    ctx.shadowBlur     = 6;
    ctx.fillText(f.text, cx, cy);
    ctx.restore();
  }

  /* Combo banner — big centred call-out when chaining gates */
  if (g.bannerLife > 0) {
    const t = g.bannerLife / 1.2;
    const ease = 1 - (1 - t) * (1 - t);                 // ease-out alpha
    const bigScale = 1 + (1 - t) * 0.7;                  // pop-in scale
    ctx.save();
    ctx.globalAlpha    = Math.min(1, ease * 1.4);
    ctx.translate(cssW / 2, cssH / 2 - 30);
    ctx.scale(bigScale, bigScale);
    ctx.fillStyle      = "#fbbf24";
    ctx.font           = "bold 36px 'JetBrains Mono', monospace";
    ctx.textAlign      = "center";
    ctx.textBaseline   = "middle";
    ctx.shadowColor    = "#fbbf24";
    ctx.shadowBlur     = 18;
    ctx.fillText(`COMBO ×${g.bannerCombo}`, 0, 0);
    ctx.restore();
  }

  /* Damage / pickup flash overlay */
  if (g.flash > 0) {
    const c = g.flashKind === "bad" ? "248,113,113" : "52,211,153";
    ctx.fillStyle = `rgba(${c},${g.flash * 0.18})`;
    ctx.fillRect(0, 0, cssW, cssH);
  }
}

function drawSnakeCell(ctx: CanvasRenderingContext2D, fx: number, fy: number, idx: number, total: number, value: 0 | 1, offX: number, offY: number, size: number, now: number) {
  const x = offX + fx * size + 1;
  const y = offY + fy * size + 1;
  const w = size - 2;
  const radius = Math.max(2, Math.floor(size * 0.3));

  const isHead = idx === 0;
  // Body fades to dimmer at the tail so the player can read direction
  // even when the snake is long.
  const alpha = 1 - (idx / Math.max(total, 1)) * 0.55;
  const baseColor = value === 1 ? "#2dd4bf" : "#60a5fa";

  ctx.save();
  ctx.globalAlpha = alpha;

  // Every segment gets a soft glow now (used to be head-only) — sells
  // the "I am a luminous signal" identity even when fully extended.
  ctx.shadowColor = baseColor;
  ctx.shadowBlur  = isHead ? 18 : 6;

  if (isHead) {
    // Pulsing halo on the head, breath-synced to wall clock for a
    // subtle "this thing is alive" vibe.
    const pulse = 0.85 + Math.sin(now * 0.008) * 0.15;
    ctx.fillStyle = baseColor;
    ctx.globalAlpha = 0.35 * pulse;
    ctx.beginPath();
    ctx.roundRect(x - 4, y - 4, w + 8, w + 8, radius + 4);
    ctx.fill();
    ctx.globalAlpha = alpha;
  }
  ctx.fillStyle = baseColor;
  ctx.beginPath();
  ctx.roundRect(x, y, w, w, radius);
  ctx.fill();

  if (isHead) {
    ctx.shadowBlur  = 0;
    ctx.fillStyle    = "#0f1117";
    ctx.font         = `bold ${Math.max(11, Math.floor(size * 0.55))}px 'JetBrains Mono', monospace`;
    ctx.textAlign    = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(value), x + w / 2, y + w / 2 + 1);
  }
  ctx.restore();
}

function drawPickup(ctx: CanvasRenderingContext2D, p: Pickup, offX: number, offY: number, size: number, now: number) {
  // Subtle vertical bob keyed off the cell so neighbouring pickups
  // don't bob in lockstep. Makes the board feel alive without being
  // distracting.
  const phase = (p.cell.x + p.cell.y) * 0.7;
  const bob   = Math.sin(now * 0.005 + phase) * 1.5;
  const cx = offX + p.cell.x * size + size / 2;
  const cy = offY + p.cell.y * size + size / 2 + bob;

  if (p.kind === "bit") {
    const colour = p.value === 1 ? "#34d399" : "#60a5fa";
    // Outer pulsing halo
    const pulse = 0.7 + Math.sin(now * 0.006 + phase) * 0.3;
    ctx.save();
    ctx.shadowColor = colour;
    ctx.shadowBlur  = 12;
    ctx.fillStyle   = colour;
    ctx.globalAlpha = 0.3 * pulse;
    ctx.beginPath();
    ctx.arc(cx, cy, size * 0.45, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, size * 0.3, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    ctx.fillStyle    = "#0f1117";
    ctx.font         = `bold ${Math.max(10, Math.floor(size * 0.5))}px 'JetBrains Mono', monospace`;
    ctx.textAlign    = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(p.value), cx, cy + 1);
    return;
  }
  if (p.kind === "power") {
    const colour = p.effect === "vcc" ? "#34d399" : "#2dd4bf";
    ctx.save();
    ctx.shadowColor = colour;
    ctx.shadowBlur  = 10;
    ctx.strokeStyle = colour;
    ctx.lineWidth   = 2.5;
    ctx.fillStyle   = "#161922";
    ctx.beginPath();
    ctx.roundRect(cx - size * 0.4, cy - size * 0.4, size * 0.8, size * 0.8, 5);
    ctx.fill(); ctx.stroke();
    ctx.restore();
    ctx.fillStyle    = colour;
    ctx.font         = `bold ${Math.max(8, Math.floor(size * 0.38))}px 'JetBrains Mono', monospace`;
    ctx.textAlign    = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(p.effect === "vcc" ? "♥" : "⏱", cx, cy + 1);
    return;
  }
  // gate
  const wantHigh = p.needs === 1;
  const colour = wantHigh ? "#818cf8" : "#fbbf24";
  // Gates pulse stronger than bits — they're the score multiplier so
  // they should grab the eye more aggressively.
  const pulse = 0.6 + Math.sin(now * 0.008 + phase) * 0.4;
  ctx.save();
  ctx.shadowColor = colour;
  ctx.shadowBlur  = 10 + pulse * 6;
  ctx.strokeStyle = colour;
  ctx.lineWidth   = 2.5;
  ctx.fillStyle   = "#161922";
  ctx.beginPath();
  ctx.arc(cx, cy, size * 0.44, 0, Math.PI * 2);
  ctx.fill(); ctx.stroke();
  ctx.restore();
  ctx.fillStyle    = colour;
  ctx.font         = `bold ${Math.max(7, Math.floor(size * 0.28))}px 'JetBrains Mono', monospace`;
  ctx.textAlign    = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(p.gateKind, cx, cy - 2);
  ctx.font         = `${Math.max(7, Math.floor(size * 0.22))}px 'JetBrains Mono', monospace`;
  ctx.fillText(`need ${p.needs}`, cx, cy + size * 0.18);
}


/* ─────────────────────────────────────────────────────────────────
   HUD subcomponents.
   ───────────────────────────────────────────────────────────────── */

function Hud({ hp, score, length, combo, bestScore, bestLen, value, phase, onPauseToggle }: {
  hp: number; score: number; length: number; combo: number;
  bestScore: number; bestLen: number; value: 0 | 1;
  phase: Phase; onPauseToggle: () => void;
}) {
  const hearts = "♥".repeat(Math.max(0, hp)) || "·";
  const comboHot = combo >= 3;
  return (
    <div className="flex items-stretch gap-2 flex-wrap">
      <Cell icon={<Heart size={14} />}  label="HP"    value={hearts} colour="text-err" />
      <Cell icon={<Trophy size={14} />} label="Score" value={String(score)} sub={bestScore > 0 ? `Best ${bestScore}` : undefined} />
      <Cell icon={<Zap size={14} />}    label="Length" value={String(length)} sub={bestLen > 0 ? `Best ${bestLen}` : undefined} />
      <Cell icon={null}                 label="Value" value={String(value)}    colour={value === 1 ? "text-ok" : "text-accent"} />
      {combo >= 2 && (
        <Cell icon={null} label="Combo" value={`×${combo}`} colour={comboHot ? "text-warn" : "text-gray-100"} />
      )}
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

function Cell({ icon, label, value, sub, colour = "text-gray-100" }: {
  icon: React.ReactNode; label: string; value: string; sub?: string; colour?: string;
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-bg-800/70 border border-bg-600 min-w-[90px]">
      {icon && <span className="text-gray-400">{icon}</span>}
      <div className="flex flex-col leading-tight">
        <span className="text-[10px] uppercase tracking-wider text-gray-500">{label}</span>
        <span className={`text-[14px] font-semibold tabular-nums ${colour}`}>{value}</span>
        {sub && <span className="text-[9px] text-gray-600 tabular-nums">{sub}</span>}
      </div>
    </div>
  );
}

/** Mobile-only D-pad overlay so phones don't need swipe accuracy on
 *  the body of the snake. Sits in the bottom corners; pointer-events
 *  on the buttons only so the canvas under it still receives swipes. */
function DirPad({ onDir }: { onDir: (d: Direction) => void }) {
  const btn = "w-11 h-11 rounded-lg bg-bg-800/70 border border-bg-600 text-gray-300 hover:border-accent/40 active:bg-bg-700 flex items-center justify-center pointer-events-auto";
  return (
    <div className="absolute bottom-3 right-3 grid grid-cols-3 gap-1 pointer-events-none md:hidden">
      <div />
      <button className={btn} onClick={() => onDir("up")}    aria-label="up"><ArrowUp size={18} /></button>
      <div />
      <button className={btn} onClick={() => onDir("left")}  aria-label="left"><ArrowLeft size={18} /></button>
      <div />
      <button className={btn} onClick={() => onDir("right")} aria-label="right"><ArrowRight size={18} /></button>
      <div />
      <button className={btn} onClick={() => onDir("down")}  aria-label="down"><ArrowDown size={18} /></button>
      <div />
    </div>
  );
}

function Splash({ title, body, cta, onCta }: {
  title: string; body: React.ReactNode;
  cta: React.ReactNode; onCta: () => void;
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
      <p>You're a logic signal slithering through a grid. Eat bits to grow, pass through gates that match your current value for big points, and don't crash into yourself.</p>
      <ul className="text-gray-500 text-[12px] space-y-0.5 mt-1">
        <li><span className="text-accent">↑↓←→ / WASD</span> — turn (desktop)</li>
        <li><span className="text-accent">Swipe</span> — turn (mobile), or use the D-pad bottom-right</li>
        <li><span className="text-accent">P / Esc</span> — pause</li>
      </ul>
      <p className="text-[12px] text-gray-500">
        Bit eaten → grow & change your value. Gate matched → big score and combo. Gate missed → lose 1 HP.
      </p>
    </div>
  );
}

function OverRecap({ score, length, bestScore }: {
  score: number; length: number; bestScore: number;
}) {
  const isBest = score > 0 && score >= bestScore;
  return (
    <div className="space-y-1">
      <div>Final score: <span className="text-accent font-bold">{score}</span></div>
      <div className="text-gray-400 text-[12px]">Final length: <span className="text-gray-100 font-semibold">{length}</span></div>
      {isBest && <div className="mt-1 text-warn">⚡ New best!</div>}
    </div>
  );
}
