# Pie Office — Project Instructions

## Language Policy

- **All code comments, docstrings, markdown docs, and commit messages**: English only.
- **User-facing conversation**: Follow the user's language preference (e.g., Korean if the user writes in Korean).

## Ports

- **Production**: 10317 — the user's running instance. Do NOT touch.
- **Claude Test**: 10318 — use this port for testing (`./dev.sh 10318`).

## Dev Server

```bash
./dev.sh          # starts on port 10318 (default)
./dev.sh 10317    # production port
```

## Project Structure

```
pie-office/
  backend/          # Flask (app.py, state.py, sse.py)
  frontend/         # HTML + Phaser 3 + JS modules
    js/             # config, game, agents, sse, ui, i18n, pathfinding, instance-alerts
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
- Agent map lives in `theme/default/config.json` under `agent_map`.
- Resident agents (`resident: true` in agent_map) spawn on page load; non-residents appear on hook events and are auto-removed after 60s idle.
- Unmapped agents fall back to `robot` sprite with random pastel tint (Ditto style).
- Tool events are routed to 4 characters: Explorer (Read/Grep/Glob/Bash/WebSearch/WebFetch), Assistant (Write/Edit/NotebookEdit), Planner (Agent/TaskCreate/TaskUpdate), Leader (Skill/MCP/AskUser).
- SubagentStart reuses resident agents when `agent_type` matches `AGENT_TYPE_MAP` keys (prevents duplicate characters).
- SSE uses `threading.Lock` for thread safety and sends keepalive every 15s.
- Server binds to `127.0.0.1` only; CORS restricted to localhost ports.
- All hook errors logged to stderr (not gated by DEBUG flag).
- Object sprites live in `theme/default/objects/` and are configured in `config.json` under `objects` array.
- Objects support both static images and animated spritesheets (with `anim` property in config).
- Instance alerts: `config.json` → `instance_slots` defines server room computer positions. Hook forwards `session_id`/`cwd` on all events. `permission_prompt`/`idle_prompt` notifications become `instance_alert` SSE events with animated sprites (exclamation/question mark).
