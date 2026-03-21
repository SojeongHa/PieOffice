---
name: onboard-remote
description: Set up remote terminal access from iPhone to Mac. Installs tmux, Tailscale VPN, generates mTLS certificates, configures claude wrapper, and walks through iPhone setup step by step. Supports both LAN-only and cross-network (Tailscale) modes.
---

# Onboard Remote Terminal

Interactive onboarding for accessing Claude Code from your phone via the Pie Office web terminal.

## Process

Walk through each step interactively. Run checks, install what's missing, and confirm with the user before moving on. Conversation with the user should follow their language preference (typically Korean). Skill file content stays in English.

### Step 1: Check Prerequisites

Run these checks silently and report results:

```bash
# Check tmux
which tmux 2>/dev/null && tmux -V || echo "MISSING"

# Check openssl
which openssl 2>/dev/null && openssl version || echo "MISSING"

# Check Pie Office venv
test -d ~/Documents/workspace/PieOffice/venv && echo "OK" || echo "MISSING"

# Check flask-sock installed
cd ~/Documents/workspace/PieOffice && source venv/bin/activate && pip show flask-sock 2>/dev/null | head -2 || echo "MISSING"

# Check LAN IP
ipconfig getifaddr en0 2>/dev/null || echo "NO_WIFI"

# Check Tailscale
which tailscale 2>/dev/null && tailscale status 2>/dev/null | head -1 || echo "NOT_INSTALLED"
```

Report what is installed and what is missing. Install missing items:

- **tmux missing**: `brew install tmux`
- **flask-sock missing**: `cd ~/Documents/workspace/PieOffice && source venv/bin/activate && pip install flask-sock`
- **No WiFi**: Warn the user — WiFi is required for LAN access (Tailscale can work without WiFi via cellular)

### Step 2: Ask Network Mode

Ask the user which access mode they need:

1. **LAN only** — same WiFi only, simplest setup
2. **Tailscale (recommended)** — access from any network (LTE, different WiFi, etc.)

If the user chooses Tailscale (or already expressed interest in cross-network access), proceed with Step 2a. Otherwise skip to Step 3.

#### Step 2a: Install and Configure Tailscale

**Mac setup (App Store recommended):**

1. App Store → search "Tailscale" → install (or `open https://apps.apple.com/app/tailscale/id1475387142`)
2. Open the Tailscale app from Applications / menu bar
3. Sign in via browser when prompted
4. Click "Connect" in the menu bar icon

Verify:
```bash
tailscale status | head -5
tailscale ip -4  # Note the 100.x.x.x IP
```

Note: The App Store version manages the daemon automatically — no `sudo tailscaled` or `brew install` needed.

**iPhone setup** — instruct the user:
1. App Store → search "Tailscale" → install
2. Open Tailscale app → sign in with the **same account** used on Mac
3. Toggle VPN on when prompted
4. Verify both devices appear in `tailscale status`

Ask the user to confirm both devices are connected before proceeding.

### Step 3: Ask Claude Wrapper Preference

Ask the user which approach they prefer:

1. **`claude-tmux` as a separate command** — existing `claude` stays untouched, use `claude-tmux` when you want tmux wrapping (default)
2. **Replace `claude` with alias** — `claude` itself runs inside tmux via alias in `~/.zshrc`

Wait for the user's choice before proceeding.

**Option 1 (claude-tmux, default):**
- Install `scripts/claude-tmux` to `~/.local/bin/claude-tmux`
- Ensure `~/.local/bin` is in PATH (add to `~/.zshrc` if needed)

**Option 2 (claude alias):**
- Install `scripts/claude-tmux` to `~/.local/bin/claude-tmux`
- Ensure `~/.local/bin` is in PATH
- Append alias to `~/.zshrc`: `alias claude='claude-tmux'`
- Warn the user that the original `claude` command is now shadowed by the tmux wrapper. To revert, remove the alias line from `~/.zshrc`.

