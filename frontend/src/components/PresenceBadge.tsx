import { useEffect, useState } from "react";
import { collab, type PresenceUser } from "../collab";
import { Users, X } from "lucide-react";
import { getRoomCode, isRoomOwner, kickFromRoom, fetchRoomInfo } from "../api";

/**
 * Shows a small badge listing other people currently in the same room.
 * Hidden when alone (no peers). Room owner sees a kick button next to each
 * peer when hovered.
 */
export function PresenceBadge() {
  const [users, setUsers] = useState<PresenceUser[]>([]);
  const [open,  setOpen]  = useState(false);
  const [serverIsOwner, setServerIsOwner] = useState<boolean | null>(null);

  useEffect(() => collab.onPresence(setUsers), []);

  const code = getRoomCode();
  // Server-trusted owner check (survives clearing browser, works across devices
  // when the user is signed in).
  useEffect(() => {
    if (!code) { setServerIsOwner(null); return; }
    let alive = true;
    fetchRoomInfo(code).then((info) => {
      if (alive) setServerIsOwner(info.is_owner);
    }).catch(() => { /* offline — fall back to localStorage */ });
    return () => { alive = false; };
  }, [code]);

  // "users" includes the current user. Strip the local sid.
  const ownSid = collab.ownSid();
  const peers  = users.filter((u) => u.sid !== ownSid);
  if (peers.length === 0) return null;

  // Server has the final word; fall back to localStorage if offline.
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

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-1.5 px-2 py-1 rounded-md bg-bg-700 border ${
          isOwner ? "border-accent text-accent" : "border-bg-600 hover:border-accent"
        }`}
        title={isOwner
          ? `Host controls — click to see members and kick (${peers.length} ${peers.length === 1 ? "person" : "people"} in room)`
          : `${peers.length} ${peers.length === 1 ? "person" : "people"} editing this room with you`}
      >
        <Users size={11} className="text-accent" />
        <div className="flex items-center -space-x-1.5">
          {peers.slice(0, 4).map((u) => (
            <div key={u.sid}
              className="w-5 h-5 rounded-full border-2 border-bg-800 flex items-center justify-center text-[8px] font-mono font-bold"
              style={{ backgroundColor: u.color, color: "#0d0d18" }}>
              {(u.name || "?")[0].toUpperCase()}
            </div>
          ))}
          {peers.length > 4 && (
            <div className="w-5 h-5 rounded-full border-2 border-bg-800 bg-bg-700 flex items-center justify-center text-[8px] font-mono text-gray-400">
              +{peers.length - 4}
            </div>
          )}
        </div>
      </button>

      {open && (
        <div className="absolute right-0 mt-1 w-56 z-50 bg-bg-800 border border-bg-600 rounded-md shadow-lg p-2 text-xs">
          <div className="px-2 py-1 text-gray-400 uppercase tracking-wide">
            In room {code || "—"} {isOwner && <span className="text-accent">(host)</span>}
          </div>
          {peers.map((u) => (
            <div key={u.sid} className="flex items-center gap-2 px-2 py-1.5 hover:bg-bg-700 rounded">
              <div className="w-4 h-4 rounded-full flex items-center justify-center text-[7px] font-bold"
                   style={{ backgroundColor: u.color, color: "#0d0d18" }}>
                {(u.name || "?")[0].toUpperCase()}
              </div>
              <span className="flex-1 truncate">{u.name || "guest"}</span>
              {isOwner && (
                <button
                  onClick={() => handleKick(u.sid, u.name)}
                  className="p-1 rounded hover:bg-red-600/30 text-red-400"
                  title="Remove from room"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
