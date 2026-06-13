"""
Real-time multiplayer for LogicGate — Flask-SocketIO server.

Architecture
------------
Each browser connects via Socket.IO and joins exactly one *room* (the same
room concept used by the REST API's `X-Session-Id` header). When a user
adds, moves, or deletes a gate or wire, the client emits an event; the
server broadcasts it to every OTHER client in the same room (skip_sid=self
so the originator doesn't get a feedback echo).

Events
------
  Client → server:
    join     {room, name, color}        → server sends current presence list back
    leave    {}
    op       {kind, payload}            → kind ∈ {add_gate, move_gate, remove_gate,
                                          add_wire, remove_wire, set_value, set_circuit}
                                          payload mirrors the same shape as the
                                          frontend's reducer Actions.

  Server → client:
    presence {users: [{sid, name, color}]}     — broadcast whenever roster changes
    op       {kind, payload, from: sid}         — relays operations to peers
    error    {message}

The server is purely a relay — it does not maintain canonical circuit state.
Each client owns its local store; convergence is best-effort. For most class /
group use this is fine; the rare case where two clients add a gate at the
exact same instant will produce two gates with different ids (intentional).
"""
from __future__ import annotations
import logging
import time
from collections import defaultdict
from typing import Dict, List, Set

from flask import request
from flask_socketio import SocketIO, emit, join_room, leave_room

log = logging.getLogger("logicgate.realtime")

# Per-room user roster: room_name -> list of {sid, name, color, joined_at}
_rosters: Dict[str, List[dict]] = defaultdict(list)
# sid -> room (so disconnect knows which room to remove from)
_sid_room: Dict[str, str] = {}
# sid -> client IP, captured at join time. IP bans are a fallback for the
# rare case where a kicked user clears localStorage to drop their device id.
_sid_ip: Dict[str, str] = {}
# sid -> device_id sent by the client on join. This is the primary identity
# the kick system uses, because:
#   - IPs collide on shared WiFi / behind HF's proxy (one ban hits everyone)
#   - device_id is generated once per browser and persists across reloads,
#     so a kicked user trying to refresh their way back in is recognised
#     and re-rejected before they ever join the roster.
_sid_did: Dict[str, str] = {}
# Per-room ban lists, indexed two ways. A join is refused if it matches
# *either* set — device_id is checked first because it's the authoritative
# identity; IP is the backup.
_banned_devices: Dict[str, Set[str]] = defaultdict(set)
_banned_ips:     Dict[str, Set[str]] = defaultdict(set)
# Module-level handle to the live SocketIO instance, used by kick_socket().
_socketio = None