After installing, verify:

```bash
# For option 1:
which claude-tmux && echo "OK"

# For option 2:
grep 'alias claude=' ~/.zshrc && echo "OK"
```

### Step 4: Generate mTLS Certificates

If Tailscale is installed, `setup-terminal.sh` automatically detects the Tailscale IP and includes it in the server certificate SAN. No manual configuration needed.

Run the setup script, then generate the signed `.mobileconfig` bundle:

```bash
cd ~/Documents/workspace/PieOffice && ./scripts/setup-terminal.sh
cd ~/Documents/workspace/PieOffice && ./scripts/generate-mobileconfig.sh
```

If certificates already exist, inform the user and ask whether to regenerate. Regenerating revokes existing iPhone certificates.

If the user wants to regenerate (e.g., Tailscale was installed after initial setup):
```bash
cd ~/Documents/workspace/PieOffice && ./scripts/setup-terminal.sh --regen-server && ./scripts/generate-mobileconfig.sh
```

If the user wants a full revoke + regenerate:
```bash
cd ~/Documents/workspace/PieOffice && ./scripts/setup-terminal.sh --revoke && ./scripts/setup-terminal.sh && ./scripts/generate-mobileconfig.sh
```

**Important:** When Tailscale IP changes or is newly added, use `--regen-server` to regenerate the server certificate with the updated SAN. Client certificates do not need to change.

### Step 5: iPhone Certificate Installation Guide

The `.mobileconfig` file bundles CA + client certificate in a single signed profile. Only one file to install.

Open the certificate directory in Finder for the user:
```bash
open ~/.pieoffice-tls/
```

1. AirDrop `PieOffice.mobileconfig` to iPhone
2. On iPhone: Settings → General → VPN & Device Management
3. Tap "Profile Downloaded" → Install the "PieOffice Remote Terminal" profile
4. Go to Settings → General → About → Certificate Trust Settings
5. Toggle ON "PieOffice CA" under "Enable Full Trust For Root Certificates"

Ask the user to confirm they have completed the installation before proceeding.

### Step 6: Test Connection

Tell the user to open a **separate terminal tab** and run:

```bash
cd ~/Documents/workspace/PieOffice && ./dev.sh --lan
```

Then get the connection IP:
```bash
# LAN IP (same WiFi)
ipconfig getifaddr en0

# Tailscale IP (any network)
tailscale ip -4
```

Tell the user to test based on their setup:

- **LAN**: `https://<LAN_IP>:10316/` (same WiFi only)
- **Tailscale**: `https://<TAILSCALE_IP>:10316/` (any network — try from LTE to verify)

Expected behavior:
- First visit shows a privacy warning → tap Advanced → Proceed
- Safari prompts to select a client certificate → select the installed one
- Page shows "Authenticating device..." then the session list appears
- If a claude-tmux session is running, it appears in the sidebar

If using Tailscale, suggest testing from cellular (WiFi off) to confirm cross-network access works.

Wait for the user to confirm it works.

### Step 7: Summary

Print the final usage guide covering:

- How to start Pie Office in LAN mode: `./dev.sh --lan` (in a separate terminal tab)
- How to start a Claude session: `claude-tmux` (or `claude` if alias was chosen)
- Connection options:
  - Same WiFi: `https://<LAN_IP>:10316/`
  - Any network (Tailscale): `https://<TAILSCALE_IP>:10316/`
- Security layers (explain briefly):
  - **Tailscale VPN**: only authenticated devices can reach the server (no public port exposure)
  - **mTLS**: client certificate validates the specific device
  - **Rate limiter**: IP-based request throttling (30 HTTP req/min, 10 WS conn/min) as defense-in-depth
- Certificate management:
  - `--revoke` to revoke client certs, re-run to regenerate
  - `--regen-server` to regenerate server cert (when IPs change or Tailscale added)
- Optional iOS Shortcut for one-tap access: see `docs/ios-shortcut-setup.md`
