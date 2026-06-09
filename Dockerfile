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
RUN pip install --no-cache-dir -r requirements.txt

# App source (excluding node_modules / __pycache__ etc — see .dockerignore)
COPY . .

# Embed the pre-built React app so Flask serves it from /frontend/dist
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

# Saved circuits persist across restarts via a volume mount
RUN mkdir -p circuits

EXPOSE 5000

# Use Flask-SocketIO's built-in server (threading async mode is configured
# in realtime.py). Avoids eventlet/gevent compatibility issues on Python 3.12.
CMD ["python", "app.py"]
