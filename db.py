"""
SQLite-backed storage for LogicGate users and circuits.

Why SQLite (not Postgres)?
  - Zero ops to deploy: one file, copies cleanly into a Docker volume
  - More than adequate for a class-sized site (thousands of users, tens of
    thousands of circuits)
  - When the site scales past that, swap the DSN — the schema is portable

Schema
------
users     (id, username, password_hash, display_name, google_sub, created_at)
circuits  (id, owner_session, name, gates_json, wires_json, updated_at)
rooms     (code, owner_id, created_at, last_used_at)   -- for auto-generated codes

`owner_session` on circuits is the X-Session-Id value — which is
"user_<username>" for logged-in users, "g_<google_sub>" for Google users,
"room_<code>" for room workspaces, or "s_<random>" for guests. The same
field is used as the foreign key everywhere, so room/user/guest scoping
works uniformly.
"""
from __future__ import annotations
import os
import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional, List, Dict

DB_PATH = os.environ.get(
    "LOGICGATE_DB",
    os.path.join(os.path.dirname(__file__), "data", "logicgate.db"),
)


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")    # better concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_pool: Optional[sqlite3.Connection] = None


def get_db() -> sqlite3.Connection:
    """Module-level singleton. SQLite handles its own concurrency."""
    global _pool
    if _pool is None:
        _pool = _connect()
        _init_schema(_pool)
    return _pool


