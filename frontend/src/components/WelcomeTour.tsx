import { useEffect, useState } from "react";
import { ChevronRight, Sparkles, X } from "lucide-react";

const STORAGE_KEY = "logicgate.tour_seen_v1";

const STEPS = [
  {
    title: "Welcome to LogicGate",
    body: "Build digital circuits with drag-and-drop, simulate them, and ask the AI Smart panel anything about digital logic. This 30-second tour shows you around.",
    icon: "👋",
  },
  {
    title: "Click → place gates",
    body: "Click any gate in the left palette (AND, OR, INPUT, half-adder…), then click on the canvas to drop it. The canvas grid auto-snaps unless you turn Snap off.",
    icon: "🧱",
  },
  {
    title: "Drag pin → pin to wire",
    body: "Drag from a gate's output (right side) to another's input (left side) to create a wire. Wire colour flips between red/green during simulation to show signal flow.",
    icon: "🔌",
  },
  {
    title: "▶ Simulate, then explore",
    body: "Press Simulate at the top to run the circuit. Open the right panel for TRUTH table, K-MAP, BOOL expression, or SMART chat. Try the Examples gallery (Load → BookOpen).",
    icon: "🚀",
  },
  {
    title: "Multi-user — Rooms",
    body: "Click the Users icon in the top bar to enter a shared room code. Everyone in the same room sees the same saved circuits. Without a room you're in solo mode — fully private.",
    icon: "👥",
  },
  {
    title: "Smart panel learns from YOU",
    body: "Every answer the Smart panel gives has 👍/👎 buttons. Click them to teach the ML model. Hit \"Retrain on my feedback\" to apply your corrections. The more you use it, the better it gets.",
    icon: "🧠",
  },
];

export function WelcomeTour() {
  const [open, setOpen]   = useState(false);
  const [step, setStep]   = useState(0);

  useEffect(() => {
    if (!localStorage.getItem(STORAGE_KEY)) {
      setOpen(true);
    }
  }, []);

  function close() {
    setOpen(false);
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch {}
  }

  function next() {
    if (step < STEPS.length - 1) setStep(step + 1);
    else close();
  }

  if (!open) return null;
  const s = STEPS[step];
  return (
    <div className="fixed inset-0 z-[100] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-bg-800 border border-accent/40 rounded-xl shadow-2xl max-w-md w-full p-6 space-y-4">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-accent/20 border border-accent/40 flex items-center justify-center text-lg">
              {s.icon}
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <Sparkles size={11} className="text-accent" />
                <span className="text-[9px] font-mono uppercase tracking-widest text-accent">
                  Step {step + 1} / {STEPS.length}
                </span>
              </div>
              <h2 className="text-base font-mono font-bold text-gray-100">{s.title}</h2>
            </div>
          </div>
          <button onClick={close} title="Skip tour"
            className="text-gray-600 hover:text-gray-300 transition-colors">
            <X size={16} />
          </button>
        </div>

        <p className="text-[11px] font-mono text-gray-400 leading-relaxed">
          {s.body}
        </p>

        {/* Progress dots */}
        <div className="flex items-center justify-center gap-1.5 py-1">
          {STEPS.map((_, i) => (
            <button key={i} onClick={() => setStep(i)}
              className={`h-1.5 rounded-full transition-all ${
                i === step ? "w-6 bg-accent" : "w-1.5 bg-bg-600 hover:bg-bg-500"
              }`} />
          ))}
        </div>

        <div className="flex gap-2 pt-1">
          <button onClick={close}
            className="px-3 py-2 rounded-lg text-[10px] font-mono text-gray-500 hover:text-gray-300 transition-colors">
            Skip
          </button>
          <div className="flex-1" />
          {step > 0 && (
            <button onClick={() => setStep(step - 1)}
              className="px-3 py-2 rounded-lg bg-bg-700 hover:bg-bg-600 text-[10px] font-mono text-gray-300 border border-bg-600">
              Back
            </button>
          )}
          <button onClick={next}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-accent hover:bg-accent-hover text-white text-[10px] font-mono font-bold">
            {step < STEPS.length - 1 ? "Next" : "Let's go!"}
            <ChevronRight size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}
