# Pie Office v1.0.0

**Release Date:** 2026-03-20
**101 commits** | Initial public release

---

## What is Pie Office?

Pie Office is a pixel-art virtual office that visualizes Claude Code agent activity in real time. Characters walk around, sit at desks, and react to tool calls — giving you a living dashboard of what your AI agents are doing.

---

## Features

### Core Office Simulation
- **Phaser 3 game engine** with 32x32 tile grid and 128x128 character sprites
- **4-directional pathfinding** with collision detection on tilemap
- **Agent-to-character mapping** via `config.json` (`agent_map`) with per-user overrides in `config.local.json` (gitignored)
- **Resident agents** spawn on page load; non-resident agents appear on hook events and auto-remove after 60s idle
- **Unmapped agents** fall back to `robot` sprite with random pastel tint (Ditto style)
- **Tool-event routing** to 4 character roles: Explorer (Read/Grep/Glob/Bash/WebSearch/WebFetch + search MCP), Assistant (Write/Edit/NotebookEdit), Planner (Agent/TaskCreate/TaskUpdate), Leader (Skill/AskUserQuestion + non-search MCP)
- **SubagentStart** reuses resident agents when `agent_type` matches, preventing duplicate characters
- **Object sprites** — static images and animated spritesheets for furniture and decorations

### Real-Time SSE Event Stream
- **Server-Sent Events** with `_Listener` class (queue + threading.Lock)
- **Max 20 concurrent connections** with oldest-first eviction
- **10-minute connection timeout** with periodic stale listener sweep
- **Six-layer FD leak defense:**
  1. Werkzeug socket timeout (30s) detects broken connections
  2. Sleep detection (sweep gap >30s → force-close all listeners)
  3. `stream()` try-finally guarantees listener removal
  4. `stopped` Event ensures generator exits within 2s
  5. Client-side exponential backoff (1s → 2s → 4s → … → 30s max)
  6. FD soft limit raised at startup + health endpoint monitoring (`sse_listeners`, `open_fds`, `fd_limit`)

### Claude Code Hook Integration
- **`hook/pie-office-hook.py`** — captures PreToolUse, PostToolUse, SubagentStart, SubagentStop, Stop, Notification, TeammateIdle, and TaskCompleted events
- Forwards `session_id` and `cwd` on all events for instance alert routing
- All hook errors logged to stderr (not gated by DEBUG flag)

### Instance Alerts (Server Room)
- **`instance_slots`** in config defines server room computer positions
- `permission_prompt` and `idle_prompt` notifications become `instance_alert` SSE events with animated sprites (exclamation/question mark)
- Non-notification events from the same `session_id` auto-clear alerts
- Hook `Stop` event sends Leader to idle, triggering alert clear
- `idle_prompt` cleared on "seen" (phone fetch via `/alerts` or laptop sleep-wake ack via `/alerts/ack`)
- `permission_prompt` cleared by Stop hook (covers permission denial)

### Web Terminal (iPhone Remote Access)
- **asyncio + websockets + pty** server on port 10316 (separate process, NOT Flask thread)
- **mTLS authentication** (CERT_OPTIONAL) + session tokens
- **Slack-style frontend** with session list, auto-sync, and Korean IME support
- **tmux integration** — attach to existing sessions, shared multi-client support
- **Touch-optimized UI:**
  - Text input bar with IME composition support
  - Scroll mode toggle with natural touch scrolling (5px per line)
  - Arrow up/down quick buttons, Tab key, number keys (1/2/3), Enter, Clear
  - CSP-compliant event handlers (no inline `onclick`)
- **Caffeinate** keeps Mac awake during active phone terminal sessions (WebSocket-based, auto off on disconnect)
- **Rate limiting** — IP-based sliding window (HTTP 30req/min, WS 10conn/min)
- **`.mobileconfig` generator** for one-step iPhone certificate setup

### Tailscale VPN Support
- Cross-network phone access via Tailscale (100.x.x.x)
- `setup-terminal.sh` auto-detects Tailscale IP (with userspace socket fallback) for cert SAN
- `--regen-server` flag to refresh server cert when IPs change
- LAN mode (`PIE_TERMINAL_LAN=1`) enables `0.0.0.0` binding + TLS
- App Store install guide (recommended over brew)
- `dev.sh` Tailscale status check with warning loop in LAN mode

### Security
- Server binds `127.0.0.1` by default; CORS restricted to localhost ports
- mTLS device-level authentication for web terminal
- IP-based rate limiting as defense-in-depth
- CSP `script-src 'self'` — all handlers via `addEventListener`
- No inline event handlers anywhere in the codebase

### Internationalization
- **16 languages** supported via `frontend/i18n/` JSON files
- Language auto-detection with manual override

### Developer Experience
- **`dev.sh`** — single entry point: `[port]`, `--lan` (WiFi), `--tailscale` (cross-network), `--no-sleep` (caffeinate)
- **Port convention:** 10317 (production), 10318 (Claude test)
- **In-memory state only** — server restart = clean slate, no persistence layer to manage
- **Tile editor** in `editor/` for tilemap authoring
- **Character generator** in `public/script/` with prompts

---

## Architecture

```
Browser (Phaser 3)  ←—SSE—→  Flask backend (app.py)  ←—hook—→  Claude Code
                                    ↓
iPhone (terminal.html) ←—WSS—→  Terminal server (terminal_server.py, port 10316)
                                    ↓
                                tmux sessions
```

- **Backend:** Flask with in-memory state (dict + deque)
- **Frontend:** Vanilla HTML + Phaser 3 + JS modules
- **Terminal:** asyncio + websockets + pty (separate process)
- **Hook:** Python script invoked by Claude Code on tool events

---

## Getting Started

```bash
# Start on default port (10317)
./dev.sh

# Start on custom port
./dev.sh 10318

# Start with WiFi phone access
./dev.sh --lan

# Start with Tailscale cross-network access
./dev.sh --lan --tailscale

# Keep Mac awake while server runs (for away-from-desk use)
./dev.sh --lan --tailscale --no-sleep

# Setup terminal for iPhone
./scripts/setup-terminal.sh
```

---

## Contributors

- [@SojeongHa](https://github.com/SojeongHa)
