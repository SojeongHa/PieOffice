#!/bin/bash
# Pie Office dev server launcher
# Usage: ./dev.sh [port] [--lan]
PORT=${1:-10317}
LAN_MODE=""
for arg in "$@"; do
    if [ "$arg" = "--lan" ]; then
        LAN_MODE=1
    fi
done
DIR="$(cd "$(dirname "$0")" && pwd)"

# Kill existing process on port
lsof -ti:"$PORT" 2>/dev/null | xargs kill -9 2>/dev/null

# Activate venv and start server
cd "$DIR"
source venv/bin/activate
echo "Starting Pie Office on :$PORT ..."
PIE_TERMINAL_LAN=$LAN_MODE PORT=$PORT python3 backend/app.py