def _client_ip(req) -> str:
    """Pull the best-guess client IP from a Flask request. Trusts the first
    X-Forwarded-For hop (HF Spaces sets this), falling back to REMOTE_ADDR."""
    fwd = (req.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return fwd or req.remote_addr or ""

# A small palette of distinct colors so each user gets a unique cursor color.
_COLORS = [
    "#7c5cff", "#3ddc97", "#ff8844", "#44aaff", "#ffb454",
    "#ff5577", "#bb77ff", "#44ffaa", "#ff6b6b", "#4abb4a",
]


def _color_for(room: str, sid: str) -> str:
    """Deterministic-ish unique color per user in a room."""
    used = {u["color"] for u in _rosters[room]}
    for c in _COLORS:
        if c not in used:
            return c
    return _COLORS[hash(sid) % len(_COLORS)]


def _broadcast_presence(room: str):
    """Send the updated user list to everyone in the room."""
    users = [{"sid": u["sid"], "name": u["name"], "color": u["color"]}
             for u in _rosters[room]]
    emit("presence", {"users": users}, to=room)


def kick_socket(room: str, target_sid: str) -> bool:
    """Force-disconnect a user from a room. Used by the kick API endpoint.
    Emits a 'kicked' event to the target so the client can show a message,
    then drops them from the roster and forces a transport disconnect.
    Returns True if the target was found in the room.

    `room` may be the bare room CODE ("A7F2KQ") as the REST API uses, or
    the socket-room form the clients actually join ("room_a7f2kq")."""
    if _socketio is None:
        return False
    actual = _sid_room.get(target_sid)
    if actual is None:
        return False
    accepted = {room, f"room_{room.lower()}"}
    if actual not in accepted:
        return False
    room = actual    # use the real socket-room name from here on
    pretty = room[5:].upper() if room.startswith("room_") else room
    # Record both identities so a future join from this device is refused
    # regardless of how the client tries to reconnect:
    #   - device_id survives refresh + reconnect (the reliable path)
    #   - IP catches the case where a client somehow lost its device_id
    did = _sid_did.get(target_sid, "")
    if did:
        _banned_devices[room].add(did)
    ip = _sid_ip.get(target_sid, "")
    if ip:
        _banned_ips[room].add(ip)
    try:
        _socketio.emit("kicked", {"room": pretty, "reason": "Removed by host"},
                       to=target_sid, namespace="/collab")
    except Exception:
        pass
    _rosters[room] = [u for u in _rosters[room] if u["sid"] != target_sid]
    _sid_room.pop(target_sid, None)
    _sid_ip.pop(target_sid, None)
    _sid_did.pop(target_sid, None)
    try:
        _socketio.server.disconnect(target_sid, namespace="/collab")
    except Exception:
        pass
    # Tell the rest of the room someone left
    try:
        users = [{"sid": u["sid"], "name": u["name"], "color": u["color"]}
                 for u in _rosters[room]]
        _socketio.emit("presence", {"users": users}, to=room, namespace="/collab")
    except Exception:
        pass
    return True


def init_socketio(app, cors_allowed_origins="*") -> SocketIO:
    """
    Attach Socket.IO to the existing Flask app and register the collaboration
    namespace ('/collab'). Returns the SocketIO instance — caller is responsible
    for using socketio.run(app) instead of app.run().
    """
    global _socketio
    socketio = SocketIO(
        app,
        cors_allowed_origins=cors_allowed_origins,
        async_mode="threading",      # works without eventlet/gevent in dev
        logger=False, engineio_logger=False,
    )
    _socketio = socketio

    @socketio.on("connect", namespace="/collab")
    def _on_connect():
        # Client must follow up with a join event with the room name.
        log.info(f"socket connected: sid={request.sid}")

    @socketio.on("join", namespace="/collab")
    def _on_join(data):
        room = (data or {}).get("room") or "default"
        name = (data or {}).get("name") or "guest"
        did  = ((data or {}).get("device_id") or "").strip()[:64]
        sid  = request.sid
        ip   = _client_ip(request)
        # Refuse re-join if this device or IP has been kicked from the room.
        # device_id takes priority because IPs collide behind HF's proxy.
        banned_did = did and did in _banned_devices.get(room, set())
        banned_ip  = ip  and ip  in _banned_ips    .get(room, set())
        if banned_did or banned_ip:
            pretty = room[5:].upper() if room.startswith("room_") else room
            emit("banned", {"room": pretty,
                            "reason": "You were removed by the host. Ask the host to invite you back."})
            log.info(f"refused banned client did={did} ip={ip} room={room} "
                     f"(via {'device' if banned_did else 'ip'})")
            return
        # If this socket was in another room, remove it first.
        prev = _sid_room.get(sid)
        if prev and prev != room:
            _rosters[prev] = [u for u in _rosters[prev] if u["sid"] != sid]
            leave_room(prev, namespace="/collab")
            _broadcast_presence(prev)

        # Enforce room user cap (looks up room metadata if it's a shared room).
        # "default" and "session"-style rooms (sid-only) bypass the check.
        if room.startswith("room_"):
            code = room[5:].upper()
            try:
                import db
                cap = db.get_room_max_users(code)
                current = len(_rosters[room])
                if current >= cap:
                    emit("error", {"message": f"Room {code} is full ({cap} users max)."})
                    emit("room_full", {"room": code, "max_users": cap})
                    return
            except Exception:
                pass  # if db isn't reachable, allow join

        join_room(room, namespace="/collab")
        _sid_room[sid] = room
        if ip:
            _sid_ip[sid] = ip
        if did:
            _sid_did[sid] = did
        # Don't duplicate if reconnecting
        _rosters[room] = [u for u in _rosters[room] if u["sid"] != sid]
        _rosters[room].append({
            "sid": sid, "name": name[:32],
            "color": _color_for(room, sid),
            "joined_at": time.time(),
        })
        log.info(f"join room={room} name={name} sid={sid} "
                 f"total_in_room={len(_rosters[room])}")
        _broadcast_presence(room)

    @socketio.on("leave", namespace="/collab")
    def _on_leave():
        sid = request.sid
        room = _sid_room.pop(sid, None)
        if room:
            _rosters[room] = [u for u in _rosters[room] if u["sid"] != sid]
            leave_room(room, namespace="/collab")
            _broadcast_presence(room)

    @socketio.on("disconnect", namespace="/collab")
    def _on_disconnect(*args):
        # Treat as leave.
        sid = request.sid
        room = _sid_room.pop(sid, None)
        _sid_ip.pop(sid, None)
        _sid_did.pop(sid, None)
        if room:
            _rosters[room] = [u for u in _rosters[room] if u["sid"] != sid]
            _broadcast_presence(room)
            log.info(f"disconnect sid={sid} room={room} "
                     f"remaining_in_room={len(_rosters[room])}")

    @socketio.on("op", namespace="/collab")
    def _on_op(data):
        """Relay a circuit operation to all other peers in the room."""
        sid  = request.sid
        room = _sid_room.get(sid)
        if not room:
            emit("error", {"message": "join a room first"})
            return
        # Strict allowlist of kinds — refuse anything else so a malicious
        # client can't push arbitrary events.
        kind = (data or {}).get("kind", "")
        if kind not in {
            "add_gate", "move_gate", "remove_gate", "set_gate_value",
            "add_wire", "remove_wire",
            "set_circuit", "clear_circuit",
            "cursor",   # high-frequency presence
        }:
            return
        payload = (data or {}).get("payload", {})
        emit(
            "op",
            {"kind": kind, "payload": payload, "from": sid},
            to=room, include_self=False,
        )

    return socketio
