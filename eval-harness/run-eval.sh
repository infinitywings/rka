#!/usr/bin/env bash
#
# T3 orchestration wrapper — runs the eval across all 4 configs.
#
# Mission: mis_01KRKJ9G20EM5XMA147JTKQCFF
#
# Strategy: only 2 container restarts (one per `RKA_FTS_QUERY_MODE`
# value), not 4. Hybrid/non-hybrid distinction is entirely runner-side
# (qwen3 RRF pass) — the container doesn't care.
#
# Per-config invocation:
#   1. Set RKA_FTS_QUERY_MODE in the container via docker-compose.override.yml
#      + .env file substitution.
#   2. `docker compose up -d --force-recreate rka` to pick up the new env.
#   3. Wait for `/api/health` to return 200.
#   4. Invoke `python -m eval_harness.runner` for the matching config(s).
#
# Pre-flight per observation #2 (reachability-first):
#   - LM Studio probe BEFORE any restarts (runner does its own per-config
#     probe too; this is an early-fail catch).
#   - Infrastructure failure → exit 2 (checkpoint), no retry-loop.

set -euo pipefail

# Resolve paths regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ID="prj_01KKQM9JFG67GT5FGWTAHD9YE4"   # rka_development

CONFIGS_DIR="${SCRIPT_DIR}/configs"
QUERIES_PATH="${SCRIPT_DIR}/corpus/queries.jsonl"
RESULTS_DIR="${SCRIPT_DIR}/results/raw"

# Order matters — group configs sharing the same RKA_FTS_QUERY_MODE so we
# only restart between mode switches.
CONFIGS_OR=("current_or" "current_or_hybrid")
CONFIGS_AND=("and_fix" "and_fix_hybrid")

API_URL="http://127.0.0.1:9712"
LM_STUDIO_URL="${LM_STUDIO_URL:-http://192.168.86.24:1234}"

# ---------- helpers ----------

log() {
    printf '[run-eval] %s · %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

abort_checkpoint() {
    log "⚠ CHECKPOINT — $1"
    exit 2
}

write_env_file() {
    local mode="$1"
    cat > "${REPO_ROOT}/.env" <<EOF
# Auto-written by run-eval.sh for mission mis_01KRKJ9G20EM5XMA147JTKQCFF.
# Restored to production defaults after the eval run completes.
RKA_FTS_QUERY_MODE=${mode}
RKA_EMBEDDINGS_ENABLED=false
EOF
}

restart_container_and_wait() {
    local mode="$1"
    write_env_file "${mode}"
    log "restart rka container with RKA_FTS_QUERY_MODE=${mode}"
    (cd "${REPO_ROOT}" && docker compose up -d --force-recreate rka)
    log "waiting for /api/health …"
    local tries=0
    until curl -sf -o /dev/null "${API_URL}/api/health"; do
        tries=$((tries + 1))
        if [ "${tries}" -ge 30 ]; then
            abort_checkpoint "container did not become healthy after 30 attempts"
        fi
        sleep 2
    done
    log "/api/health responding ✓"
}

run_one_config() {
    local cfg="$1"
    local out="${RESULTS_DIR}/${cfg}.jsonl"
    log "running config: ${cfg} → ${out}"
    mkdir -p "${RESULTS_DIR}"
    python3 -m eval_harness.runner \
        --config "${CONFIGS_DIR}/${cfg}.yaml" \
        --queries "${QUERIES_PATH}" \
        --output "${out}" \
        --project-id "${PROJECT_ID}" \
        --api-url "${API_URL}"
}

# ---------- pre-flight ----------

cd "${SCRIPT_DIR}"

log "pre-flight: LM Studio reachability probe"
if ! python3 -m eval_harness.embedder probe \
        --base-url "${LM_STUDIO_URL}" \
        --model "text-embedding-qwen3-embedding-8b"; then
    abort_checkpoint "LM Studio unreachable at ${LM_STUDIO_URL}. Load text-embedding-qwen3-embedding-8b first."
fi

# ---------- 2 container restarts × N configs each ----------

restart_container_and_wait "or"
for cfg in "${CONFIGS_OR[@]}"; do
    run_one_config "${cfg}"
done

restart_container_and_wait "and"
for cfg in "${CONFIGS_AND[@]}"; do
    run_one_config "${cfg}"
done

# ---------- restore production defaults ----------

log "restoring production defaults (deleting .env)"
rm -f "${REPO_ROOT}/.env"
log "restart with production defaults"
(cd "${REPO_ROOT}" && docker compose up -d --force-recreate rka)

log "✓ eval run complete · 4 configs × $(wc -l < "${QUERIES_PATH}") queries"
log "next: T4 PI labeling — invoke eval-harness/eval_harness/labeler.py"
