import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { health, getSessionId } from "./api";
import type { GateType, Tool, RightTab } from "./types";
import { useCircuitReducer, StateCtx, DispatchCtx } from "./store";
import { collab } from "./collab";
import { getDisplayName } from "./components/SignInGate";
import { Canvas, CanvasEmptyState } from "./components/Canvas";
import { Sidebar }       from "./components/Sidebar";
import { Header }        from "./components/Header";
import { RightPanel }    from "./components/RightPanel";
import { ToastProvider } from "./components/Toast";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { WelcomeTour }  from "./components/WelcomeTour";
import { SignInGate }   from "./components/SignInGate";

/**
 * Slim vertical bar that sits between the canvas and each side panel.
 * The chevron sits at the vertical center and rotates based on state.
 * Hover state highlights the bar in accent color.
 */
function CollapseHandle({
  side, open, onToggle, title,
}: {
  side: "left" | "right"; open: boolean; onToggle: () => void; title: string;
}) {
  // Chevron direction:
  //   left handle:  open → ‹  (collapse leftward),   closed → ›  (expand rightward)
  //   right handle: open → ›  (collapse rightward),  closed → ‹  (expand leftward)
  const showRight = (side === "left" && !open) || (side === "right" && open);
  return (
    <button
      onClick={onToggle}
      title={title}
      className={`group flex-shrink-0 w-3 hover:w-4 transition-all bg-bg-800 hover:bg-accent/10 flex items-center justify-center text-gray-600 hover:text-accent border-bg-600 ${
        side === "left" ? "border-r" : "border-l"
      }`}
    >
      {showRight
        ? <ChevronRight size={11} strokeWidth={2.5} className="opacity-50 group-hover:opacity-100 transition-opacity" />
        : <ChevronLeft  size={11} strokeWidth={2.5} className="opacity-50 group-hover:opacity-100 transition-opacity" />}
    </button>
  );
}

export default function App() {
  const [state, dispatch] = useCircuitReducer();

  const [tool,           setTool]           = useState<Tool>("select");
  const [snapGrid,       setSnapGrid]       = useState(true);
  const [pendingType,    setPendingType]    = useState<GateType | null>(null);
  const [rightTab,       setRightTab]       = useState<RightTab>("smart");
  const [selectedGateId, setSelectedGateId] = useState<string | null>(null);
  const [backendOk,      setBackendOk]      = useState<boolean | null>(null);
  const [sidebarOpen,    setSidebarOpen]    = useState(true);
  const [rightOpen,      setRightOpen]      = useState(true);

  useEffect(() => {
    const check = () =>
      health().then(() => setBackendOk(true)).catch(() => setBackendOk(false));
    check();
    const id = setInterval(check, 15_000);
    return () => clearInterval(id);
  }, []);

  // Open the realtime collab socket once the user has chosen guest/sign-in.
  // Reconnects whenever the session changes (e.g. user joins a room).
  useEffect(() => {
    const sid  = getSessionId();
    const name = getDisplayName() || "guest";
    collab.connect(sid, name);
    // Listen for session changes (the Room modal updates localStorage)
    function onStorage(e: StorageEvent) {
      if (e.key === "logicgate.session_id") {
        collab.connect(getSessionId(), getDisplayName() || "guest");
      }
    }
    window.addEventListener("storage", onStorage);
    // If the host kicks us, jump back to a private session.
    const offKicked = collab.onKicked((info) => {
      alert(`You were removed from room ${info.room}.\n${info.reason || ""}`);
      // The room id lives in sessionStorage (per-tab) — clearing only
      // localStorage used to leave the tab in the room after reload, so
      // the "kicked" user simply rejoined. Clear both.
      try {
        sessionStorage.removeItem("logicgate.session_id");
        localStorage.removeItem("logicgate.session_id");
      } catch { /* */ }
      const url = new URL(window.location.href);
      url.searchParams.delete("room");
      window.location.href = url.toString();
    });
    return () => {
      window.removeEventListener("storage", onStorage);
      offKicked();
      collab.disconnect();
    };
  }, []);

  function handleSidebarSelect(type: GateType) {
    setPendingType(pendingType === type ? null : type);
    setTool("select");
  }

  function handleGateSelected(id: string | null) {
    setSelectedGateId(id);
    if (id) setRightTab("props");
  }

  return (
    <ErrorBoundary>
      <ToastProvider>
        <StateCtx.Provider value={state}>
          <DispatchCtx.Provider value={dispatch}>
            <SignInGate />
            <WelcomeTour />
            <div className="h-screen flex flex-col overflow-hidden bg-bg-900 text-gray-200">

              <Header
                tool={tool}
                setTool={(t) => { setTool(t); if (t !== "select") setPendingType(null); }}
                snapGrid={snapGrid}
                setSnapGrid={setSnapGrid}
                backendOk={backendOk}
                onCircuitLoaded={() => { setSelectedGateId(null); setRightTab("smart"); }}
              />

              <div className="flex flex-1 min-h-0 overflow-hidden">
                {/* Left sidebar */}
                {sidebarOpen && <Sidebar selected={pendingType} onSelect={handleSidebarSelect} />}
                <CollapseHandle
                  side="left"
                  open={sidebarOpen}
                  onToggle={() => setSidebarOpen((v) => !v)}
                  title={sidebarOpen ? "Hide gate palette" : "Show gate palette"}
                />

                {/* Canvas */}
                <main className="flex-1 min-w-0 min-h-0 relative">
                  <Canvas
                    tool={tool}
                    snapGrid={snapGrid}
                    pendingType={pendingType}
                    onClearPending={() => setPendingType(null)}
                    onGateSelected={handleGateSelected}
                  />
                  {state.circuit.gates.length === 0 && <CanvasEmptyState />}
                </main>

                {/* Right collapse handle + panel */}
                <CollapseHandle
                  side="right"
                  open={rightOpen}
                  onToggle={() => setRightOpen((v) => !v)}
                  title={rightOpen ? "Hide analysis panel" : "Show analysis panel"}
                />
                {rightOpen && (
                  <RightPanel
                    tab={rightTab}
                    setTab={setRightTab}
                    selectedGateId={selectedGateId}
                  />
                )}
              </div>

              {/* Status bar */}
              <div className="h-6 bg-bg-800 border-t border-bg-600 flex items-center px-3 gap-4 flex-shrink-0">
                <span className="text-[9px] font-mono text-gray-600">
                  {state.circuit.gates.length} gates · {state.circuit.wires.length} wires
                </span>
                <span className="text-[9px] font-mono text-gray-700">
                  Tool: <span className="text-gray-500">{tool}</span>
                </span>
                {state.selected.size > 0 && (
                  <span className="text-[9px] font-mono text-accent">
                    {state.selected.size} selected
                  </span>
                )}
                {pendingType && (
                  <span className="text-[9px] font-mono text-warn">
                    Placing: {pendingType}
                  </span>
                )}
                <div className="flex-1" />
                <span className="text-[9px] font-mono text-gray-700 hidden sm:block">
                  Del · Ctrl+Z · Ctrl+A · Esc
                </span>
              </div>
            </div>
          </DispatchCtx.Provider>
        </StateCtx.Provider>
      </ToastProvider>
    </ErrorBoundary>
  );
}
