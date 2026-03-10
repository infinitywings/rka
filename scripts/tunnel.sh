#!/bin/bash
# SSH reverse tunnel for remote Claude Code sessions.
# Forwards remote localhost:9712 → local localhost:9712
#
# Usage: ./tunnel.sh <ssh-host>
# Example: ./tunnel.sh research-server

set -euo pipefail

HOST="${1:?Usage: ./tunnel.sh <ssh-host>}"
PORT="${RKA_PORT:-9712}"

echo "🔗 Establishing SSH reverse tunnel..."
echo "   Remote localhost:${PORT} → Local localhost:${PORT}"
echo "   Press Ctrl+C to disconnect."

ssh -N -R "${PORT}:localhost:${PORT}" "${HOST}"
