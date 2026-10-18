# Vicky API + worker image (one image, two commands).
#
#   docker build -t vicky-api ./backend
#   docker run --rm -p 8000:8000 --env-file .env vicky-api                 # API (uvicorn on $PORT, default 8000)
#   docker run --rm --env-file .env vicky-api arq vicky.jobs.WorkerSettings # worker
#   docker run --rm --env-file .env vicky-api python -m vicky.migrate      # migrations
#
# The venv's bin/ is on PATH, so `arq`, `uvicorn` and `python` need no `uv run`. uv is still
# shipped (UV_NO_SYNC=1) so the TRD's `uv run arq ...` / `uv run python -m vicky.migrate` also work.
# Secrets come from the runtime environment only; never pass them as build ARGs.

ARG PYTHON_IMAGE=python:3.13-slim

FROM ghcr.io/astral-sh/uv:0.11.33 AS uv

# ---- builder: resolve the locked dependencies into /app/.venv ----
FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first (cached until pyproject.toml or uv.lock changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the project itself. It stays an editable install so vicky.BACKEND_DIR resolves to /app
# (migrations/ and data/ are read relative to the package).
COPY vicky ./vicky
COPY migrations ./migrations
COPY data ./data
RUN uv sync --frozen --no-dev

# ---- runtime ----
FROM ${PYTHON_IMAGE} AS runtime
# tesseract reads scanned PDF pages and images for the knowledge base (vicky/kb/ocr.py).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 vicky \
 && useradd --system --uid 10001 --gid vicky --home-dir /app --no-create-home --shell /usr/sbin/nologin vicky
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
# Owned by root and read-only to the app user: the service writes nothing to local disk.
COPY --from=builder /app /app
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

ENV PATH="/app/.venv/bin:${PATH}" \
    VIRTUAL_ENV=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_NO_SYNC=1 \
    UV_PYTHON_DOWNLOADS=0 \
    UV_CACHE_DIR=/tmp/uv-cache

USER vicky
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
