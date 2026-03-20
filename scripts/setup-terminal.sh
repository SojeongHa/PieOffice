#!/bin/bash
# setup-terminal.sh — Generate mTLS certificates and install tmux wrapper
#
# Creates a private CA, server cert, and client cert (.p12) for device auth.
# Usage:
#   ./setup-terminal.sh           # Initial setup
#   ./setup-terminal.sh --revoke  # Revoke all client certs and regenerate
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TLS_DIR="$HOME/.pieoffice-tls"
WRAPPER_DIR="$HOME/.local/bin"
CLIENT_P12_PASSWORD="pieoffice"  # Password for .p12 import on iPhone

# ---------------------------------------------------------------------------
# Revoke / regen modes
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--revoke" ]]; then
    echo "=== Revoking all client certificates ==="
    rm -f "$TLS_DIR/client-cert.pem" "$TLS_DIR/client-key.pem" "$TLS_DIR/client.p12"
    echo "  Removed client certificates."
    echo "  Re-run without --revoke to generate new ones."
    exit 0
fi

REGEN_SERVER=false
if [[ "${1:-}" == "--regen-server" ]]; then
    REGEN_SERVER=true
    echo "=== Regenerating server certificate (new IPs) ==="
    rm -f "$TLS_DIR/server-cert.pem" "$TLS_DIR/server-key.pem"
fi

echo "=== Pie Office Terminal Setup (mTLS) ==="
echo ""

# ---------------------------------------------------------------------------
# 1. CA (Certificate Authority) — our own private CA
# ---------------------------------------------------------------------------
echo "[1/4] Certificate Authority..."
mkdir -p "$TLS_DIR"
if [ -f "$TLS_DIR/ca.pem" ]; then
    echo "  Already exists: $TLS_DIR/ca.pem"
else
    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "$TLS_DIR/ca-key.pem" \
        -out "$TLS_DIR/ca.pem" \
        -days 3650 \
        -subj "/CN=PieOffice CA" \
        2>/dev/null
    chmod 600 "$TLS_DIR/ca-key.pem"
    echo "  Generated: $TLS_DIR/ca.pem (valid 10 years)"
fi

# ---------------------------------------------------------------------------
# 2. Server certificate (signed by CA)
# ---------------------------------------------------------------------------
echo "[2/4] Server certificate..."
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "192.168.1.1")
echo "  LAN IP detected: $LAN_IP"

# Detect Tailscale IP (if installed and running)
# Try default socket first, then user-local socket (homebrew userspace mode)
TAILSCALE_IP=""
if command -v tailscale &>/dev/null; then
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || true)
    if [ -z "$TAILSCALE_IP" ] && [ -S "$HOME/.tailscale/tailscaled.sock" ]; then
        TAILSCALE_IP=$(tailscale --socket="$HOME/.tailscale/tailscaled.sock" ip -4 2>/dev/null || true)
    fi
    if [ -n "$TAILSCALE_IP" ]; then
        echo "  Tailscale IP detected: $TAILSCALE_IP"
    fi
fi

if [ -f "$TLS_DIR/server-cert.pem" ]; then
    echo "  Already exists: $TLS_DIR/server-cert.pem"
else
    # Build SAN list
    SAN="IP:$LAN_IP,IP:127.0.0.1,DNS:localhost"
    if [ -n "$TAILSCALE_IP" ]; then
        SAN="$SAN,IP:$TAILSCALE_IP"
    fi
    echo "  SAN: $SAN"

    # Generate server key + CSR
    openssl req -newkey rsa:2048 -nodes \
        -keyout "$TLS_DIR/server-key.pem" \
        -out "$TLS_DIR/server.csr" \
        -subj "/CN=PieOffice Server" \
        2>/dev/null

    # Sign with CA (include SAN for IP access)
    cat > "$TLS_DIR/server-ext.cnf" <<EXTEOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
