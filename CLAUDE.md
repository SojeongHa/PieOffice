# Pie Office — Project Instructions

## Language Policy

- **All code comments, docstrings, markdown docs, and commit messages**: English only.
- **User-facing conversation**: Follow the user's language preference (e.g., Korean if the user writes in Korean).

## Ports

- **Production**: 10317 — the user's running instance. Do NOT touch.
- **Claude Test**: 10318 — use this port for testing (`./dev.sh 10318`).

## Dev Server

```bash
cd backend && PORT=10318 python3 app.py   # Claude test port
```

### dev.sh Flags

```bash
./dev.sh [port] [--lan] [--tailscale] [--no-sleep]
```

- `--lan` — Enable phone access (WiFi only, same network)
- `--tailscale` — Enable Tailscale for cross-network access (implies `--lan`). Warns if Tailscale is not running.
- `--no-sleep` — Keep Mac awake via `caffeinate -s` while server runs (auto-killed on exit)

## Project Structure

```
PieOffice/
  backend/          # Flask (app.py, state.py, sse.py, terminal.py, terminal_auth.py, terminal_server.py, rate_limiter.py)
  frontend/         # HTML + Phaser 3 + JS modules
    js/             # config, game, agents, sse, ui, i18n, pathfinding, instance-alerts, terminal-client, dialogue
    i18n/           # 16 language JSON files
  editor/           # Tile editor + private generation scripts (gitignored)
  public/script/    # Public character generator + prompts
  theme/default/    # Tilemap, tileset, config, character sprites
    objects/        # Object sprites (furniture, decorations, animated items)
  hook/             # Claude Code hook (pie-office-hook.py)
  docs/             # Screenshots, banner, plans
```

## Key Conventions

- State is **in-memory only** (dict + deque). No file persistence. Server restart = clean slate.
- Character sprites are **128x128 frames** (scaled to 0.75x via `CONFIG.CHAR_SCALE`) on a **32x32 tile** grid.
- Pathfinding is **4-directional** (no diagonals).
- Agent map: base defaults in `theme/default/config.json` under `agent_map`. Personal overrides in `config.local.json` (gitignored) — backend deep-merges `agent_map` per-key at runtime via `/theme/config.json` endpoint. Only changed fields needed; unspecified fields inherit from base. Hook also reads `agent_type_map` and `agent_alias_map` from `config.local.json` for per-user agent type→display name and alias mappings.
- Resident agents (`resident: true` in agent_map) spawn on page load; non-residents appear on hook events and are auto-removed after 60s idle.
- Unmapped agents fall back to `robot` sprite with random pastel tint (Ditto style).
- Tool events are routed to 4 characters: Explorer (Read/Grep/Glob/Bash/WebSearch/WebFetch + search-oriented MCP), Assistant (Write/Edit/NotebookEdit), Planner (Agent/TaskCreate/TaskUpdate), Leader (Skill/AskUserQuestion + non-search MCP).
- SubagentStart reuses resident agents when `agent_type` matches `AGENT_TYPE_MAP` keys (prevents duplicate characters).
- SSE uses `_Listener` class (queue + `created_at` + `stopped` Event) with `threading.Lock` for thread safety. Max 20 concurrent connections (`MAX_LISTENERS`), oldest-first eviction on overflow. 10-minute connection timeout (`MAX_CONNECTION_AGE=600`), periodic `sweep_stale_listeners()` cleanup. `_poison()` helper sets `stopped` Event + attempts poison pill (`None`) — guarantees generator termination even when queue is full. Generator polls every 2s (`queue.get(timeout=2)`), keepalive sent every ~15s via separate timestamp tracking. Active listener count exposed via `/health` endpoint (`sse_listeners`, `open_fds`, `fd_limit`). Server sends `retry: 5000` SSE directive. Client uses manual exponential backoff (1s → 2s → 4s → … → 30s max) instead of EventSource auto-reconnect to prevent FD exhaustion storms after Mac sleep. FD soft limit raised at startup via `resource.setrlimit()`. Four-layer FD leak defense: (1) werkzeug socket timeout (`SOCKET_TIMEOUT=30s`) detects broken connections, (2) sleep detection (sweep gap >30s → force-close all listeners, clients auto-reconnect with backoff), (3) `stream()` try-finally guarantees listener removal on any exit path, (4) `stopped` Event ensures generator exits within 2s even when poison pill cannot be delivered to a full queue.
- Server binds to `127.0.0.1` by default; CORS restricted to localhost ports. LAN mode (`PIE_TERMINAL_LAN=1`) enables `0.0.0.0` binding + TLS for phone access.
- Web terminal: asyncio+websockets+pty server on port 10316 (separate process, NOT Flask thread). Auth via mTLS (CERT_OPTIONAL) + session tokens. Setup: `./scripts/setup-terminal.sh`. NEVER use pty in Flask threads (segfault). NEVER use tmux resize-window -A (locks manual size). Rate limiting: IP-based sliding window (HTTP 30req/min, WS 10conn/min) as defense-in-depth. `setup-terminal.sh` auto-detects Tailscale IP (with userspace socket fallback) for cert SAN; use `--regen-server` to refresh server cert when IPs change. `terminal.html` uses no inline event handlers (CSP `script-src 'self'` compliant); all handlers registered via `addEventListener` in `terminal-client.js`. Terminal server `/sessions` endpoint merges Pie Office alert state (via `/alerts` proxy) into each session entry (`alert_type`, `alert_message`).
- All hook errors logged to stderr (not gated by DEBUG flag).
- Object sprites live in `theme/default/objects/` and are configured in `config.json` under `objects` array.
- Objects support both static images and animated spritesheets (with `anim` property in config).
- Instance alerts: `config.json` → `instance_slots` defines server room computer positions. Hook forwards `session_id`/`cwd` on all events. `permission_prompt`/`idle_prompt` notifications become `instance_alert` SSE events with animated sprites (exclamation/question mark). Non-notification events from same `session_id` auto-clear the alert. Hook `Stop` event sends Leader to idle, triggering alert clear (covers permission denial). `/alerts` endpoint returns pending alerts for terminal server proxy and clears `idle_prompt` on fetch (phone user has seen them). `/alerts/ack` (POST) clears `idle_prompt` from laptop UI after sleep wake (SSE `_open` event → 10s delay → ack).
