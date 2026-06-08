import { useEffect, useState } from "react";
import { collab, type PresenceUser } from "../collab";
import { Users } from "lucide-react";

/**
 * Shows a small badge listing other people currently in the same room.
 * Hidden when alone (no peers).
 */
export function PresenceBadge() {
  const [users, setUsers] = useState<PresenceUser[]>([]);

  useEffect(() => {
    return collab.onPresence(setUsers);
  }, []);

  // "users" includes the current user. Strip the local sid by counting only
  // foreign sids — we don't have our own sid easily here, so just show all
  // OTHER users by detecting size > 1.
  const peers = users.length > 1 ? users : [];

  if (peers.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-bg-700 border border-bg-600"
      title={`${peers.length} ${peers.length === 1 ? "person" : "people"} editing this room with you`}>
      <Users size={11} className="text-accent" />
      <div className="flex items-center -space-x-1.5">
        {peers.slice(0, 4).map((u) => (
          <div key={u.sid}
            className="w-5 h-5 rounded-full border-2 border-bg-800 flex items-center justify-center text-[8px] font-mono font-bold"
            style={{ backgroundColor: u.color, color: "#0d0d18" }}
            title={u.name}>
            {(u.name || "?")[0].toUpperCase()}
          </div>
        ))}
        {peers.length > 4 && (
          <div className="w-5 h-5 rounded-full border-2 border-bg-800 bg-bg-700 flex items-center justify-center text-[8px] font-mono text-gray-400">
            +{peers.length - 4}
          </div>
        )}
      </div>
    </div>
  );
}
