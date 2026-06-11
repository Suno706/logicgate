import { Gamepad2, ChevronRight } from "lucide-react";

/** Right-panel Play tab — just a launcher card. Clicking it dispatches a
 *  window event that App.tsx listens for and opens the full-screen game
 *  overlay. We keep this panel small because the actual games live on
 *  their own page. */
export function GamePanel() {
  function launch() {
    window.dispatchEvent(new CustomEvent("logicgate:open-game"));
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto p-4 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <Gamepad2 size={16} className="text-accent" />
        <span className="text-[14px] font-semibold text-gray-100">Logic arcade</span>
      </div>
      <p className="text-[12px] text-gray-400 leading-relaxed">
        Take a break from circuit building. Two games are live:
        a puzzle ladder and a timed arcade mode.
      </p>

      <button onClick={launch}
        className="w-full flex items-center gap-3 rounded-xl border border-accent/40 bg-accent/10 hover:bg-accent/15 text-accent px-4 py-3 transition-colors">
        <div className="flex-1 text-left">
          <div className="text-[13px] font-semibold">Open arcade</div>
          <div className="text-[11px] opacity-80">Full-screen · ESC or Back returns here</div>
        </div>
        <ChevronRight size={16} />
      </button>

      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div className="rounded-lg border border-bg-600 bg-bg-800/60 p-3">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Puzzle</div>
          <div className="text-gray-100 font-medium">Signal Maze</div>
          <div className="text-gray-500 mt-1">Route the signal to light the LED.</div>
        </div>
        <div className="rounded-lg border border-bg-600 bg-bg-800/60 p-3">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Arcade</div>
          <div className="text-gray-100 font-medium">Override</div>
          <div className="text-gray-500 mt-1">Match gates before the timer runs out.</div>
        </div>
      </div>
    </div>
  );
}
