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

# --- Stage 2: Python runtime ---
FROM python:3.13-slim AS runtime

# System deps for sqlite-vec, fastembed, and PDF support
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
# Note: pyzotero conflicts with bibtexparser>=2, so we install
# academic extras individually (excluding pyzotero)
COPY pyproject.toml .
COPY rka/ rka/
COPY --from=web-builder /build/dist/ web/dist/
RUN pip install --no-cache-dir ".[llm,workspace]" \
    bibtexparser habanero semanticscholar arxiv

# Data volume
RUN mkdir -p /data
VOLUME /data

# Default environment
ENV RKA_DB_PATH=/data/rka.db \
    RKA_HOST=0.0.0.0 \
    RKA_PORT=9712 \
    RKA_LLM_ENABLED=true \
    RKA_LLM_MODEL=openai/qwen3-32b \
    RKA_LLM_API_BASE=http://host.docker.internal:1234/v1

EXPOSE 9712

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r=httpx.get('http://localhost:9712/api/health'); r.raise_for_status()" || exit 1

# Default: run the API server
CMD ["rka", "serve"]
