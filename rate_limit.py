"""
Tiny in-memory rate limiter for Flask.

Per-IP token bucket. No external deps — kept lightweight on purpose so the
free-tier Docker image stays small. Suitable for a single-process gunicorn
worker; behind multi-worker setups swap in flask-limiter + Redis.

Usage:
    from rate_limit import limit
    @app.route('/save', methods=['POST'])
    @limit("save", per_minute=20)
    def save(): ...
"""
from __future__ import annotations

import time
import threading
from collections import defaultdict, deque
from functools import wraps
from typing import Callable

from flask import request, jsonify


_LOCK = threading.Lock()
_HITS: dict[str, deque[float]] = defaultdict(deque)


def _client_id() -> str:
    """Best-effort identifier — prefer authenticated user, then X-Forwarded-For
    (first hop), then remote_addr. Cheap and good enough for abuse-prevention."""
    try:
        from auth import current_user
        u = current_user()
        if u and u.get('id'):
            return f"u:{u['id']}"
    except Exception:
        pass
    xff = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    return f"ip:{xff or request.remote_addr or 'unknown'}"


def limit(bucket: str, *, per_minute: int = 30) -> Callable:
    """Decorator: at most `per_minute` calls per client per bucket per 60s.

    Returns 429 JSON when exceeded — does NOT raise.
    """
    window = 60.0

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{bucket}:{_client_id()}"
            now = time.time()
            with _LOCK:
                dq = _HITS[key]
                while dq and dq[0] < now - window:
                    dq.popleft()
                if len(dq) >= per_minute:
                    retry_in = max(1, int(window - (now - dq[0])))
                    return jsonify({
                        'status':  'error',
                        'success': False,
                        'message': (f'Rate limit: {per_minute}/min for "{bucket}". '
                                    f'Try again in ~{retry_in}s.'),
                    }), 429
                dq.append(now)
            return fn(*args, **kwargs)
        return wrapper
    return deco


def require_session(fn):
    """Reject requests with a missing / obviously-spoofed session id.

    Guests are fine — they just need to present a session id (the frontend
    generates one in localStorage). The point is to reject scripted abuse
    that sends no X-Session-Id and no cookie at all."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        sid = request.headers.get('X-Session-Id', '').strip()
        try:
            from auth import current_user
            authed = bool(current_user())
        except Exception:
            authed = False
        if not authed and not sid:
            return jsonify({
                'status':  'error',
                'success': False,
                'message': 'Missing session credentials. '
                           'Sign in or send X-Session-Id.',
            }), 401
        return fn(*args, **kwargs)
    return wrapper
