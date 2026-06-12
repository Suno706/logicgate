import { useState } from "react";
import { X, Gamepad2, ChevronRight, Zap, Cpu, MousePointer2, Activity, Bot } from "lucide-react";
import { SignalMaze } from "./SignalMaze";
import { OverrideMode } from "./OverrideMode";
import { SignalRunner } from "./SignalRunner";
import { GateBots } from "./GateBots";

type GameId = "menu" | "maze" | "override" | "runner" | "bots";

interface Props {
  onClose: () => void;
}

/** Full-screen game overlay. Opens above the editor on top of everything,
 *  blocks editor interaction, shows a launcher menu, then loads the chosen
 *  game. ESC or the close button returns to the editor. */
export function GameScreen({ onClose }: Props) {
  const [game, setGame] = useState<GameId>("menu");

  return (
    <div className="fixed inset-0 z-[120] bg-bg-900 text-gray-200 flex flex-col">
      {/* Top bar */}
      <div className="h-12 flex items-center px-4 border-b border-bg-600 bg-bg-800 flex-shrink-0 gap-3">
        <Gamepad2 size={16} className="text-accent" />
        <span className="text-[13px] font-semibold text-gray-100">Arcade</span>
        {game !== "menu" && (
          <>
            <ChevronRight size={12} className="text-gray-600" />
            <button onClick={() => setGame("menu")}
              className="text-[12px] text-gray-400 hover:text-accent transition-colors">
              All games
            </button>
            <ChevronRight size={12} className="text-gray-600" />
            <span className="text-[12px] text-gray-300">
              {game === "maze" ? "Signal Maze"
                : game === "override" ? "Override the Mainframe"
                : game === "runner"   ? "Signal Runner"
                : "Gate Bots"}
            </span>
          </>
        )}
        <div className="flex-1" />
        <button onClick={onClose}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-medium text-gray-300 border border-bg-600 hover:border-accent/40 hover:text-gray-100 transition-colors"
          title="Close game (back to editor)">
          <X size={13} /> <span className="hidden sm:inline">Back to editor</span>
        </button>
      </div>

      {/* Body — single scrollable container so each game doesn't have to
          manage scroll itself. iOS Safari needs explicit momentum scrolling
          via -webkit-overflow-scrolling for finger-flick to feel right; the
          inline style covers Tailwind not having that as a utility. */}
      <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain"
           style={{ WebkitOverflowScrolling: "touch" }}>
        {game === "menu" && <Launcher onPick={setGame} />}
        {game === "maze"     && <SignalMaze />}
        {game === "override" && <OverrideMode />}
        {game === "runner"   && <SignalRunner />}
        {game === "bots"     && <GateBots />}
      </div>
    </div>
  );
}

function Launcher({ onPick }: { onPick: (g: GameId) => void }) {
  return (
    <div className="flex-1 overflow-y-auto p-5 md:p-10">
      <div className="max-w-3xl mx-auto">
        <h1 className="text-[28px] md:text-[34px] font-bold text-gray-100 mb-2 tracking-tight">
          Logic arcade
        </h1>
        <p className="text-[14px] text-gray-400 mb-8 max-w-xl leading-relaxed">
          Pick a game. Both run entirely in the browser — no scores leave your device.
        </p>

        <div className="grid md:grid-cols-2 gap-5">
          <GameCard
            icon={<Bot size={22} />}
            tag="Strategy · Campaign + 1v1"
            title="Gate Bots"
            blurb="Build a fighting robot out of logic gates — every gate type is a different stat (OR = attack, AND = armor, NOT = speed, XOR = crit…). 10 campaign stages with limited inventories and predefined bosses, plus hot-seat 1v1 on one device."
            cta="Build your bot →"
            highlight
            onClick={() => onPick("bots")}
          />
          <GameCard
            icon={<Activity size={22} />}
            tag="Arcade · 2D Runner"
            title="Signal Runner"
            blurb="Race a HIGH/LOW signal through a stream of logic gates. Switch lanes to match each gate's required input — match it, score; mismatch it, lose HP. VCC heals, CLOCK slows time, NOT flips your lane. Touch + keyboard."
            cta="Start the run →"
            onClick={() => onPick("runner")}
          />
          <GameCard
            icon={<MousePointer2 size={22} />}
            tag="Build on the canvas"
            title="Canvas Challenge"
            blurb="A random truth table is your goal. Drag real gates from the palette, wire them between A, B and Y on the actual editor. Hit Check — every input combination is simulated and compared to the target. Match every row to win."
            cta="Start building →"
            onClick={() => window.dispatchEvent(new CustomEvent("logicgate:start-challenge", { detail: { nIn: 2 } }))}
          />
          <GameCard
            icon={<Cpu size={22} />}
            tag="Procedural · Puzzle"
            title="Signal Maze"
            blurb="Route a signal through a chain of gates to light the LED. Every level is freshly generated — never the same puzzle twice."
            cta="Start solving →"
            onClick={() => onPick("maze")}
          />
          <GameCard
            icon={<Zap size={22} />}
            tag="Arcade · Timed"
            title="Override the Mainframe"
            blurb="Match truth tables to gates as fast as you can. Correct picks earn combo points and bonus time. Wrong picks cost time."
            cta="Start the run →"
            onClick={() => onPick("override")}
          />
        </div>

        <div className="mt-10 text-[11px] text-gray-600 text-center">
          More games coming. Suggestions welcome.
        </div>
      </div>
    </div>
  );
}

function GameCard({ icon, tag, title, blurb, cta, onClick, highlight }: {
  icon: React.ReactNode; tag: string; title: string; blurb: string; cta: string;
  onClick: () => void; highlight?: boolean;
}) {
  return (
    <button onClick={onClick}
      className={`text-left rounded-2xl border p-6 transition-colors group ${
        highlight
          ? "bg-accent/10 border-accent/60 hover:bg-accent/15"
          : "bg-bg-800/70 border-bg-600 hover:bg-bg-800 hover:border-accent/50"
      }`}>
      <div className="flex items-center gap-3 mb-3">
        <div className="w-11 h-11 rounded-xl bg-accent/15 border border-accent/40 text-accent flex items-center justify-center">
          {icon}
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-0.5">{tag}</div>
          <div className="text-[17px] font-semibold text-gray-100">{title}</div>
        </div>
      </div>
      <p className="text-[12px] text-gray-400 leading-relaxed mb-3">{blurb}</p>
      <div className="text-[12px] font-medium text-accent group-hover:translate-x-0.5 transition-transform">
        {cta}
      </div>
    </button>
  );
}
