#!/bin/bash
# Pie Office dev server launcher
# Usage: ./dev.sh [port] [--lan]    ./dev.sh --lan [port]
PORT=10317
LAN_MODE=""
for arg in "$@"; do
    if [ "$arg" = "--lan" ]; then
        LAN_MODE=1
    elif [[ "$arg" =~ ^[0-9]+$ ]]; then
        PORT="$arg"
    fi
done
DIR="$(cd "$(dirname "$0")" && pwd)"

# LAN mode: check Tailscale is running
if [ -n "$LAN_MODE" ]; then
    if ! tailscale status >/dev/null 2>&1; then
        echo ""
        echo "⚠  Tailscale is not running! LAN mode will not work for phone access."
        echo "   Start it: open -a Tailscale (or App Store → Tailscale)"
        echo ""
        # Background warning loop until Tailscale comes up
        (while ! tailscale status >/dev/null 2>&1; do
            echo "⚠  Tailscale still not running — phone access unavailable"
            sleep 30
        done
        echo "✓ Tailscale connected: $(tailscale ip -4 2>/dev/null)") &
    else
        echo "Tailscale: $(tailscale ip -4 2>/dev/null)"
    fi
fi

# Kill existing process on port
lsof -ti:"$PORT" 2>/dev/null | xargs kill -9 2>/dev/null

# Activate venv and start server
cd "$DIR"
source venv/bin/activate
echo "Starting Pie Office on :$PORT ..."
PIE_TERMINAL_LAN=$LAN_MODE PORT=$PORT python3 backend/app.py
