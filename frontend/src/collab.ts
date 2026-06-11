/**
 * Real-time collaboration over WebSocket.
 *
 * Each browser opens one Socket.IO connection to /collab and joins the same
 * room the REST API uses (the X-Session-Id value). When the local user adds,
 * moves or deletes anything, we emit an `op` event. When peers do the same,
 * the server relays it back and we dispatch the same Action into the store.
 *
 * Public API:
 *   collab.connect(room, name)   — open the socket
 *   collab.disconnect()
 *   collab.broadcast(action)     — send a local Action to peers
 *   collab.onRemote(handler)     — register a callback for incoming peer Actions
 *   collab.onPresence(handler)   — register a callback for roster changes
 */
import { io, Socket } from "socket.io-client";
import type { Gate, Wire, Circuit } from "./types";

export type RemoteOp =
  | { kind: "add_gate";       payload: { gate: Gate } }
  | { kind: "move_gate";      payload: { id: string; x: number; y: number } }
  | { kind: "remove_gate";    payload: { id: string } }
  | { kind: "set_gate_value"; payload: { id: string; value: 0 | 1 } }
  | { kind: "add_wire";       payload: { wire: Wire } }
  | { kind: "remove_wire";    payload: { id: string } }
  | { kind: "set_circuit";    payload: { circuit: Circuit } }
  | { kind: "clear_circuit";  payload: {} }
  | { kind: "cursor";         payload: { x: number; y: number } };

export interface PresenceUser {
  sid:   string;
  name:  string;
  color: string;
}

type RemoteHandler   = (op: RemoteOp & { from: string }) => void;
type PresenceHandler = (users: PresenceUser[]) => void;
type KickedHandler   = (info: { room: string; reason: string }) => void;

class CollabClient {
  private socket: Socket | null = null;
  private remoteHandlers:   Set<RemoteHandler>   = new Set();
  private presenceHandlers: Set<PresenceHandler> = new Set();
  private kickedHandlers:   Set<KickedHandler>   = new Set();
  private currentRoom: string | null = null;
  private mySid: string | null = null;
  /** Suppress broadcast for the next applied op — used when re-applying a
   *  remote op locally so it doesn't bounce back to the peer. */
  private suppress = false;

  connect(room: string, name: string) {
    if (this.socket && this.currentRoom === room) {
      // Already connected to this room.
      return;
    }
    if (this.socket) {
      this.disconnect();
    }
    this.currentRoom = room;

    const s = io("/collab", {
      // Both transports — falls back to long-polling if WebSocket is blocked
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionDelay: 1000,
      withCredentials: true,
    });

    s.on("connect", () => {
      this.mySid = s.id || null;
      s.emit("join", { room, name });
    });

    s.on("kicked", (info: { room: string; reason: string }) => {
      this.kickedHandlers.forEach((h) => h(info));
    });

    // The server also emits "banned" when a previously-kicked client tries
    // to rejoin. Treat it identically — kicks the user back out of the room.
    s.on("banned", (info: { room: string; reason: string }) => {
      this.kickedHandlers.forEach((h) => h(info));
    });

    s.on("presence", (data: { users: PresenceUser[] }) => {
      this.presenceHandlers.forEach((h) => h(data.users || []));
    });

    s.on("op", (data: RemoteOp & { from: string }) => {
      this.suppress = true;
      try {
        this.remoteHandlers.forEach((h) => h(data));
      } finally {
        this.suppress = false;
      }
    });

    s.on("disconnect", () => {
      // Server-side disconnect: clear the roster.
      this.presenceHandlers.forEach((h) => h([]));
    });

    s.on("connect_error", (err) => {
      console.warn("[collab] connection error", err.message);
    });

    this.socket = s;
  }

  disconnect() {
    if (this.socket) {
      try { this.socket.emit("leave"); } catch {}
      this.socket.disconnect();
      this.socket = null;
    }
    this.currentRoom = null;
    this.mySid = null;
    this.presenceHandlers.forEach((h) => h([]));
  }

  /** Send a local op to peers. No-op if not connected. */
  broadcast(op: RemoteOp) {
    if (this.suppress) return;       // remote-applied, don't echo
    if (!this.socket || !this.socket.connected) return;
    this.socket.emit("op", op);
  }

  onRemote(h: RemoteHandler): () => void {
    this.remoteHandlers.add(h);
    return () => { this.remoteHandlers.delete(h); };
  }

  onPresence(h: PresenceHandler): () => void {
    this.presenceHandlers.add(h);
    return () => { this.presenceHandlers.delete(h); };
  }

  onKicked(h: KickedHandler): () => void {
    this.kickedHandlers.add(h);
    return () => { this.kickedHandlers.delete(h); };
  }

  isConnected() {
    return !!this.socket?.connected;
  }

  currentRoomName() {
    return this.currentRoom;
  }

  /** Socket ID of *this* client. null until the connect handshake finishes. */
  ownSid(): string | null {
    return this.mySid;
  }
}

export const collab = new CollabClient();
