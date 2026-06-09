import { useEffect, useState } from "react";
import {
  MousePointer2, Spline, Hand, Undo2, Redo2, Trash2, Square,
  Grid3x3, Play, StopCircle, Save, FolderOpen, Wifi, WifiOff,
  Loader2, X, Maximize2, Users, BookOpen,
} from "lucide-react";
import type { Tool } from "../types";
import { useCircuitState, useCircuitDispatch, useCircuitActions } from "../store";
import { simulate, saveCircuit, listAllCircuits, loadCircuit,
         getSessionId, setRoom, getRoomCode, markRoomOwned,
         isRoomOwner, saveOwnerToken, getOwnerToken,
         kickFromRoom } from "../api";
import { collab } from "../collab";
import { getDisplayName, signOut } from "./SignInGate";
import { PresenceBadge } from "./PresenceBadge";
import { useToast } from "./Toast";

interface Props {
  tool: Tool;
  setTool: (t: Tool) => void;
  snapGrid: boolean;
  setSnapGrid: (v: boolean) => void;
  backendOk: boolean | null;
  onCircuitLoaded: () => void;
}

interface BtnProps {
  icon: React.ReactNode;
  label?: string;
  title: string;
  active?: boolean;
  disabled?: boolean;
  variant?: "default" | "primary" | "danger" | "success" | "warning";
  onClick: () => void;
}

function UserChip() {
  const name = getDisplayName();
  return (
    <button
      onClick={() => {
        if (confirm(`Sign out ${name || "guest"}? You'll be sent back to the sign-in screen.`)) {
          signOut();
        }
      }}
      title={name ? `Signed in as ${name} — click to sign out` : "Guest mode — click to switch identity"}
      className={`flex items-center gap-1.5 px-2 py-1 rounded-md ml-2 text-[10px] font-mono font-semibold border transition-all ${
        name
          ? "border-accent/40 text-accent hover:bg-accent/10"
          : "border-bg-600 text-gray-500 hover:text-gray-300 hover:bg-bg-700"
      }`}
    >
      <div className={`w-5 h-5 rounded-full flex items-center justify-center font-bold text-[9px] ${
        name ? "bg-accent/20 text-accent" : "bg-bg-600 text-gray-500"
      }`}>
        {name ? name[0].toUpperCase() : "g"}
      </div>
      <span className="hidden lg:block">{name || "guest"}</span>
    </button>
  );
}

function ToolBtn({ icon, label, title, active, disabled, variant = "default", onClick }: BtnProps) {
  const base = "flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[10px] font-mono font-semibold border transition-all disabled:opacity-40 disabled:cursor-not-allowed select-none";
  const styles: Record<string, string> = {
    default: active
      ? "border-accent/70 text-accent bg-accent/10"
      : "border-bg-600 text-gray-400 hover:border-gray-500 hover:text-gray-200 hover:bg-bg-700",
    primary: "border-accent/60 text-accent hover:bg-accent/10",
    danger:  "border-err/40 text-err hover:bg-err/10",
    success: "border-ok/40 text-ok hover:bg-ok/10",
    warning: "border-warn/40 text-warn hover:bg-warn/10",
  };
  return (
    <button title={title} onClick={onClick} disabled={disabled} className={`${base} ${styles[variant]}`}>
      {icon}
      {label && <span>{label}</span>}
    </button>
  );
}

function Divider() {
  return <div className="w-px h-5 bg-bg-600 mx-0.5 flex-shrink-0" />;
}

