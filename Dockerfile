# ── Stage 1: Build the React frontend ─────────────────────────────────────────
FROM node:22-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci --prefer-offline
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Production Python image ──────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5000 \
    FLASK_ENV=production

WORKDIR /app

# Python dependencies (cached layer)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# App source (excluding node_modules / __pycache__ etc — see .dockerignore)
COPY . .

# Embed the pre-built React app so Flask serves it from /frontend/dist
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

# Saved circuits persist across restarts via a volume mount
RUN mkdir -p circuits

EXPOSE 5000

# Eventlet-backed gunicorn so Flask-SocketIO's WebSockets work properly.
# Single worker — Flask-SocketIO uses an in-process roster for presence/rooms.
# 180 s timeout absorbs the first-request model training if pickles are missing.
RUN pip install --no-cache-dir eventlet
CMD ["sh", "-c", "gunicorn -k eventlet -w 1 --timeout 180 -b 0.0.0.0:${PORT} app:app"]
