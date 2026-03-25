#!/bin/bash
# Pie Office dev server launcher
# Usage: ./dev.sh [port] [--lan] [--tailscale] [--no-sleep]
#   --lan        Enable phone access (WiFi only)
#   --tailscale  Enable Tailscale for cross-network access (implies --lan)
#   --no-sleep   Keep Mac awake via caffeinate while server runs
PORT=10317
LAN_MODE=""
TAILSCALE_MODE=""
TAILSCALE_WATCH_PID=""
NO_SLEEP=""
for arg in "$@"; do
    if [ "$arg" = "--lan" ]; then
        LAN_MODE=1
    elif [ "$arg" = "--tailscale" ]; then
        LAN_MODE=1
        TAILSCALE_MODE=1
    elif [ "$arg" = "--no-sleep" ]; then
        NO_SLEEP=1
    elif [[ "$arg" =~ ^[0-9]+$ ]]; then
        PORT="$arg"
    fi
done
DIR="$(cd "$(dirname "$0")" && pwd)"

# Show access info
if [ -n "$LAN_MODE" ]; then
    LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "unknown")
    echo "WiFi LAN: https://$LAN_IP:10316/"

    if [ -n "$TAILSCALE_MODE" ]; then
        if ! tailscale status >/dev/null 2>&1; then
            echo ""
            echo "⚠  Tailscale is not running! Cross-network access unavailable."
            echo "   Start it: open -a Tailscale (or App Store → Tailscale)"
            echo ""
            # Background warning loop until Tailscale comes up
            (while ! tailscale status >/dev/null 2>&1; do
                echo "⚠  Tailscale still not running — cross-network access unavailable"
                sleep 30
            done
            echo "✓ Tailscale connected: https://$(tailscale ip -4 2>/dev/null):10316/") &
            TAILSCALE_WATCH_PID=$!
        else
            echo "Tailscale: https://$(tailscale ip -4 2>/dev/null):10316/"
        fi
    fi
fi

# No-sleep mode: caffeinate keeps Mac awake while server runs
CAFFEINATE_PID=""
if [ -n "$NO_SLEEP" ]; then
    caffeinate -s &
    CAFFEINATE_PID=$!
    echo "No-sleep mode: caffeinate ON (pid=$CAFFEINATE_PID)"
fi

# Kill existing process on port
lsof -ti:"$PORT" 2>/dev/null | xargs kill -9 2>/dev/null

# Activate venv and start server
cd "$DIR"
source venv/bin/activate
echo "Starting Pie Office on :$PORT ..."

# Clean up caffeinate on exit
cleanup() {
    if [ -n "$TAILSCALE_WATCH_PID" ]; then
        kill "$TAILSCALE_WATCH_PID" 2>/dev/null
    fi
    if [ -n "$CAFFEINATE_PID" ]; then
        kill "$CAFFEINATE_PID" 2>/dev/null
        echo "No-sleep mode: caffeinate OFF"
    fi
}
trap cleanup EXIT

PIE_TERMINAL_LAN=$LAN_MODE PORT=$PORT python3 backend/app.py
