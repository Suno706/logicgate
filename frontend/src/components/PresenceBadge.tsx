import { useEffect, useState } from "react";
import { collab, type PresenceUser } from "../collab";
import { Users, Loader2 } from "lucide-react";
import { getRoomCode, isRoomOwner, kickFromRoom, fetchRoomInfo } from "../api";
import { useToast } from "./Toast";

/**
 * Shows a badge listing everyone in the current room (including yourself).
 * Visible whenever the user is in a named room — even when alone — so they
 * can see at a glance that the room is live and who has joined.
 */
export function PresenceBadge() {
  const [users, setUsers] = useState<PresenceUser[]>([]);
  const [open,  setOpen]  = useState(false);
  const [serverIsOwner, setServerIsOwner] = useState<boolean | null>(null);
  // sid -> 'pending' | 'kicked' lets the row render a spinner while the
  // API is mid-flight, and an optimistic "Removed" state once it returns.
  // Without this the host clicks Remove and the dropdown looks frozen
  // until the next presence broadcast lands, which is what felt
  // "half-cooked" to the user.
  const [kickStatus, setKickStatus] = useState<Record<string, "pending" | "kicked">>({});
  const toast = useToast();

  useEffect(() => collab.onPresence((next) => {
    setUsers(next);
    // Clean up kick status entries for sids that are no longer in the
    // roster — they've actually left, so the "Removed" badge can go.
    setKickStatus((cur) => {
      const inRoom = new Set(next.map((u) => u.sid));
      const out: Record<string, "pending" | "kicked"> = {};
      for (const [sid, st] of Object.entries(cur)) {
        if (inRoom.has(sid)) out[sid] = st;
      }
      return out;
    });
  }), []);

  const code = getRoomCode();

  useEffect(() => {
    if (!code) { setServerIsOwner(null); return; }
    let alive = true;
    fetchRoomInfo(code).then((info) => {
      if (alive) setServerIsOwner(info.is_owner);
    }).catch(() => { /* offline */ });
    return () => { alive = false; };
  }, [code]);

  // Show the badge whenever we're in a named room, even alone.
  if (!code) return null;

  const ownSid = collab.ownSid();
  const peers  = users.filter((u) => u.sid !== ownSid);
  const me     = users.find((u) => u.sid === ownSid);
  const total  = users.length;

  const isOwner = serverIsOwner ?? isRoomOwner(code);

  async function handleKick(sid: string, name: string) {
    if (!code) return;
    // Guard against double-tap firing two requests
    if (kickStatus[sid]) return;
    // We keep a confirm() here because Remove is destructive and a custom
    // modal would be heavier than this UX needs. If the design team
    // later wants an inline toast-confirm pattern, swap here.
    if (!confirm(`Remove ${name || "this user"} from room ${code}?\n\nThey'll be disconnected immediately and can't rejoin until you invite them back.`)) return;

    setKickStatus((m) => ({ ...m, [sid]: "pending" }));
    try {
      const res = await kickFromRoom(code, sid);
      if (res.success && res.kicked) {
        toast.success(`${name || "User"} removed from room.`);
        setKickStatus((m) => ({ ...m, [sid]: "kicked" }));
      } else if (res.success && !res.kicked) {
        // Server accepted the call but the target wasn't actually in the
        // room socket — most often because they already left. Either
        // way, the user is gone from the host's point of view.
        toast.info(`${name || "User"} was no longer in the room.`);
        setKickStatus((m) => ({ ...m, [sid]: "kicked" }));
      }
    } catch (e) {
      const msg = (e as Error).message || "Kick failed";
      toast.error(`Couldn't remove ${name || "user"}: ${msg}`);
      setKickStatus((m) => {
        const next = { ...m };
        delete next[sid];
        return next;
      });
    }
  }

  // Choose label color: green when 2+ are present (live), gray when alone.
  const live = total >= 2;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-1.5 px-2 py-1 rounded-md bg-bg-700 border ${
          isOwner ? "border-accent text-accent" : "border-bg-600 hover:border-accent"
        }`}
        title={
          isOwner
            ? `Host controls — ${total} ${total === 1 ? "person" : "people"} in room ${code}${peers.length ? " (click to kick)" : ""}`
            : `In room ${code} — ${total} ${total === 1 ? "person" : "people"}`
        }
      >
        <Users size={12} className={live ? "text-ok" : "text-accent"} />
        <span className="text-[11px] font-mono font-semibold text-gray-100 tracking-tight">
          {code}
        </span>
        <span className={`text-[11px] font-medium ${live ? "text-ok" : "text-gray-500"}`}>
          · {total}
        </span>
        {/* Avatar stack */}
        {users.length > 0 && (
          <div className="flex items-center -space-x-1.5 ml-0.5">
            {users.slice(0, 4).map((u) => (
              <div key={u.sid}
                className="w-4 h-4 rounded-full border border-bg-800 flex items-center justify-center text-[7px] font-mono font-bold"
                style={{ backgroundColor: u.color, color: "#0d0d18" }}>
                {(u.name || "?")[0].toUpperCase()}
              </div>
            ))}
            {users.length > 4 && (
              <div className="w-4 h-4 rounded-full border border-bg-800 bg-bg-700 flex items-center justify-center text-[6px] font-mono text-gray-400">
                +{users.length - 4}
              </div>
            )}
          </div>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 mt-1.5 z-50 bg-bg-800 border border-bg-600 rounded-lg shadow-xl p-1.5 text-xs"
          style={{
            // On phones the host's presence dropdown was anchored to the
            // badge, which sits mid-toolbar. A fixed w-72 (288px) would
            // extend off-screen on the left. Clamp to viewport width so
            // it always fits and stays tappable.
            width: "min(288px, 90vw)",
          }}>
          <div className="flex items-center justify-between px-2 py-1.5 border-b border-bg-600 mb-1">
            <span className="text-[11px] text-gray-400">
              Room <span className="font-mono font-semibold text-gray-100">{code}</span>
            </span>
            {isOwner && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent/15 text-accent font-medium">
                Host
              </span>
            )}
          </div>
          {users.length === 0 && (
            <div className="px-2 py-2 text-gray-500 italic text-[11px]">
              Connecting…
            </div>
          )}
          {me && (
            <div className="flex items-center gap-2 px-2 py-1.5 bg-bg-700/40 rounded">
              <div className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold"
                   style={{ backgroundColor: me.color, color: "#0d0d18" }}>
                {(me.name || "?")[0].toUpperCase()}
              </div>
              <span className="flex-1 truncate text-[12px] text-gray-100">
                {me.name || "guest"} <span className="text-gray-500 text-[11px]">· you</span>
              </span>
            </div>
          )}
          {peers.map((u) => (
            <div key={u.sid} className="group flex items-center gap-2 px-2 py-1.5 hover:bg-bg-700/60 rounded">
              <div className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold"
                   style={{ backgroundColor: u.color, color: "#0d0d18" }}>
                {(u.name || "?")[0].toUpperCase()}
              </div>
              <span className="flex-1 truncate text-[12px] text-gray-200">{u.name || "guest"}</span>
              {isOwner && (() => {
                const st = kickStatus[u.sid];
                if (st === "pending") {
                  return (
                    <span className="px-2 py-0.5 rounded text-[10px] font-medium text-gray-500 border border-bg-600 flex items-center gap-1 flex-shrink-0">
                      <Loader2 size={11} className="animate-spin" /> Removing
                    </span>
                  );
                }
                if (st === "kicked") {
                  return (
                    <span className="px-2 py-0.5 rounded text-[10px] font-medium text-gray-600 border border-bg-600 flex-shrink-0 italic">
                      Removed
                    </span>
                  );
                }
                return (
                  <button
                    onClick={() => handleKick(u.sid, u.name)}
                    className="px-2 py-0.5 rounded text-[10px] font-medium text-gray-500 hover:text-err hover:bg-err/10 border border-bg-600 hover:border-err/30 transition-colors flex-shrink-0"
                    title="Remove this user from the room — they'll be disconnected and banned until you invite them back"
                  >
                    Remove
                  </button>
                );
              })()}
            </div>
          ))}
          {peers.length === 0 && users.length > 0 && (
            <div className="px-2 py-1.5 text-gray-500 italic text-[11px]">
              You're the only one here. Share the invite link to bring others in.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
