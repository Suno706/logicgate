# LogicGate — Deployment Guide

A digital-circuit designer with built-in ML, multi-user session isolation, and
online-learning feedback. Designed to be deployed as a public website that
anyone can use — no database, no signup friction.

## What you're deploying

- **Flask backend** on port 5000 serving both the API and the React SPA
- **5 scikit-learn models** trained on 200K-row dataset (auto-rebuilt on first start if pickles are missing)
- **Per-session saved circuits** — each browser gets a private `X-Session-Id`
- **Optional room codes** — groups share a workspace by entering the same code
- **Examples gallery** — 14 pre-built circuits visible to everyone
- **Online learning loop** — user thumbs-up/down feedback is logged and merged into the intent classifier at ×5 weight on retrain

## Quick local run (no Docker)

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
python app.py
```

Open http://localhost:5000.

## Docker (recommended for production)

```bash
docker compose up --build
```

The compose file mounts three named volumes so data survives container rebuilds:

| Volume | Path | Contents |
|---|---|---|
| `circuits` | `/app/circuits` | per-user / per-room saved circuits |
| `data` | `/app/data` | training CSVs + user query log |
| `models` | `/app/ml_models/saved` | trained pickles |

First boot rebuilds all pickles from the 200K-row dataset — takes ~30 seconds.

## Deploying to a public host

### Option A — Single VM (Hetzner, DigitalOcean, AWS Lightsail)

A 2 CPU / 4 GB RAM box is enough. The `minimizer.pkl` is 551 MB once trained,
so allow at least 2 GB free disk for the model directory.

```bash
git clone https://github.com/YOU/logicgate.git
cd logicgate
docker compose up -d --build
# point Caddy / nginx / Traefik at port 5000
```

Sample Caddy config that adds HTTPS automatically:

```
logicgate.example.com {
    reverse_proxy localhost:5000
}
```

### Option B — Fly.io / Railway / Render

The `Dockerfile` is single-image and listens on `$PORT`. Most PaaS deploy it
without changes. Allow ~60 seconds for first-request model load — set the
healthcheck `start_period` accordingly.

For Fly.io, three persistent volumes (`circuits`, `data`, `models`) cover all
runtime state.

## Identity model

LogicGate supports four identity levels, listed from highest authority down:

1. **Google account** (real auth, recommended for production)
   - Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` env vars
   - Session id = `g_<google-sub>` — survives across all devices, can't be spoofed
2. **Named user** — session id is `user_<sanitized-name>`. Same name on another
   device sees the same saved circuits. No verification — anyone who knows the
   name can impersonate.
3. **Guest** — random session id in `localStorage`. Private to the browser.
4. **Room** — session id is `room_<code>`. Everyone joining the same code
   shares a workspace. For class groups / pair programming.

### Enabling Google OAuth

1. Create a Google OAuth 2.0 Client ID at
   https://console.cloud.google.com/apis/credentials
   - Application type: **Web application**
   - Authorized redirect URI: `https://YOUR-DOMAIN.com/api/auth/google/callback`
     (for dev: `http://localhost:5000/api/auth/google/callback`)
2. Set the env vars **before** starting Flask:
   ```bash
   export GOOGLE_CLIENT_ID="<your-client-id>.apps.googleusercontent.com"
   export GOOGLE_CLIENT_SECRET="<your-client-secret>"
   export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
   ```
   In Docker, add them to `docker-compose.yml` under `environment:`.
3. Restart. The "Sign in with Google" button appears automatically on the
   welcome modal. `GET /api/auth/config` returns `{"google_enabled": true}`
   so the frontend knows to show it.

When the env vars aren't set, the button is hidden and the existing
guest/name-only flow keeps working — nothing breaks.

## Real-time collaboration

Connections are WebSocket-based via Flask-SocketIO on the same port. Every
browser opens one socket to `/collab` and joins the room matching its
`X-Session-Id`. Add/move/wire ops are broadcast to all peers in the same
room — verified end-to-end via `python tests/realtime_check.py`.

Production note: gunicorn alone won't serve WebSockets reliably. Use eventlet
or gevent workers:

```bash
gunicorn -k eventlet -w 1 -b 0.0.0.0:$PORT app:app
```

(Single worker — Flask-SocketIO uses an in-process roster.)

## Multi-user scaling

- ML models are loaded once at startup, shared across all gunicorn workers.
- The simulator is stateless — perfectly parallel.
- `/api/ask` appends one CSV row per call — fine up to ~100 req/sec.
  Swap to SQLite if you exceed this.
- Retraining the intent classifier is synchronous (~10 s). Rate-limit
  `/api/learning/retrain` if exposed publicly.

## Health monitoring

```bash
python tests/component_check.py        # 62 backend checks
python tests/smart_features_check.py   # exercises Build / Suggest / Fault / Minimize
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | 5000 | HTTP listen port |
| `FLASK_ENV` | development | Set to `production` to disable debug reloader |
