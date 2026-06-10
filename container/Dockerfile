# ─────────────────────────────────────────────────────────────────
# rec-inference: Multi-stage Dockerfile
# Scenario X — Personalized In-App Recommendations
#
# Strategy: model artifact is NOT baked in; it is downloaded from GCS
# by an init container at pod startup (see ADR 0001).
# This image contains only the inference server + ONNX Runtime.
#
# Expected final image size: ~340 MB
# Base: python:3.11-slim-bookworm (~130 MB)
# + ONNX Runtime GPU wheels + FastAPI + dependencies (~200 MB)
# + app code (~10 MB)
# ─────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ─────────────────────────────────────────────
# Installs Python dependencies into a virtual environment.
# Kept separate so build tools (pip, gcc for any C extensions) do
# not appear in the final image.
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

# Install build dependencies (removed in runtime stage)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency manifest first — allows Docker layer caching
# to skip the expensive pip install when only source code changes.
COPY container/requirements.txt .

# Create isolated venv; install dependencies into it
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip==24.0 && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ─────────────────────────────────────────────
# Minimal runtime image. No build tools, no pip, no gcc.
FROM python:3.11-slim-bookworm AS runtime

# Install only CUDA runtime libraries needed by ONNX Runtime GPU provider.
# Using slim CUDA toolkit (libcublas, libcudnn stubs) rather than full CUDA image
# to keep image small. ONNX Runtime GPU wheels bundle the required CUDA binaries.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy the virtualenv from the builder stage — no pip in runtime
COPY --from=builder /opt/venv /opt/venv

# Set PATH so the venv python/uvicorn are found without activation
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ── Non-root user ─────────────────────────────────────────────────
# Run as a dedicated non-root user. UID/GID 1001 chosen to avoid
# collision with common system users.
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/false --no-create-home appuser

WORKDIR /app

# Copy application source code
COPY --chown=appuser:appgroup src/ ./src/

# Model artifact directory — created but EMPTY at build time.
# The init container (defined in the Helm chart) downloads the model
# from GCS into this directory before the inference server starts.
# Path: /model/rec-model-${MODEL_VERSION}.onnx
#        /model/rec-index-${MODEL_VERSION}.faiss
RUN mkdir -p /model && chown appuser:appgroup /model

# ── Runtime environment variables ────────────────────────────────
# MODEL_VERSION and FEATURE_SCHEMA_VERSION are injected by the
# Helm chart from the registry entry (e.g. v1.3.0-20260601).
# Defaults here are placeholders; the pod will fail the readiness
# check if MODEL_VERSION is not set or the artifact is missing.
ENV MODEL_VERSION="UNSET" \
    FEATURE_SCHEMA_VERSION="v3" \
    MODEL_DIR="/model" \
    SERVICE_PORT="8080" \
    WORKERS="1" \
    LOG_LEVEL="info"

# ── Port ─────────────────────────────────────────────────────────
EXPOSE 8080

# ── User ─────────────────────────────────────────────────────────
USER appuser

# ── Healthcheck ──────────────────────────────────────────────────
# /health  — liveness: is the process running?
# /ready   — readiness: is the model loaded and warm?
# The readiness probe is intentionally slow to start (120 s) to
# allow the init container to download the 1.35 GB model artifact.
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# ── Entrypoint ───────────────────────────────────────────────────
# uvicorn runs a single worker per pod; horizontal scaling is done
# at the pod level (HPA), not via uvicorn workers, to give Prometheus
# per-pod metrics without aggregation complexity.
CMD ["uvicorn", "src.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "1", \
     "--log-level", "info", \
     "--access-log"]
