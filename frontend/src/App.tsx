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
  // Default both panels closed on phones — they take all the screen otherwise.
  const isMobileInit = typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches;
  const [sidebarOpen,    setSidebarOpen]    = useState(!isMobileInit);
  const [rightOpen,      setRightOpen]      = useState(!isMobileInit);
  const [isMobile,       setIsMobile]       = useState(isMobileInit);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

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

              <div className="flex flex-1 min-h-0 overflow-hidden relative">
                {/* Backdrop — only on mobile, only when a panel is open. Tapping
                    it closes whichever side panel is open. */}
                {isMobile && (sidebarOpen || rightOpen) && (
                  <div
                    onClick={() => { setSidebarOpen(false); setRightOpen(false); }}
                    className="fixed inset-0 top-12 z-30 bg-black/40 backdrop-blur-[1px] md:hidden"
                    aria-hidden
                  />
                )}

                {/* Left sidebar — overlays the canvas on mobile, in-flow on md+ */}
                {sidebarOpen && (
                  <div className={isMobile
                    ? "absolute left-0 top-0 bottom-0 z-40 shadow-2xl"
                    : "flex"}>
                    <Sidebar selected={pendingType} onSelect={handleSidebarSelect} />
                  </div>
                )}
                {!isMobile && (
                  <CollapseHandle
                    side="left"
                    open={sidebarOpen}
                    onToggle={() => setSidebarOpen((v) => !v)}
                    title={sidebarOpen ? "Hide gate palette" : "Show gate palette"}
                  />
                )}

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

                  {/* Mobile-only floating toggles to open the two side panels */}
                  {isMobile && !sidebarOpen && (
                    <button
                      onClick={() => { setSidebarOpen(true); setRightOpen(false); }}
                      title="Show gate palette"
                      className="absolute left-2 top-2 z-20 w-9 h-9 rounded-full bg-bg-800/90 border border-bg-600 text-gray-300 hover:text-accent hover:border-accent/50 flex items-center justify-center shadow-lg backdrop-blur"
                    >
                      <ChevronRight size={16} />
                    </button>
                  )}
                  {isMobile && !rightOpen && (
                    <button
                      onClick={() => { setRightOpen(true); setSidebarOpen(false); }}
                      title="Show analysis panel"
                      className="absolute right-2 top-2 z-20 w-9 h-9 rounded-full bg-bg-800/90 border border-bg-600 text-gray-300 hover:text-accent hover:border-accent/50 flex items-center justify-center shadow-lg backdrop-blur"
                    >
                      <ChevronLeft size={16} />
                    </button>
                  )}
                </main>

                {/* Right collapse handle + panel */}
                {!isMobile && (
                  <CollapseHandle
                    side="right"
                    open={rightOpen}
                    onToggle={() => setRightOpen((v) => !v)}
                    title={rightOpen ? "Hide analysis panel" : "Show analysis panel"}
                  />
                )}
                {rightOpen && (
                  <div className={isMobile
                    ? "absolute right-0 top-0 bottom-0 z-40 shadow-2xl"
                    : "flex"}>
                    <RightPanel
                      tab={rightTab}
                      setTab={setRightTab}
                      selectedGateId={selectedGateId}
                    />
                  </div>
                )}
              </div>

              {/* Status bar */}
              <div className="h-6 bg-bg-800 border-t border-bg-600 flex items-center px-3 gap-3 flex-shrink-0 text-[11px] tabular-nums">
                <span className="text-gray-500">
                  {state.circuit.gates.length} <span className="text-gray-600">gates</span> · {state.circuit.wires.length} <span className="text-gray-600">wires</span>
                </span>
                <span className="text-gray-600 hidden sm:inline">
                  Tool <span className="text-gray-400">{tool}</span>
                </span>
                {state.selected.size > 0 && (
                  <span className="text-accent">
                    {state.selected.size} selected
                  </span>
                )}
                {pendingType && (
                  <span className="text-warn">
                    Placing {pendingType}
                  </span>
                )}
                <div className="flex-1" />
                <span className="text-gray-600 hidden md:inline">
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
