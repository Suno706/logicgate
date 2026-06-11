import { useEffect, useState } from "react";
import { collab, type PresenceUser } from "../collab";
import { Users } from "lucide-react";
import { getRoomCode, isRoomOwner, kickFromRoom, fetchRoomInfo } from "../api";

/**
 * Shows a badge listing everyone in the current room (including yourself).
 * Visible whenever the user is in a named room — even when alone — so they
 * can see at a glance that the room is live and who has joined.
 */
export function PresenceBadge() {
  const [users, setUsers] = useState<PresenceUser[]>([]);
  const [open,  setOpen]  = useState(false);
  const [serverIsOwner, setServerIsOwner] = useState<boolean | null>(null);

  useEffect(() => collab.onPresence(setUsers), []);

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
    if (!confirm(`Remove ${name || "this user"} from room ${code}?`)) return;
    try {
      await kickFromRoom(code, sid);
    } catch (e) {
      alert(`Kick failed: ${(e as Error).message}`);
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
        <div className="absolute right-0 mt-1.5 w-72 z-50 bg-bg-800 border border-bg-600 rounded-lg shadow-xl p-1.5 text-xs">
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
              {isOwner && (
                <button
                  onClick={() => handleKick(u.sid, u.name)}
                  className="px-2 py-0.5 rounded text-[10px] font-medium text-gray-500 hover:text-err hover:bg-err/10 border border-bg-600 hover:border-err/30 transition-colors flex-shrink-0"
                  title="Remove this user from the room"
                >
                  Remove
                </button>
              )}
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
