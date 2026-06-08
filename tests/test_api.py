"""
Integration tests for the Flask API.

Uses Flask's built-in test client (no real HTTP server needed).
"""
import json

import pytest

from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


# -- /api/health --------------------------------------------------------------

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "online"
    assert "models" in data


# -- /api/ask -----------------------------------------------------------------

def test_ask_build_half_adder(client):
    r = client.post("/api/ask", json={
        "question": "build a half adder",
        "circuit": {"gates": [], "wires": []},
    })
    assert r.status_code == 200
    data = r.get_json()
    assert "answer" in data
    # Build intent should return a circuit.
    assert data.get("circuit", {}).get("gates"), "Expected gates in response"


def test_ask_full_adder_using_nand(client):
    r = client.post("/api/ask", json={
        "question": "full adder using NAND",
        "circuit": {"gates": [], "wires": []},
    })
    assert r.status_code == 200
    data = r.get_json()
    gates = data.get("circuit", {}).get("gates", [])
    types = {g["type"] for g in gates if g["type"] not in ("INPUT", "OUTPUT")}
    assert types == {"NAND"}, f"Expected NAND-only, got {types}"


def test_ask_no_question(client):
    """Empty question should return an error, not crash."""
    r = client.post("/api/ask", json={"question": ""})
    assert r.status_code in (200, 400)


# -- /simulate ----------------------------------------------------------------

def test_simulate_and_gate(client):
    circuit = {
        "gates": [
            {"id": "g1", "type": "INPUT", "label": "A", "value": 1},
            {"id": "g2", "type": "INPUT", "label": "B", "value": 1},
            {"id": "g3", "type": "AND"},
            {"id": "g4", "type": "OUTPUT", "label": "Y"},
        ],
        "wires": [
            {"from_gate": "g1", "from_pin": 0, "to_gate": "g3", "to_pin": 0},
            {"from_gate": "g2", "from_pin": 0, "to_gate": "g3", "to_pin": 1},
            {"from_gate": "g3", "from_pin": 0, "to_gate": "g4", "to_pin": 0},
        ],
    }
    r = client.post("/simulate", json=circuit)
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"]
    assert data["outputs"]["g4"] == 1


# -- /api/build/boolean -------------------------------------------------------

def test_build_boolean(client):
    r = client.post("/api/build/boolean", json={"expression": "A & B | ~C"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"]
    assert data["circuit"]["gates"]


def test_build_boolean_empty(client):
    r = client.post("/api/build/boolean", json={"expression": ""})
    assert r.status_code == 400


# -- /api/synthesize ----------------------------------------------------------

def test_synthesize_nand_only(client):
    r = client.post("/api/synthesize", json={
        "expression": "A ^ B",
        "allowed_gates": ["NAND"],
    })
    assert r.status_code == 200
    data = r.get_json()
    types = {g["type"] for g in data["circuit"]["gates"]
             if g["type"] not in ("INPUT", "OUTPUT")}
    assert types == {"NAND"}
