#!/bin/bash
# setup-terminal.sh — Generate TLS cert, auth token, install tmux wrapper
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TLS_DIR="$HOME/.pieoffice-tls"
TOKEN_PATH="$HOME/.pieoffice-terminal-token"
WRAPPER_DIR="$HOME/.local/bin"

echo "=== Pie Office Terminal Setup ==="
echo ""

# 1. TLS cert
echo "[1/3] TLS certificate..."
mkdir -p "$TLS_DIR"
if [ -f "$TLS_DIR/cert.pem" ]; then
    echo "  Already exists: $TLS_DIR/cert.pem"
else
    # Get Mac's LAN IP
    LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "192.168.1.1")
    echo "  LAN IP detected: $LAN_IP"

    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "$TLS_DIR/key.pem" \
        -out "$TLS_DIR/cert.pem" \
        -days 365 \
        -subj "/CN=PieOffice" \
        -addext "subjectAltName=IP:$LAN_IP,IP:127.0.0.1,DNS:localhost" \
        2>/dev/null
    chmod 600 "$TLS_DIR/key.pem"
    echo "  Generated: $TLS_DIR/cert.pem (valid 365 days)"
fi

# 2. Auth token
echo "[2/3] Auth token..."
if [ -f "$TOKEN_PATH" ]; then
    echo "  Already exists: $TOKEN_PATH"
    echo "  Token: $(cat "$TOKEN_PATH")"
else
    TOKEN=$(openssl rand -hex 32)
    echo -n "$TOKEN" > "$TOKEN_PATH"
    chmod 600 "$TOKEN_PATH"
    echo "  Generated: $TOKEN_PATH"
    echo ""
    echo "  ┌──────────────────────────────────────────────────────────────────┐"
    echo "  │  SAVE THIS TOKEN ON YOUR PHONE:                                 │"
    echo "  │  $TOKEN  │"
    echo "  └──────────────────────────────────────────────────────────────────┘"
    echo ""
fi

# 3. Tmux wrapper
echo "[3/3] Claude tmux wrapper..."
mkdir -p "$WRAPPER_DIR"
cp "$DIR/claude-tmux" "$WRAPPER_DIR/claude-tmux"
chmod +x "$WRAPPER_DIR/claude-tmux"
echo "  Installed: $WRAPPER_DIR/claude-tmux"

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$WRAPPER_DIR:"* ]]; then
    echo ""
    echo "  Add to your ~/.zshrc:"
    echo "    export PATH=\"$WRAPPER_DIR:\$PATH\""
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Usage:"
echo "  1. Start Pie Office in LAN mode:"
echo "     PIE_TERMINAL_LAN=1 ./dev.sh 10317"
echo "     # or: ./dev.sh 10317 --lan"
echo ""
echo "  2. Start Claude via tmux wrapper:"
echo "     claude-tmux"
echo ""
echo "  3. On your phone, open:"
echo "     https://$(ipconfig getifaddr en0 2>/dev/null || echo '<mac-ip>'):10317/terminal"