def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            display_name  TEXT,
            email         TEXT,
            google_sub    TEXT UNIQUE,
            created_at    REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS circuits (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_session   TEXT NOT NULL,
            name            TEXT NOT NULL,
            gates_json      TEXT NOT NULL,
            wires_json      TEXT NOT NULL,
            updated_at      REAL NOT NULL,
            UNIQUE(owner_session, name)
        );

        CREATE INDEX IF NOT EXISTS idx_circuits_owner ON circuits(owner_session);

        CREATE TABLE IF NOT EXISTS rooms (
            code          TEXT PRIMARY KEY,
            created_by    TEXT,
            created_at    REAL NOT NULL,
            last_used_at  REAL NOT NULL,
            max_users     INTEGER DEFAULT 20
        );
    """)
    # Add max_users column if upgrading from an older schema.
    try:
        conn.execute("ALTER TABLE rooms ADD COLUMN max_users INTEGER DEFAULT 20")
    except Exception:
        pass  # already exists
    conn.commit()


@contextmanager
def cursor():
    conn = get_db()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


# ─── Users ──────────────────────────────────────────────────────────────────

def create_user(username: str, password_hash: str,
                display_name: str = "", email: str = "",
                google_sub: str = "") -> int:
    """Returns the new user id. Raises sqlite3.IntegrityError on duplicate."""
    with cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash, display_name, email, "
            "google_sub, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (username, password_hash, display_name or username,
             email or "", google_sub or None, time.time()),
        )
        return cur.lastrowid


def get_user_by_username(username: str) -> Optional[dict]:
    with cursor() as cur:
        row = cur.execute(
            "SELECT id, username, password_hash, display_name, email, google_sub "
            "FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_google_sub(sub: str) -> Optional[dict]:
    with cursor() as cur:
        row = cur.execute(
            "SELECT id, username, display_name, email, google_sub "
            "FROM users WHERE google_sub = ?", (sub,)
        ).fetchone()
        return dict(row) if row else None


def get_user(user_id: int) -> Optional[dict]:
    with cursor() as cur:
        row = cur.execute(
            "SELECT id, username, display_name, email FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        return dict(row) if row else None


# ─── Circuits ──────────────────────────────────────────────────────────────

def save_circuit(owner_session: str, name: str,
                 gates: list, wires: list) -> int:
    """Upsert by (owner_session, name). Returns the row id."""
    with cursor() as cur:
        cur.execute(
            """INSERT INTO circuits (owner_session, name, gates_json, wires_json, updated_at)
                 VALUES (?, ?, ?, ?, ?)
                 ON CONFLICT(owner_session, name) DO UPDATE SET
                     gates_json = excluded.gates_json,
                     wires_json = excluded.wires_json,
                     updated_at = excluded.updated_at""",
            (owner_session, name,
             json.dumps(gates), json.dumps(wires), time.time()),
        )
        return cur.lastrowid or 0


def load_circuit(owner_session: str, name: str) -> Optional[dict]:
    with cursor() as cur:
        row = cur.execute(
            "SELECT gates_json, wires_json, updated_at FROM circuits "
            "WHERE owner_session = ? AND name = ?",
            (owner_session, name),
        ).fetchone()
        if not row:
            return None
        return {
            "gates":      json.loads(row["gates_json"]),
            "wires":      json.loads(row["wires_json"]),
            "updated_at": row["updated_at"],
        }


def list_circuits(owner_session: str) -> List[str]:
    with cursor() as cur:
        rows = cur.execute(
            "SELECT name FROM circuits WHERE owner_session = ? ORDER BY name",
            (owner_session,),
        ).fetchall()
        return [r["name"] for r in rows]


def delete_circuit(owner_session: str, name: str) -> bool:
    with cursor() as cur:
        cur.execute(
            "DELETE FROM circuits WHERE owner_session = ? AND name = ?",
            (owner_session, name),
        )
        return cur.rowcount > 0


# ─── Rooms (auto-generated codes) ──────────────────────────────────────────

# Alphabet excludes ambiguous characters (0/O, 1/I/l) so codes are easy to
# read over voice / handwriting.
_ROOM_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
import secrets   # noqa: E402


def generate_room_code(length: int = 6, owner_session: str = None,
                       max_users: int = 20) -> str:
    """Generate a unique room code. owner_session: caller's session_id, stored
    as text so guests (s_xxx) AND signed-in users (u_xxx_yyy / g_xxx) can own
    a room and kick others. max_users caps concurrent connections (default 20)."""
    for _ in range(20):
        code = "".join(secrets.choice(_ROOM_ALPHABET) for _ in range(length))
        with cursor() as cur:
            exists = cur.execute(
                "SELECT 1 FROM rooms WHERE code = ?", (code,)
            ).fetchone()
            if not exists:
                cur.execute(
                    "INSERT INTO rooms (code, created_by, created_at, last_used_at, max_users) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (code, owner_session, time.time(), time.time(), max_users),
                )
                return code
    raise RuntimeError("Could not generate unique room code")


def get_room_owner(code: str) -> Optional[str]:
    """Returns the session_id of the room creator, or None if room is open."""
    with cursor() as cur:
        row = cur.execute(
            "SELECT created_by FROM rooms WHERE code = ?", (code,)
        ).fetchone()
        return row["created_by"] if row else None


def get_room_max_users(code: str) -> int:
    """Returns the cap on concurrent users. Defaults to 20."""
    with cursor() as cur:
        row = cur.execute(
            "SELECT max_users FROM rooms WHERE code = ?", (code,)
        ).fetchone()
        if row and row["max_users"] is not None:
            try:
                return int(row["max_users"])
            except (TypeError, ValueError):
                pass
        return 20


def set_room_max_users(code: str, owner_session: str, max_users: int) -> bool:
    """Owner-only: update max_users for a room. Returns True if the caller owns
    the room and the update happened."""
    max_users = max(2, min(100, int(max_users)))
    with cursor() as cur:
        row = cur.execute(
            "SELECT created_by FROM rooms WHERE code = ?", (code,)
        ).fetchone()
        if not row or row["created_by"] != owner_session:
            return False
        cur.execute("UPDATE rooms SET max_users = ? WHERE code = ?",
                    (max_users, code))
        return True


def touch_room(code: str) -> bool:
    """Update last_used_at. Returns True if the room exists."""
    with cursor() as cur:
        cur.execute("UPDATE rooms SET last_used_at = ? WHERE code = ?",
                    (time.time(), code))
        if cur.rowcount > 0:
            return True
        # Auto-create unknown rooms — friction-free for users who type a code
        # they want to use.
        cur.execute(
            "INSERT OR IGNORE INTO rooms (code, created_by, created_at, last_used_at) "
            "VALUES (?, ?, ?, ?)",
            (code, None, time.time(), time.time()),
        )
        return cur.rowcount > 0


def get_room(code: str) -> Optional[dict]:
    with cursor() as cur:
        row = cur.execute(
            "SELECT code, created_at, last_used_at FROM rooms WHERE code = ?",
            (code,),
        ).fetchone()
        return dict(row) if row else None


# ─── One-time migration from filesystem ────────────────────────────────────

def migrate_filesystem_circuits(circuits_root: str = "circuits"):
    """
    On first startup, sweep the old per-folder structure into SQLite so users
    don't lose their saved circuits.
    """
    if not os.path.isdir(circuits_root):
        return 0
    migrated = 0
    for owner in os.listdir(circuits_root):
        owner_dir = os.path.join(circuits_root, owner)
        if not os.path.isdir(owner_dir):
            continue
        # "examples" stays as filesystem — they're the curated shared gallery.
        if owner == "examples":
            continue
        for fname in os.listdir(owner_dir):
            if not fname.endswith(".json"):
                continue
            name = fname[:-5]
            try:
                with open(os.path.join(owner_dir, fname), "r") as f:
                    data = json.load(f)
                gates = data.get("gates", [])
                wires = data.get("wires", [])
                # Skip if already migrated
                if load_circuit(owner, name):
                    continue
                save_circuit(owner, name, gates, wires)
                migrated += 1
            except Exception as e:
                print(f"[migrate] skipped {owner}/{fname}: {e}")
    return migrated
