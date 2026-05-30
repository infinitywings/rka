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

# System deps: curl + Node.js (for the claude CLI), ca-certs for HTTPS.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install the Claude CLI — claude-agent-sdk spawns it as a subprocess
# (located via shutil.which("claude")). The canonical install is via npm.
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

# Install the rka package — its CLI `rka mcp` subcommand is the stdio
# launcher the SDK subprocess invokes for the rka MCP server (see
# orchestrator/llm_client.py:_find_rka_mcp_binary which uses shutil.which).
# We only need the core deps + the binary on PATH; the heavy extras
# (academic/llm/workspace) are NOT needed in the orchestrator container —
# all rka work happens against the rka-server container via HTTP.
COPY pyproject.toml ./
COPY rka/ ./rka/
RUN pip install --no-cache-dir .

# Install orchestrator + deps. Pins langgraph, claude-agent-sdk, etc.
COPY orchestrator/ ./orchestrator/
RUN pip install --no-cache-dir "./orchestrator[dev]"

# Gap 5 hardening — non-root user (UID 1000 by default; overridable at
# build via --build-arg ORCH_UID=$(id -u) for Linux-host UID matching).
# The bind-mounted workspace must be writable by this UID; on macOS
# Docker Desktop auto-translates UIDs so the default works; on Linux
# match your host UID at build time.
ARG ORCH_UID=1000
ARG ORCH_GID=1000
RUN groupadd -g ${ORCH_GID} orchestrator \
    && useradd -m -u ${ORCH_UID} -g ${ORCH_GID} -s /bin/bash orchestrator

# Data volume — the orchestrator's two SQLite files (parked-interrupt
# store + LangGraph SqliteSaver) live here. Three-storage discipline:
# this is orchestrator-owned only; RKA's rka.db lives in the separate
# rka-data volume on the rka-server container.
RUN mkdir -p /data && chown orchestrator:orchestrator /data /app
VOLUME /data

ENV ORCHESTRATOR_DB_PATH=/data/orchestrator.db \
    ORCHESTRATOR_SAVER_PATH=/data/orchestrator-saver.db \
    ORCHESTRATOR_HOST=0.0.0.0 \
    ORCHESTRATOR_PORT=9713 \
    RKA_API_URL=http://rka:9712 \
    HOME=/home/orchestrator

EXPOSE 9713

# Health check — same shape as the rka image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r=httpx.get('http://localhost:9713/health'); r.raise_for_status()" || exit 1

# Drop root before runtime — Gap 5 hardening. The daemon and every
# claude-agent-sdk subprocess it spawns now runs as UID 1000 ("orchestrator").
# An LLM that escapes the SDK sandbox can only mutate paths the
# orchestrator user has write access to (the bind-mounted workspace,
# /data, /home/orchestrator, /tmp) — not /etc, /usr, /root, or the
# rest of the container image.
USER orchestrator

# Run via uvicorn factory — same pattern as `rka serve`.
CMD ["python", "-m", "uvicorn", \
     "--factory", "orchestrator.server:create_app", \
     "--host", "0.0.0.0", "--port", "9713"]
