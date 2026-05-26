# =============================================================
# RKA Orchestrator daemon image
# Hosts the FastAPI server + LangGraph runner. The PI's Claude
# Code session talks to this via a second MCP stdio binary
# (orchestrator/orchestrator/mcp_server.py) registered alongside
# `rka` in claude_desktop_config.json.
#
# Build context is the REPO ROOT (one level up) so the build can
# COPY both `orchestrator/` and the host's auth assets cleanly.
# =============================================================

FROM python:3.13-slim

# System deps: curl (for installing the claude CLI), ca-certs for HTTPS.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install the Claude CLI — the orchestrator's claude-agent-sdk spawns
# this as a subprocess. Uses the official npm-free installer.
RUN curl -fsSL https://claude.ai/install.sh | bash && \
    ln -sf /root/.local/bin/claude /usr/local/bin/claude

WORKDIR /app

# Install orchestrator + deps. The package's pyproject pins langgraph,
# claude-agent-sdk, etc., per the agentic-branch backbrief.
COPY orchestrator/ ./orchestrator/
RUN pip install --no-cache-dir "./orchestrator[dev]"

# Data volume — the orchestrator's two SQLite files (parked-interrupt
# store + LangGraph SqliteSaver) live here. Three-storage discipline:
# this is orchestrator-owned only; RKA's rka.db lives in the separate
# rka-data volume on the rka-server container.
RUN mkdir -p /data
VOLUME /data

ENV ORCHESTRATOR_DB_PATH=/data/orchestrator.db \
    ORCHESTRATOR_SAVER_PATH=/data/orchestrator-saver.db \
    ORCHESTRATOR_HOST=0.0.0.0 \
    ORCHESTRATOR_PORT=9713 \
    RKA_API_URL=http://rka:9712

EXPOSE 9713

# Health check — same shape as the rka image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r=httpx.get('http://localhost:9713/health'); r.raise_for_status()" || exit 1

# Run via uvicorn factory — same pattern as `rka serve`.
CMD ["python", "-m", "uvicorn", \
     "--factory", "orchestrator.server:create_app", \
     "--host", "0.0.0.0", "--port", "9713"]
