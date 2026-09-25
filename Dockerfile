# syntax=docker/dockerfile:1
# ============================================================================
# Strategy Navigator — one image, three roles (api / worker / db) chosen at
# runtime by the CLI subcommand. Keep it small; no build toolchain in final.
# ============================================================================
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# --- deps layer (cached unless pyproject changes) ---
COPY pyproject.toml README.md ./
RUN uv pip install --system -e "."

# --- app ---
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv pip install --system -e "."

# non-root
RUN useradd --uid 10001 --create-home sn && chown -R sn:sn /app
USER sn

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

# default role; compose overrides `command` for workers
ENTRYPOINT ["strategy-navigator"]
CMD ["serve"]
