---
name: onboard-remote
description: Set up remote terminal access from iPhone to Mac. Installs tmux, generates mTLS certificates, configures claude wrapper, and walks through iPhone setup step by step.
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
```

Report what is installed and what is missing. Install missing items:

- **tmux missing**: `brew install tmux`
- **flask-sock missing**: `cd ~/Documents/workspace/PieOffice && source venv/bin/activate && pip install flask-sock`
- **No WiFi**: Warn the user — WiFi is required for LAN access

### Step 2: Ask Claude Wrapper Preference

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

### Step 3: Generate mTLS Certificates

Run the setup script:

```bash
cd ~/Documents/workspace/PieOffice && ./scripts/setup-terminal.sh
```

If certificates already exist, inform the user and ask whether to regenerate. Regenerating revokes existing iPhone certificates.

If the user wants to regenerate:
```bash
cd ~/Documents/workspace/PieOffice && ./scripts/setup-terminal.sh --revoke && ./scripts/setup-terminal.sh
```

### Step 4: iPhone Certificate Installation Guide

Walk the user through installing the client certificate on their iPhone:

1. Open Finder and navigate to `~/.pieoffice-tls/client.p12`
   - Finder → Go → Go to Folder → `~/.pieoffice-tls`
2. AirDrop the `client.p12` file to iPhone
3. On iPhone: Settings → General → VPN & Device Management
4. Tap "Profile Downloaded" → Install
5. Enter password: `pieoffice`
6. Installation complete

Ask the user to confirm they have completed the certificate installation before proceeding.

### Step 5: Test Connection

Start the server on the test port and guide the user through testing:

```bash
cd ~/Documents/workspace/PieOffice
PIE_TERMINAL_LAN=1 PORT=10318 python3 backend/app.py &
SERVER_PID=$!
LAN_IP=$(ipconfig getifaddr en0)
echo "Open on iPhone: https://$LAN_IP:10318/terminal"
```

Tell the user to open `https://<LAN_IP>:10318/terminal` in iPhone Safari.

Expected behavior:
- First visit shows a privacy warning → tap Advanced → Proceed
- Safari prompts to select a client certificate → select the installed one
- Page shows "Authenticating device..." then the session list appears
- If a claude-tmux session is running, it appears in the sidebar

Wait for the user to confirm it works.

After testing, kill the test server:
```bash
kill $SERVER_PID 2>/dev/null
```

### Step 6: Summary

Print the final usage guide covering:

- How to start Pie Office in LAN mode: `./dev.sh 10317 --lan`
- How to start a Claude session: `claude-tmux` (or `claude` if alias was chosen)
- How to connect from iPhone: `https://<LAN_IP>:10317/terminal`
- Certificate management: `--revoke` to revoke, re-run to regenerate
- Optional iOS Shortcut for one-tap access: see `docs/ios-shortcut-setup.md`
