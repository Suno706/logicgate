"""Tests for the rate-limit decorator."""
from flask import Flask, jsonify

from rate_limit import limit, require_session


def _app():
    app = Flask(__name__)

    @app.route("/hit", methods=["POST"])
    @limit("test", per_minute=3)
    def hit():
        return jsonify(ok=True)

    @app.route("/private", methods=["POST"])
    @require_session
    def private():
        return jsonify(ok=True)

    return app


def test_limit_blocks_after_threshold():
    app = _app()
    client = app.test_client()
    for _ in range(3):
        assert client.post("/hit").status_code == 200
    r = client.post("/hit")
    assert r.status_code == 429
    body = r.get_json()
    assert body["status"] == "error"
    assert "Rate limit" in body["message"]


def test_require_session_blocks_without_header():
    app = _app()
    client = app.test_client()
    r = client.post("/private")
    assert r.status_code == 401


def test_require_session_passes_with_header():
    app = _app()
    client = app.test_client()
    r = client.post("/private", headers={"X-Session-Id": "abc"})
    assert r.status_code == 200
