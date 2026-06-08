"""End-to-end test of the real-time collab WebSocket layer."""
import time
import socketio

# Two clients in the same room
c1 = socketio.SimpleClient()
c2 = socketio.SimpleClient()

c1.connect("http://localhost:5000", namespace="/collab", transports=["websocket"])
c2.connect("http://localhost:5000", namespace="/collab", transports=["websocket"])
print("[OK] Both clients connected")

c1.emit("join", {"room": "test_room", "name": "alice"})
c2.emit("join", {"room": "test_room", "name": "bob"})
time.sleep(0.3)

# Drain presence events
alice_saw_two = False
bob_saw_two   = False
for c, label in [(c1, "alice"), (c2, "bob")]:
    for _ in range(5):
        try:
            ev = c.receive(timeout=0.5)
            if ev[0] == "presence" and len(ev[1].get("users", [])) == 2:
                if label == "alice": alice_saw_two = True
                else:                bob_saw_two   = True
        except Exception:
            break

print(f"[{'OK' if alice_saw_two and bob_saw_two else 'BAD'}] "
      f"Presence broadcast: alice={alice_saw_two}, bob={bob_saw_two}")

# Alice adds a gate; bob should receive it
gate = {"id": "g1", "type": "AND", "x": 100, "y": 100}
c1.emit("op", {"kind": "add_gate", "payload": {"gate": gate}})

bob_got = None
for _ in range(20):
    try:
        ev = c2.receive(timeout=0.5)
        if ev[0] == "op":
            bob_got = ev[1]
            break
    except Exception:
        pass

if bob_got:
    print(f"[OK] add_gate relay: bob received kind={bob_got['kind']} "
          f"gate.id={bob_got['payload']['gate']['id']}")
else:
    print("[BAD] add_gate relay: bob did not receive the op")

# Alice moves the gate, bob should see it
c1.emit("op", {"kind": "move_gate", "payload": {"id": "g1", "x": 200, "y": 200}})
moved = None
for _ in range(20):
    try:
        ev = c2.receive(timeout=0.5)
        if ev[0] == "op" and ev[1]["kind"] == "move_gate":
            moved = ev[1]
            break
    except Exception:
        pass

if moved and moved["payload"]["x"] == 200:
    print(f"[OK] move_gate relay: bob got x=200")
else:
    print(f"[BAD] move_gate relay: got {moved}")

# Now Bob adds a wire — alice should receive it
wire = {"id": "w1", "from_gate": "g1", "to_gate": "g2", "from_pin": 0, "to_pin": 0}
c2.emit("op", {"kind": "add_wire", "payload": {"wire": wire}})
alice_got_wire = None
for _ in range(20):
    try:
        ev = c1.receive(timeout=0.5)
        if ev[0] == "op" and ev[1]["kind"] == "add_wire":
            alice_got_wire = ev[1]
            break
    except Exception:
        pass

if alice_got_wire:
    print(f"[OK] add_wire relay: alice got wire.id={alice_got_wire['payload']['wire']['id']}")
else:
    print("[BAD] add_wire relay: alice did not receive bob's wire")

# Verify own-broadcast suppression — alice shouldn't see her own ops echoed
c1.emit("op", {"kind": "set_gate_value", "payload": {"id": "g1", "value": 1}})
echoed = False
for _ in range(10):
    try:
        ev = c1.receive(timeout=0.3)
        if ev[0] == "op":
            echoed = True
            break
    except Exception:
        pass

if not echoed:
    print("[OK] echo suppression: alice's own op did NOT come back to her")
else:
    print("[BAD] echo suppression: alice received her own op (bad)")

# Disconnect carefully — bob should see presence drop to 1
c1.disconnect()
time.sleep(0.3)
bob_saw_drop = False
for _ in range(5):
    try:
        ev = c2.receive(timeout=0.5)
        if ev[0] == "presence" and len(ev[1].get("users", [])) == 1:
            bob_saw_drop = True
            break
    except Exception:
        break

print(f"[{'OK' if bob_saw_drop else 'BAD'}] disconnect propagates: "
      f"bob saw roster drop to 1")

c2.disconnect()
print("[OK] All clients disconnected cleanly")
