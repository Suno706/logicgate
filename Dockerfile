# LogicGate — production container image
# Build:  docker build -t logicgate .
# Run:    docker run -p 5000:5000 logicgate
# Deploy: works on any host that runs Docker (Fly.io, Render, Railway,
#         DigitalOcean App Platform, AWS ECS, your own VPS, ...).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5000 \
    FLASK_DEBUG=0

WORKDIR /app

# Install Python deps first so docker layer cache survives source edits.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy the rest of the project. The trained pickles will be re-built on
# first request if they're missing (each ML class trains-on-load from the
# CSV). To skip that and bake them in, copy ml_models/saved/ as well.
COPY . .

EXPOSE 5000

# Use gunicorn (production WSGI) instead of Flask's dev server.
CMD ["sh", "-c", "gunicorn -w 2 -k gthread --threads 4 --timeout 180 -b 0.0.0.0:${PORT} app:app"]
