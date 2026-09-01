# =============================================================
# RKA — Research Knowledge Agent
# Multi-stage build: Node (web UI) → Python (server + MCP)
# =============================================================

# --- Stage 1: Build web UI ---
FROM node:22-alpine AS web-builder
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

# --- Stage 2: Build sqlite-vec from source ---
FROM python:3.13-slim AS vec-builder

ARG SQLITE_VEC_VERSION=0.1.6

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    gcc \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/sqlite-vec

RUN curl -fsSL -o sqlite-vec.zip \
      "https://github.com/asg017/sqlite-vec/releases/download/v${SQLITE_VEC_VERSION}/sqlite-vec-${SQLITE_VEC_VERSION}-amalgamation.zip" \
    && unzip sqlite-vec.zip \
    && gcc -O3 -fPIC -shared sqlite-vec.c -o vec0.so -lm

# --- Stage 3: Python runtime ---
FROM python:3.13-slim AS runtime

# System deps for sqlite-vec, fastembed, and PDF support
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
COPY README.md LICENSE ./
COPY rka/ rka/
COPY --from=web-builder /build/dist/ web/dist/
COPY --from=vec-builder /tmp/sqlite-vec/vec0.so /usr/local/lib/vec0.so
RUN pip install --no-cache-dir ".[embeddings,academic,workspace]"

# Data volume
RUN mkdir -p /data
VOLUME /data

# Default environment
ENV RKA_DATA_DIR=/data \
    RKA_DB_PATH=/data/rka.db \
    RKA_EMBEDDINGS_ENABLED=true \
    RKA_HOST=0.0.0.0 \
    RKA_PORT=9712 \
    RKA_LLM_ENABLED=false \
    RKA_SQLITE_VEC_PATH=/usr/local/lib/vec0.so \
    # v2.7.0.1: bound onnxruntime parallelism + persist FastEmbed cache.
    # These defaults are safe for any caller (Docker run, compose, direct).
    # Compose interpolation in docker-compose.yml can override RKA_EMBEDDING_THREADS.
    OMP_NUM_THREADS=2 \
    TOKENIZERS_PARALLELISM=false \
    RKA_EMBEDDING_THREADS=2 \
    RKA_EMBEDDING_CACHE_DIR=/data/fastembed_cache

LABEL org.opencontainers.image.title="RKA Core" \
      org.opencontainers.image.description="Local-first research memory and evidence infrastructure" \
      org.opencontainers.image.source="https://github.com/rka-project/rka-core" \
      org.opencontainers.image.licenses="MIT"

EXPOSE 9712

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r=httpx.get('http://localhost:9712/api/health'); r.raise_for_status()" || exit 1

# Default: run the API server
CMD ["rka", "serve"]
