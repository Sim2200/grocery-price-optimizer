# syntax=docker/dockerfile:1
# Two stages: Node builds the Next.js app (static export), then a slim Python image
# serves the API *and* the built frontend from one process (the same as `make serve`).

# ---- stage 1: build the frontend -------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
# Copy only the lockfile first so `npm ci` is cached until dependencies change.
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- stage 2: the Python app --------------------------------------------------
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# Editable install keeps the package at /app/src, so config.PROJECT_ROOT is /app and
# the app finds data/ (catalog, synthetic receipts) and web/out next to it.
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install -e ".[postgres]"

COPY data/ data/
COPY --from=web /web/out web/out

# Run as a non-root user. /app/var holds the SQLite file (mount a volume there).
RUN useradd --create-home --uid 10001 app && mkdir -p /app/var && chown app:app /app/var
USER app
ENV GROCERY_DB=/app/var/grocery.db

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
# --no-access-log: the app writes its own JSON access log line (with request ID) per request.
CMD ["uvicorn", "--factory", "grocery_optimizer.api.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
