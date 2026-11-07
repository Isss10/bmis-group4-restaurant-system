# ---------------------------------------------------------------------------
# Multi-stage build for the FastAPI application.
#
# Why multi-stage: the final image carries only the runtime and installed
# packages — no compiler toolchain, no pip cache, no build metadata. That is a
# smaller image and, more importantly, a smaller attack surface (OWASP A05).
#
# Build from the repository root:
#     docker build -f deploy/docker/Dockerfile -t restaurant-system-api .
# Run:
#     docker compose -f deploy/docker/docker-compose.yml up --build
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Stage 1: build wheels from the dependency list.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# Build deps for compiling C extensions (cryptography, bcrypt, PyMySQL's optional
# speedups). These live ONLY in this stage and never reach the runtime image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libffi-dev \
      libssl-dev \
      default-libmysqlclient-dev \
      pkg-config \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only the requirements first. Docker caches this layer, so a source-code
# change does not trigger a full dependency reinstall — the difference between
# a 20-second and a 3-minute rebuild during development.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# curl is needed by the healthcheck below. `--no-install-recommends` keeps it
# minimal; the apt cache is removed in the same layer so it does not persist.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Run as a non-root user. If the container is compromised, the attacker lands as
# `appuser` with no write access to the code, not as root (OWASP A05).
RUN groupadd --system --gid 1001 appuser \
 && useradd --system --uid 1001 --gid appuser --create-home --home-dir /home/appuser appuser

WORKDIR /app

# Install the pre-built wheels from stage 1.
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* \
 && rm -rf /wheels

# Application code. Owned by root and read-only to appuser, so a compromised
# process cannot modify its own code to establish persistence.
COPY --chown=root:root src/ ./src/

# alembic.ini lives at the repository root, OUTSIDE src/, so the COPY above does
# not bring it in. The compose entrypoint runs `alembic upgrade head` before
# starting uvicorn; without this file that command fails with
# "No config file 'alembic.ini' found" and the container exits immediately.
# The migrations themselves (src/data/migration/) already ship inside src/.
#
# alembic.ini carries no credentials — the database URL is resolved at runtime
# from settings/env.py (see the comment at the top of that file), which is why
# committing and copying it is safe.
COPY --chown=root:root alembic.ini ./alembic.ini

# Metadata for support and for the /health endpoint.
LABEL org.opencontainers.image.title="Restaurant Reservation & Food-Ordering System API" \
      org.opencontainers.image.description="JC2001 BMIS Group 4 — FastAPI backend" \
      org.opencontainers.image.vendor="BMIS Group 4"

USER appuser

# Non-privileged port. Binding 80/443 inside a container requires root or
# CAP_NET_BIND_SERVICE; 8000 avoids both.
EXPOSE 8000

# Fail fast on unhandled Python signals, no .pyc clutter, unbuffered logs so
# `docker logs` shows output immediately instead of at exit.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENVIRONMENT=production

# Liveness probe. A container that cannot answer /health is restarted rather
# than silently serving errors. --fail makes a non-2xx status count as unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail --silent http://localhost:8000/health || exit 1

# --workers should be tuned to the container's CPU limit. Start at 2 for a
# course project; do not set it to the host's core count, which overcommits a
# memory-limited container and invites OOM kills.
CMD ["uvicorn", "src.presentation.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
