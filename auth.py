"""
Google OAuth 2.0 login for LogicGate.

Activates automatically when GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are
present in the environment. When they aren't set, the auth endpoints return
HTTP 503 with a clear message, and the frontend falls back to the existing
name-based session model — nothing breaks.

How to enable Google sign-in in production
-------------------------------------------
1. Create an OAuth 2.0 Client ID at https://console.cloud.google.com/apis/credentials
   • Application type: Web application
   • Authorized redirect URI: https://YOUR-DOMAIN.com/api/auth/google/callback
     (For local dev: http://localhost:5000/api/auth/google/callback)
2. Set these env vars before starting Flask:
     GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com
     GOOGLE_CLIENT_SECRET=<your-client-secret>
     FLASK_SECRET_KEY=<some-random-32-byte-hex>       # for session cookies
3. Restart. The /api/auth/me endpoint will start returning real user data
   once a user clicks "Sign in with Google".

Routes
------
  GET  /api/auth/me              → {logged_in, name, email, picture} | 401
  GET  /api/auth/google          → redirect to Google's consent screen
  GET  /api/auth/google/callback → handles the callback, sets session cookie
  POST /api/auth/logout          → clears the session
  GET  /api/auth/config          → {google_enabled: bool} so frontend knows
                                    whether to show the button.

The signed-in user's id (a Google-issued `sub`) is used as the X-Session-Id
for all subsequent API calls — so their saved circuits follow them across
devices automatically.
"""
from __future__ import annotations
import os
import re
import secrets
import sqlite3
from typing import Optional

from flask import Blueprint, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
PASSWORD_MIN = 6

GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

_oauth = None


def init_auth(app):
    """
    Wire up Authlib if Google credentials are present. Safe to call even when
    not configured — endpoints just return 503 with a helpful message.
    """
    global _oauth

    # Session cookies need a secret key. Generate an ephemeral one for dev so
    # the app boots, but warn that it won't survive a restart.
    if not app.secret_key:
        app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
        if not os.environ.get("FLASK_SECRET_KEY"):
            print("[auth] Warning: using ephemeral FLASK_SECRET_KEY. "
                  "Sessions will be lost on restart. Set FLASK_SECRET_KEY in env "
                  "for production.")

    if not GOOGLE_ENABLED:
        print("[auth] Google OAuth disabled (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET "
              "not set). The site will run in guest/name-only mode.")
        return

    try:
        from authlib.integrations.flask_client import OAuth
    except ImportError:
        print("[auth] Authlib not installed; Google OAuth disabled.")
        return

    _oauth = OAuth(app)
    _oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    print(f"[auth] Google OAuth enabled (client_id={GOOGLE_CLIENT_ID[:24]}…)")


def current_user() -> Optional[dict]:
    """Returns the signed-in user dict or None."""
    return session.get("user")


@bp.route("/config", methods=["GET"])
def auth_config():
    """Tells the frontend whether the Google button should be visible."""
    return jsonify({"google_enabled": GOOGLE_ENABLED})


@bp.route("/me", methods=["GET"])
def me():
    u = current_user()
    if not u:
        return jsonify({"logged_in": False}), 200
    return jsonify({
        "logged_in": True,
        "id":      u.get("id"),
        "name":    u.get("name"),
        "email":   u.get("email"),
        "picture": u.get("picture"),
    })


@bp.route("/google", methods=["GET"])
def google_login():
    if not GOOGLE_ENABLED or _oauth is None:
        return jsonify({
            "error": "Google OAuth not configured on this server.",
            "hint":  "Ask the admin to set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        }), 503
    # Build the callback URL using the request's Host header so this works
    # both on localhost and behind a reverse proxy.
    redirect_uri = url_for("auth.google_callback", _external=True)
    return _oauth.google.authorize_redirect(redirect_uri)


@bp.route("/google/callback", methods=["GET"])
def google_callback():
    if not GOOGLE_ENABLED or _oauth is None:
        return jsonify({"error": "Google OAuth not configured"}), 503
    try:
        token = _oauth.google.authorize_access_token()
    except Exception as e:
        return jsonify({"error": f"OAuth callback failed: {e}"}), 400
    userinfo = token.get("userinfo") or {}
    if not userinfo:
        # Fall back to the userinfo endpoint
        userinfo = _oauth.google.get(
            "https://openidconnect.googleapis.com/v1/userinfo").json()
    user = {
        "id":      "g_" + str(userinfo.get("sub", "")),   # "g_" prefix avoids
        "name":    userinfo.get("name", "user"),          # collision with name-
        "email":   userinfo.get("email", ""),             # based session ids
        "picture": userinfo.get("picture", ""),
    }
    session["user"] = user
    session.permanent = True
    # Redirect to the frontend so the SPA picks up the session
    return redirect("/")


@bp.route("/logout", methods=["POST", "GET"])
def logout():
    session.pop("user", None)
    if request.method == "GET":
        return redirect("/")
    return jsonify({"status": "success"})


# ─── Username/password auth (works without Google) ──────────────────────────

@bp.route("/register", methods=["POST"])
def register():
    """Create a new account. Body: {username, password, display_name?}"""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    display  = (data.get("display_name") or username).strip() or username

    if not USERNAME_RE.match(username):
        return jsonify({"error": "Username must be 3–32 chars (letters, digits, _ or -)."}), 400
    if len(password) < PASSWORD_MIN:
        return jsonify({"error": f"Password must be at least {PASSWORD_MIN} characters."}), 400

    try:
        uid = db.create_user(
            username=username,
            password_hash=generate_password_hash(password),
            display_name=display,
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already taken."}), 409

    user = {
        "id":      f"u_{uid}_{username}",
        "uid":     uid,
        "name":    display,
        "email":   "",
        "picture": "",
    }
    session["user"] = user
    session.permanent = True
    return jsonify({"status": "success", "user": user})


@bp.route("/login", methods=["POST"])
def login():
    """Body: {username, password}"""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""

    row = db.get_user_by_username(username)
    if not row or not row.get("password_hash") \
       or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Wrong username or password."}), 401

    user = {
        "id":      f"u_{row['id']}_{row['username']}",
        "uid":     row["id"],
        "name":    row.get("display_name") or row["username"],
        "email":   row.get("email") or "",
        "picture": "",
    }
    session["user"] = user
    session.permanent = True
    return jsonify({"status": "success", "user": user})