subjectAltName=$SAN
EXTEOF

    openssl x509 -req \
        -in "$TLS_DIR/server.csr" \
        -CA "$TLS_DIR/ca.pem" \
        -CAkey "$TLS_DIR/ca-key.pem" \
        -CAcreateserial \
        -out "$TLS_DIR/server-cert.pem" \
        -days 365 \
        -extfile "$TLS_DIR/server-ext.cnf" \
        2>/dev/null

    chmod 600 "$TLS_DIR/server-key.pem"
    rm -f "$TLS_DIR/server.csr" "$TLS_DIR/server-ext.cnf" "$TLS_DIR/ca.srl"
    echo "  Generated: $TLS_DIR/server-cert.pem (valid 1 year)"
fi

# ---------------------------------------------------------------------------
# 3. Client certificate (for iPhone, signed by CA)
# ---------------------------------------------------------------------------
echo "[3/4] Client certificate..."
if [ -f "$TLS_DIR/client.p12" ]; then
    echo "  Already exists: $TLS_DIR/client.p12"
else
    # Generate client key + CSR
    openssl req -newkey rsa:2048 -nodes \
        -keyout "$TLS_DIR/client-key.pem" \
        -out "$TLS_DIR/client.csr" \
        -subj "/CN=PieOffice Client" \
        2>/dev/null

    # Sign with CA
    openssl x509 -req \
        -in "$TLS_DIR/client.csr" \
        -CA "$TLS_DIR/ca.pem" \
        -CAkey "$TLS_DIR/ca-key.pem" \
        -CAcreateserial \
        -out "$TLS_DIR/client-cert.pem" \
        -days 365 \
        2>/dev/null

    # Package as .p12 for iPhone import
    openssl pkcs12 -export \
        -out "$TLS_DIR/client.p12" \
        -inkey "$TLS_DIR/client-key.pem" \
        -in "$TLS_DIR/client-cert.pem" \
        -certfile "$TLS_DIR/ca.pem" \
        -passout "pass:$CLIENT_P12_PASSWORD" \
        2>/dev/null

    chmod 600 "$TLS_DIR/client-key.pem" "$TLS_DIR/client.p12"
    rm -f "$TLS_DIR/client.csr" "$TLS_DIR/ca.srl"
    echo "  Generated: $TLS_DIR/client.p12"
    echo ""
    echo "  ┌──────────────────────────────────────────────────────┐"
    echo "  │  AirDrop client.p12 to your iPhone:                  │"
    echo "  │                                                      │"
    echo "  │  1. Open Finder → $TLS_DIR/client.p12                │"
    echo "  │  2. AirDrop to iPhone                                │"
    echo "  │  3. iPhone: Settings → Profile Downloaded → Install  │"
    echo "  │  4. Password: $CLIENT_P12_PASSWORD                          │"
    echo "  └──────────────────────────────────────────────────────┘"
    echo ""
fi

# ---------------------------------------------------------------------------
# 4. Tmux wrapper
# ---------------------------------------------------------------------------
echo "[4/4] Claude tmux wrapper..."
mkdir -p "$WRAPPER_DIR"
cp "$DIR/claude-tmux" "$WRAPPER_DIR/claude-tmux"
chmod +x "$WRAPPER_DIR/claude-tmux"
echo "  Installed: $WRAPPER_DIR/claude-tmux"

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
echo "     ./dev.sh 10317 --lan"
echo ""
echo "  2. Start Claude via tmux wrapper:"
echo "     claude-tmux"
echo ""
echo "  3. On your iPhone (with client cert installed), open:"
if [ -n "$TAILSCALE_IP" ]; then
echo "     Same WiFi:  https://$LAN_IP:10316/terminal"
echo "     Any network: https://$TAILSCALE_IP:10316/terminal  (via Tailscale)"
else
echo "     https://$LAN_IP:10316/terminal"
fi
echo ""
echo "  No token needed — mTLS authenticates your device automatically."
echo ""
if [ -z "$TAILSCALE_IP" ]; then
echo "  Tip: Install Tailscale for cross-network access:"
echo "     brew install tailscale"
echo "     Then re-run: ./setup-terminal.sh --regen-server"
fi