export function Header({ tool, setTool, snapGrid, setSnapGrid, backendOk, onCircuitLoaded }: Props) {
  const state    = useCircuitState();
  const dispatch = useCircuitDispatch();
  const actions  = useCircuitActions(dispatch);
  const toast    = useToast();

  const [simming,    setSimming]    = useState(false);
  const [saving,     setSaving]     = useState(false);
  const [circuits,   setCircuits]   = useState<{ mine: string[]; examples: string[] }>({ mine: [], examples: [] });
  const [showLoad,   setShowLoad]   = useState(false);
  const [saveName,   setSaveName]   = useState("my-circuit");
  const [showSave,   setShowSave]   = useState(false);
  const [showRoom,   setShowRoom]   = useState(false);
  const [roomInput,  setRoomInput]  = useState("");
  const [currentRoom, setCurrentRoom] = useState<string | null>(getRoomCode());

  const { circuit, selected, history, future } = state;
  const canUndo = history.length > 0;
  const canRedo = future.length > 0;

  // URL-based room auto-join: visiting /?room=ABC123 joins that room on load.
  useEffect(() => {
    const url = new URL(window.location.href);
    const code = url.searchParams.get("room");
    if (code && code !== currentRoom) {
      setRoom(code);
      setCurrentRoom(code);
      toast.success(`Joined room ${code} from URL`);
      // Don't reload here — the App's collab.connect effect already picks up the new sid
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runSim() {
    if (!circuit.gates.length) return;
    setSimming(true);
    try {
      const r = await simulate(circuit);
      if (r.success) {
        actions.setSimOutputs(r.outputs);
        toast.success(`Simulation complete — ${Object.keys(r.outputs).length} outputs computed`);
      } else {
        toast.error(`Simulation error: ${r.error}`);
      }
    } catch {
      toast.error("Backend offline — start the Flask server");
    } finally {
      setSimming(false);
    }
  }

  async function doSave() {
    setSaving(true);
    try {
      await saveCircuit(saveName.trim() || "circuit", circuit);
      toast.success(`Saved as "${saveName}"`);
      setShowSave(false);
    } catch {
      toast.error("Save failed — check backend connection");
    } finally {
      setSaving(false);
    }
  }

  async function openLoad() {
    try {
      setCircuits(await listAllCircuits());
    } catch {
      setCircuits({ mine: [], examples: [] });
    }
    setShowLoad(true);
  }

  function joinRoom() {
    const code = roomInput.trim().toUpperCase();
    setRoom(code);
    setCurrentRoom(code || null);
    setShowRoom(false);
    setRoomInput("");
    toast.success(code ? `Joined room: ${code}` : "Switched to private session");
    // Sync the URL ?room= param so a Leave (code === "") doesn't get
    // auto-rejoined by the URL-auto-join effect on next reload.
    const url = new URL(window.location.href);
    if (code) url.searchParams.set("room", code);
    else      url.searchParams.delete("room");
    window.history.replaceState({}, "", url.toString());
    // Force a reload so the WebSocket reconnects with the new session id.
    setTimeout(() => window.location.reload(), 300);
  }

  async function createNewRoom() {
    try {
      const res = await fetch("/api/rooms/new", {
        method: "POST",
        headers: { "X-Session-Id": getSessionId() },
      });
      const data = await res.json();
      if (data.code) {
        setRoomInput(data.code);
        // Remember owner status (localStorage hint) and save the owner_token
        // so the server keeps recognising us as host after setRoom() below
        // rewrites our session_id.
        markRoomOwned(data.code);
        if (data.owner_token) saveOwnerToken(data.code, data.owner_token);
        // Auto-join the new room and update the URL so it's shareable.
        setRoom(data.code);
        setCurrentRoom(data.code);
        const url = new URL(window.location.href);
        url.searchParams.set("room", data.code);
        window.history.replaceState({}, "", url.toString());
        toast.success(`Created room ${data.code} — copy the URL to invite people`);
        setTimeout(() => window.location.reload(), 300);
      }
    } catch {
      toast.error("Could not create room — backend offline");
    }
  }

  function copyRoomLink() {
    const code = currentRoom;
    if (!code) return;
    const url = `${window.location.origin}/?room=${code}`;
    navigator.clipboard?.writeText(url).then(
      () => toast.success(`Copied ${url}`),
      () => toast.error("Could not copy — select and copy manually"),
    );
  }

  async function doLoad(name: string) {
    try {
      const r = await loadCircuit(name);
      actions.setCircuit(r.circuit);
      onCircuitLoaded();
      toast.success(`Loaded "${name}"`);
    } catch {
      toast.error(`Failed to load "${name}"`);
    }
    setShowLoad(false);
  }

  function confirmClear() {
    if (circuit.gates.length === 0) return;
    if (!window.confirm("Clear the canvas? This cannot be undone.")) return;
    actions.clear();
    actions.clearSimOutputs();
    toast.info("Canvas cleared");
  }

  return (
    <>
      <header className="h-12 bg-bg-800 border-b border-bg-600 flex items-center px-3 gap-1 flex-shrink-0 overflow-x-auto">

        {/* Logo */}
        <div className="flex items-center gap-2 mr-3 flex-shrink-0">
          <div className="w-7 h-7 rounded-lg bg-accent flex items-center justify-center text-white text-[10px] font-black tracking-tight shadow-md shadow-accent/30">
            LG
          </div>
          <span className="text-xs font-bold text-gray-100 font-mono whitespace-nowrap">LogicGate</span>
        </div>

        <Divider />

        {/* Tools */}
        <ToolBtn icon={<MousePointer2 size={13} />} label="Select" title="Select / Move (S)"
          active={tool === "select"} onClick={() => setTool("select")} />
        <ToolBtn icon={<Spline size={13} />}        label="Wire"   title="Wire mode (W)"
          active={tool === "wire"}   onClick={() => setTool("wire")} />
        <ToolBtn icon={<Hand size={13} />}          label="Pan"    title="Pan canvas (H)"
          active={tool === "hand"}   onClick={() => setTool("hand")} />

        <Divider />

        {/* Edit */}
        <ToolBtn icon={<Undo2 size={13} />} title="Undo (Ctrl+Z)"
          disabled={!canUndo} onClick={actions.undo} />
        <ToolBtn icon={<Redo2 size={13} />} title="Redo (Ctrl+Y)"
          disabled={!canRedo} onClick={actions.redo} />
        <ToolBtn icon={<Trash2 size={13} />} title="Delete selected (Del)"
          disabled={selected.size === 0} variant="danger" onClick={actions.removeSelected} />
        <ToolBtn icon={<Square size={13} />} title="Clear canvas"
          disabled={circuit.gates.length === 0} onClick={confirmClear} />

        <Divider />

        {/* Grid */}
        <ToolBtn icon={<Grid3x3 size={13} />} label={`Snap ${snapGrid ? "On" : "Off"}`}
          title="Toggle snap-to-grid" active={snapGrid}
          onClick={() => setSnapGrid(!snapGrid)} />

        {/* Fit-to-view — pan & zoom so the whole circuit is visible */}
        <ToolBtn icon={<Maximize2 size={13} />} label="Fit"
          title="Fit all gates in view"
          disabled={circuit.gates.length === 0}
          onClick={() => window.dispatchEvent(new CustomEvent("logicgate:fit-view"))} />

        <Divider />

        {/* Simulate */}
        <button
          onClick={runSim}
          disabled={simming || !circuit.gates.length}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-mono font-semibold border border-ok/50 text-ok hover:bg-ok/10 transition-all disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
          title="Run simulation (Ctrl+Enter)"
        >
          {simming
            ? <><Loader2 size={13} className="animate-spin" /> Running…</>
            : <><Play    size={13} /> Simulate</>}
        </button>
        <ToolBtn icon={<StopCircle size={13} />} label="Reset" title="Clear simulation results"
          variant="warning" onClick={actions.clearSimOutputs} />

        <Divider />

        {/* Save / Load / Examples */}
        <ToolBtn icon={<Save size={13} />}       label="Save"     title="Save circuit to YOUR session" onClick={() => setShowSave(true)} />
        <ToolBtn icon={<FolderOpen size={13} />} label="Load"     title="Load saved or example circuit" onClick={openLoad} />
        <ToolBtn icon={<Users size={13} />}      label={currentRoom ? `Room: ${currentRoom}` : "Solo"}
          title="Join a shared room — everyone in the same room sees the same saved circuits"
          variant={currentRoom ? "primary" : "default"}
          onClick={() => setShowRoom(true)} />

        <div className="flex-1 min-w-4" />

        {/* Stats */}
        <span className="text-[9px] text-gray-600 font-mono whitespace-nowrap mr-2 hidden sm:block">
          {circuit.gates.length}g · {circuit.wires.length}w
          {selected.size > 0 && <span className="text-accent ml-1">· {selected.size} sel</span>}
        </span>

        {/* Live presence — shows other people editing the same room */}
        <PresenceBadge />

        {/* Backend status */}
        <div className="flex items-center gap-1.5 flex-shrink-0" title={backendOk === true ? "Backend online" : backendOk === false ? "Backend offline" : "Connecting…"}>
          {backendOk === true  && <><Wifi     size={12} className="text-ok"  /><span className="text-[9px] font-mono text-ok  hidden md:block">online</span></>}
          {backendOk === false && <><WifiOff  size={12} className="text-err" /><span className="text-[9px] font-mono text-err hidden md:block">offline</span></>}
          {backendOk === null  && <Loader2    size={12} className="text-gray-600 animate-spin" />}
        </div>

        {/* Identity chip — display name (or "guest") + click to sign out */}
        <UserChip />
      </header>

      {/* ── Save modal ── */}
      {showSave && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50"
          onClick={() => setShowSave(false)}>
          <div className="bg-bg-800 border border-bg-600 rounded-xl p-5 w-72 space-y-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <span className="text-sm font-mono font-bold text-gray-100">Save circuit</span>
              <button onClick={() => setShowSave(false)} className="text-gray-600 hover:text-gray-300">
                <X size={14} />
              </button>
            </div>
            <input
              className="w-full bg-bg-700 border border-bg-600 rounded-lg px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-accent transition-colors"
              placeholder="circuit-name"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && doSave()}
              autoFocus
            />
            <div className="flex gap-2">
              <button onClick={doSave} disabled={saving}
                className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-mono font-semibold disabled:opacity-50 transition-colors">
                {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                {saving ? "Saving…" : "Save"}
              </button>
              <button onClick={() => setShowSave(false)}
                className="flex-1 py-2 rounded-lg bg-bg-700 hover:bg-bg-600 text-gray-400 text-xs font-mono border border-bg-600 transition-colors">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Load modal ── */}
      {showLoad && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50"
          onClick={() => setShowLoad(false)}>
          <div className="bg-bg-800 border border-bg-600 rounded-xl p-5 w-80 space-y-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <span className="text-sm font-mono font-bold text-gray-100">Load circuit</span>
              <button onClick={() => setShowLoad(false)} className="text-gray-600 hover:text-gray-300">
                <X size={14} />
              </button>
            </div>
            <div className="max-h-[55vh] overflow-y-auto space-y-3">
              {/* My circuits (per-session) */}
              <div>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <Save size={10} className="text-accent" />
                  <span className="text-[9px] uppercase tracking-widest font-mono text-gray-500">
                    My circuits {currentRoom ? `(room ${currentRoom})` : "(private session)"}
                  </span>
                </div>
                {circuits.mine.length === 0 ? (
                  <div className="py-3 px-3 text-[10px] text-gray-600 font-mono italic">
                    Nothing saved yet — click ▢ Save to add one.
                  </div>
                ) : (
                  <div className="space-y-1">
                    {circuits.mine.map((name) => (
                      <button key={name} onClick={() => doLoad(name)}
                        className="w-full text-left px-3 py-2 rounded bg-bg-700 hover:bg-bg-600 text-xs font-mono text-gray-200 border border-bg-600 hover:border-accent/40 transition-all">
                        {name}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Examples gallery (shared) */}
              <div className="border-t border-bg-600 pt-3">
                <div className="flex items-center gap-1.5 mb-1.5">
                  <BookOpen size={10} className="text-ok" />
                  <span className="text-[9px] uppercase tracking-widest font-mono text-gray-500">
                    Examples gallery
                  </span>
                </div>
                {circuits.examples.length === 0 ? (
                  <div className="py-3 px-3 text-[10px] text-gray-600 font-mono italic">
                    No example circuits installed.
                  </div>
                ) : (
                  <div className="space-y-1">
                    {circuits.examples.map((name) => (
                      <button key={name} onClick={() => doLoad(name)}
                        className="w-full text-left px-3 py-2 rounded bg-bg-700/50 hover:bg-bg-600 text-xs font-mono text-gray-300 border border-bg-600 hover:border-ok/40 transition-all flex items-center gap-2">
                        <BookOpen size={10} className="text-ok/70" />
                        {name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <button onClick={() => setShowLoad(false)}
              className="w-full py-2 rounded-lg bg-bg-700 hover:bg-bg-600 text-gray-400 text-xs font-mono border border-bg-600 transition-colors">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ── Room / collaboration modal ── */}
      {showRoom && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50"
          onClick={() => setShowRoom(false)}>
          <div className="bg-bg-800 border border-bg-600 rounded-xl p-5 w-96 space-y-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Users size={14} className="text-accent" />
                <span className="text-sm font-mono font-bold text-gray-100">Rooms & sessions</span>
              </div>
              <button onClick={() => setShowRoom(false)} className="text-gray-600 hover:text-gray-300">
                <X size={14} />
              </button>
            </div>

            <div className="text-[10px] font-mono text-gray-500 leading-relaxed space-y-1.5">
              <p>Multiple people can use this app at the same time without interrupting each other:</p>
              <p>
                <span className="text-accent">Solo</span> — your saved circuits stay private to your browser.
              </p>
              <p>
                <span className="text-ok">Room</span> — everyone who joins the same room code shares the same saved circuits. Great for class groups.
              </p>
              <p className="text-gray-600 pt-1">
                Current session id: <span className="font-bold text-gray-400">{getSessionId()}</span>
              </p>
            </div>

            {/* Create new room */}
            <div>
              <div className="text-[9px] font-mono uppercase tracking-widest text-gray-600 mb-1.5">
                Start a new collaboration
              </div>
              <button onClick={createNewRoom}
                className="w-full py-2.5 rounded-lg bg-ok/15 hover:bg-ok/25 text-ok text-xs font-mono font-bold border border-ok/30 hover:border-ok/50 transition-colors">
                ✨ Create new room (auto-generates 6-character code)
              </button>
              <p className="text-[9px] font-mono text-gray-600 mt-1.5">
                You'll get a code like <span className="text-accent">A7F2KQ</span> — share it or paste the URL.
              </p>
            </div>

            <div className="text-center text-[9px] font-mono text-gray-700 uppercase tracking-widest">— or —</div>

            {/* Join existing */}
            <div>
              <div className="text-[9px] font-mono uppercase tracking-widest text-gray-600 mb-1.5">
                Join by code
              </div>
              <input
                className="w-full bg-bg-700 border border-bg-600 rounded-lg px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-accent transition-colors uppercase"
                placeholder="A7F2KQ"
                value={roomInput}
                onChange={(e) => setRoomInput(e.target.value.toUpperCase())}
                onKeyDown={(e) => e.key === "Enter" && joinRoom()}
                maxLength={12}
              />
            </div>

            {/* Current room actions */}
            {currentRoom && (
              <CurrentRoomBlock
                currentRoom={currentRoom}
                onCopy={copyRoomLink}
                onLeave={() => { setRoomInput(""); joinRoom(); }}
              />
            )}

            <div className="flex gap-2">
              <button onClick={() => setShowRoom(false)}
                className="flex-1 py-2 rounded-lg bg-bg-700 hover:bg-bg-600 text-gray-400 text-xs font-mono border border-bg-600">
                Cancel
              </button>
              {roomInput.trim() && roomInput.trim().toUpperCase() !== currentRoom && (
                <button onClick={joinRoom}
                  className="flex-1 py-2 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-mono font-bold">
                  Join "{roomInput.trim().toUpperCase()}"
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}


/* ─── Current-room block: copy link, leave, plus host controls ───────────── */
function CurrentRoomBlock(
  { currentRoom, onCopy, onLeave }:
  { currentRoom: string; onCopy: () => void; onLeave: () => void }
) {
  const [maxUsers, setMaxUsers]   = useState<number>(20);
  const [editing,  setEditing]    = useState<boolean>(false);
  const [pending,  setPending]    = useState<number>(20);
  const [error,    setError]      = useState<string | null>(null);
  // Trust the server's is_owner — works across devices when signed in,
  // falls back to localStorage flag when offline.
  const [serverIsOwner, setServerIsOwner] = useState<boolean | null>(null);
  const isOwner = serverIsOwner ?? isRoomOwner(currentRoom);

  useEffect(() => {
    let alive = true;
    {
      const tok = getOwnerToken(currentRoom);
      fetch(`/api/rooms/${encodeURIComponent(currentRoom)}`, {
        headers: {
          "X-Session-Id": getSessionId(),
          ...(tok ? { "X-Owner-Token": tok } : {}),
        },
      })
        .then((r) => r.json())
        .then((d) => {
          if (!alive) return;
          if (d?.max_users) {
            setMaxUsers(d.max_users);
            setPending(d.max_users);
          }
          if (typeof d?.is_owner === "boolean") setServerIsOwner(d.is_owner);
        })
        .catch(() => {/* offline — keep default */});
    }
    return () => { alive = false; };
  }, [currentRoom]);

  async function saveCap() {
    if (pending < 2 || pending > 100) {
      setError("Cap must be between 2 and 100");
      return;
    }
    setError(null);
    try {
      const tok = getOwnerToken(currentRoom);
      const res = await fetch(`/api/rooms/${encodeURIComponent(currentRoom)}/config`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Session-Id": getSessionId(),
          ...(tok ? { "X-Owner-Token": tok } : {}),
        },
        body: JSON.stringify({ max_users: pending }),
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        setError(data.message || "Update failed");
        return;
      }
      setMaxUsers(pending);
      setEditing(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="bg-bg-700/40 border border-bg-600 rounded-lg p-3 space-y-2">
      <div className="text-[9px] font-mono uppercase tracking-widest text-gray-500">
        Currently in room: <span className="text-accent">{currentRoom}</span>
        {isOwner && <span className="ml-1 text-accent/70">(host)</span>}
      </div>
      <div className="text-[9px] font-mono text-gray-500 flex items-center gap-2">
        <span>Max users:</span>
        {!editing ? (
          <>
            <span className="text-gray-300">{maxUsers}</span>
            {isOwner && (
              <button onClick={() => setEditing(true)}
                className="text-accent/70 hover:text-accent text-[9px] underline">
                change
              </button>
            )}
          </>
        ) : (
          <>
            <input type="number" min={2} max={100} value={pending}
              onChange={(e) => setPending(Math.max(2, Math.min(100, Number(e.target.value) || 2)))}
              className="w-14 bg-bg-800 border border-bg-600 rounded px-1.5 py-0.5 text-[10px] text-gray-200" />
            <button onClick={saveCap}
              className="px-2 py-0.5 rounded bg-accent/25 text-accent text-[9px] hover:bg-accent/40">save</button>
            <button onClick={() => { setEditing(false); setPending(maxUsers); }}
              className="px-2 py-0.5 rounded bg-bg-800 text-gray-500 text-[9px] hover:text-gray-300">cancel</button>
          </>
        )}
      </div>
      {error && <div className="text-[8px] font-mono text-err">{error}</div>}
      <div className="flex gap-2">
        <button onClick={onCopy}
          className="flex-1 py-1.5 rounded bg-accent/15 hover:bg-accent/25 text-accent text-[10px] font-mono font-semibold border border-accent/30">
          📋 Copy invite link
        </button>
        <button onClick={onLeave}
          className="px-3 py-1.5 rounded bg-bg-800 hover:bg-err/20 text-gray-400 hover:text-err text-[10px] font-mono border border-bg-600">
          Leave
        </button>
      </div>
      {isOwner && <MembersList currentRoom={currentRoom} />}
    </div>
  );
}


/** Inline member list shown inside the Room dialog when the caller is the
 * host. Each peer has a big visible Kick button. */
function MembersList({ currentRoom }: { currentRoom: string }) {
  const [users, setUsers] = useState<{ sid: string; name: string; color: string }[]>([]);
  const [kickingSid, setKickingSid] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => collab.onPresence(setUsers as any), []);

  const ownSid = collab.ownSid();
  const peers  = users.filter((u) => u.sid !== ownSid);

  async function handleKick(sid: string, name: string) {
    if (!confirm(`Remove ${name || "this user"} from room ${currentRoom}?`)) return;
    setKickingSid(sid);
    setError(null);
    try {
      await kickFromRoom(currentRoom, sid);
    } catch (e) {
      setError(`Kick failed: ${(e as Error).message}`);
    } finally {
      setKickingSid(null);
    }
  }

  return (
    <div className="pt-2 mt-2 border-t border-bg-600 space-y-1.5">
      <div className="text-[9px] font-mono uppercase tracking-widest text-accent">
        👑 Host controls — members ({users.length})
      </div>
      {peers.length === 0 && (
        <div className="text-[9px] font-mono text-gray-600 italic">
          No one else has joined yet. Copy the invite link above.
        </div>
      )}
      {peers.map((u) => (
        <div key={u.sid} className="flex items-center gap-2 bg-bg-800 border border-bg-600 rounded px-2 py-1.5">
          <div className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold"
               style={{ backgroundColor: u.color, color: "#0d0d18" }}>
            {(u.name || "?")[0].toUpperCase()}
          </div>
          <span className="flex-1 text-[10px] font-mono text-gray-200 truncate">{u.name || "guest"}</span>
          <button
            onClick={() => handleKick(u.sid, u.name)}
            disabled={kickingSid === u.sid}
            className="px-2 py-1 rounded bg-err/15 hover:bg-err/30 text-err text-[9px] font-mono font-semibold border border-err/30 disabled:opacity-40"
          >
            {kickingSid === u.sid ? "Kicking…" : "Kick"}
          </button>
        </div>
      ))}
      {error && <div className="text-[8px] font-mono text-err">{error}</div>}
    </div>
  );
}
