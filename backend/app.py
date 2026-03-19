"""Pie Office — Flask backend with SSE broadcasting and hook endpoint."""

import json
import os
import resource
import sys
import threading
import time

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_sock import Sock

from terminal import handle_terminal_ws, list_tmux_sessions
from terminal_auth import generate_token, validate_token
from config import TERMINAL_LAN_MODE, TERMINAL_TOKEN_PATH, TERMINAL_TLS_CERT, TERMINAL_TLS_KEY

# ---------------------------------------------------------------------------
# Raise FD soft limit — prevents "Too many open files" after Mac sleep
# when SSE reconnections create many concurrent werkzeug sockets.
# ---------------------------------------------------------------------------
_soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
_target = min(8192, _hard) if _hard != resource.RLIM_INFINITY else 8192
if _soft < _target:
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (_target, _hard))
        print(f"[Init] Raised FD soft limit: {_soft} → {_target}", file=sys.stderr)
    except (ValueError, OSError) as e:
        print(f"[Init] Could not raise FD limit: {e}", file=sys.stderr)

from sse import MessageAnnouncer
from state import (
    append_hook_log,
    clear_agents,
    clear_instance_alert,
    get_agent,
    get_agents,
    get_hook_log,
    get_instances,
    init_room_map,
    register_subagent,
    remove_agent,
    resolve_subagent,
    set_agent,
    set_instance_alert,
    sweep_idle_nonresident,
    sweep_stale_agents,
    sweep_stale_instances,
    sweep_stale_subagents,
    track_instance,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
from config import LEAVE_DELAY

PORT = int(os.environ.get("PORT", 10317))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEBUG = os.environ.get("PIE_OFFICE_DEBUG", "").lower() in ("1", "true")


def _validate_theme_name(name: str) -> str:
    """Ensure theme name is a safe directory component (no path traversal)."""
    if not name or ".." in name or "/" in name or "\\" in name:
        print(f"[Config] Invalid theme name '{name}', falling back to 'default'", file=sys.stderr)
        return "default"
    return name


THEME = _validate_theme_name(os.environ.get("THEME", "default"))

# Pending leave timers: agent_id -> threading.Timer
_leave_timers: dict[str, threading.Timer] = {}
_leave_timers_lock = threading.Lock()

# Load project config: config.json (base) + config.local.json (override)
APP_CONFIG = {}
for _cfg_name in ("config.json", "config.local.json"):
    _cfg_path = os.path.join(PROJECT_ROOT, _cfg_name)
    if os.path.exists(_cfg_path):
        try:
            with open(_cfg_path) as _f:
                APP_CONFIG.update(json.load(_f))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[Config] Failed to parse {_cfg_name}: {e}", file=sys.stderr)
CHARACTER_THEME = _validate_theme_name(APP_CONFIG.get("character_theme") or "default")
if CHARACTER_THEME == "default":
    CHARACTER_THEME = None  # No override needed when theme is default
# Local agent_map overrides (partial deep merge into theme config)
_LOCAL_AGENT_MAP = APP_CONFIG.get("agent_map", {})

# Load theme config for state_room_map
_theme_cfg_path = os.path.join(PROJECT_ROOT, "theme", THEME, "config.json")
_theme_config = {}
if os.path.exists(_theme_cfg_path):
    with open(_theme_cfg_path) as _f:
        _theme_config = json.load(_f)
init_room_map(_theme_config.get("state_room_map", {"idle": "break"}))
INSTANCE_SLOT_COUNT = len(_theme_config.get("instance_slots", []))

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder=None)
if TERMINAL_LAN_MODE:
    CORS(app)
else:
    CORS(app, origins=[
        "http://localhost:10317", "http://localhost:10318",
        "http://127.0.0.1:10317", "http://127.0.0.1:10318",
    ])
sock = Sock(app)
announcer = MessageAnnouncer()

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return send_from_directory(os.path.join(PROJECT_ROOT, "frontend"), "index.html")


def _open_fd_count() -> int:
    """Count open file descriptors for this process (macOS/Linux)."""
    try:
        return len(os.listdir(f"/dev/fd"))
    except OSError:
        return -1


@app.route("/health")
def health():
    fd_count = _open_fd_count()
    fd_soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
    return jsonify({
        "status": "ok",
        "theme": THEME,
        "timestamp": time.time(),
        "sse_listeners": announcer.listener_count,
        "open_fds": fd_count,
        "fd_limit": fd_soft,
    })


@app.route("/state")
def state():
    return jsonify({"agents": get_agents(), "log": get_hook_log(20), "instances": get_instances()})


@app.route("/stream")
def stream():
    listener = announcer.listen()

    def event_stream():
        yield from announcer.stream(listener)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _cancel_leave_timer(agent_id: str):
    """Cancel a pending leave timer for the given agent."""
    with _leave_timers_lock:
        timer = _leave_timers.pop(agent_id, None)
    if timer:
        timer.cancel()


def _cancel_all_leave_timers():
    """Cancel all pending leave timers."""
    with _leave_timers_lock:
        timers = list(_leave_timers.values())
        _leave_timers.clear()
    for t in timers:
        t.cancel()


def _schedule_leave(agent_id: str, agent_name: str):
    """Schedule an agent to leave after LEAVE_DELAY seconds."""
    _cancel_leave_timer(agent_id)
    scheduled_at = time.time()

    def _do_leave():
        with _leave_timers_lock:
            _leave_timers.pop(agent_id, None)
        # Guard against race: if the agent was updated after this timer
        # was scheduled (e.g., re-joined via a new hook event), skip removal.
        agent = get_agent(agent_id)
        if agent and agent.get("updated_at", 0) > scheduled_at:
            return
        removed = remove_agent(agent_id)
        if removed:
            announcer.announce(removed, event="agent_leave")

    timer = threading.Timer(LEAVE_DELAY, _do_leave)
    timer.daemon = True
    with _leave_timers_lock:
        _leave_timers[agent_id] = timer
    timer.start()


@app.route("/hook", methods=["POST"])
def hook():
    payload = request.get_json(force=True, silent=True)
    if not payload:
        return jsonify({"error": "invalid JSON"}), 400

    event_type = payload.get("event")
    agent_id = payload.get("agent_id") or payload.get("agentId") or "unknown"
    agent_name = payload.get("agent_name") or payload.get("agentName") or agent_id

    # Log every hook event
    append_hook_log({"event": event_type, "agent_id": agent_id, "payload": payload})

    # Track instance by session_id
    session_id = payload.get("session_id", "")
    cwd = payload.get("cwd", "")
    if session_id and INSTANCE_SLOT_COUNT > 0:
        track_instance(session_id, cwd, INSTANCE_SLOT_COUNT)
        # Clear alert if this is a non-notification event from a session with active alert
        if event_type != "instance_alert":
            cleared = clear_instance_alert(session_id)
            if cleared:
                announcer.announce(cleared, event="instance_alert_clear")

    # Cancel any pending leave timer when the agent gets new activity
    if event_type not in ("SubagentStop", "shutdown", "agent_leave", "team_delete"):
        _cancel_leave_timer(agent_id)

    if event_type in ("SubagentStart", "agent_join"):
        _cancel_leave_timer(agent_id)
        agent_state = payload.get("state", "idle")
        agent = set_agent(agent_id, {
            "name": agent_name,
            "state": agent_state,
            "type": payload.get("agent_type", "general"),
        }, resident=False)
        # Track subagent instance name → agent_id for SubagentStop resolution
        subagent_name = payload.get("subagent_name")
        if subagent_name:
            register_subagent(subagent_name, agent_id)
        announcer.announce(agent, event="agent_join")

    elif event_type == "agent_update":
        agent_state = payload.get("state", "idle")
        update_data = {
            "name": agent_name,
            "state": agent_state,
        }
        # Preserve agent_type if provided (needed for sprite mapping)
        agent_type = payload.get("agent_type")
        if agent_type:
            update_data["type"] = agent_type
        # Pass through detail for bubble text
        detail = payload.get("detail")
        if detail:
            update_data["detail"] = detail
        agent = set_agent(agent_id, update_data)
        announcer.announce(agent, event="agent_update")

    elif event_type in ("SubagentStop", "shutdown", "agent_leave"):
        # Resolve subagent instance name → correct agent_id (server-side mapping)
        if event_type == "SubagentStop":
            agent_id = resolve_subagent(agent_name)
        _schedule_leave(agent_id, agent_name)

    elif event_type == "agent_chat":
        message = payload.get("message", "")
        data = {"id": agent_id, "name": agent_name, "message": message}
        set_agent(agent_id, {"name": agent_name, "state": "writing"})
        announcer.announce(data, event="agent_chat")

    elif event_type == "instance_alert":
        notification_type = payload.get("notification_type", "")
        message = payload.get("message", "")
        session_id_val = payload.get("session_id", "")
        if session_id_val and notification_type:
            inst = set_instance_alert(session_id_val, notification_type, message)
            if inst:
                announcer.announce(inst, event="instance_alert")

    elif event_type == "team_delete":
        # All agents leave immediately
        _cancel_all_leave_timers()
        agents = get_agents()
        for aid, adata in agents.items():
            announcer.announce(adata, event="agent_leave")
        clear_agents()

    else:
        # Unknown event — still broadcast it as a generic update
        announcer.announce(payload, event=event_type or "unknown")

    return jsonify({"ok": True})


@app.route("/test/simulate", methods=["POST"])
def test_simulate():
    """Run a mock agent lifecycle scenario via time-delayed SSE events.
    Only available when PIE_OFFICE_DEBUG=1."""
    if not DEBUG:
        return jsonify({"error": "debug mode disabled"}), 404
    scenario = request.args.get("scenario", "basic")
    if scenario not in ("basic", "team"):
        return jsonify({"error": f"unknown scenario: {scenario}"}), 400

    def _join(agent_id, name, agent_type):
        agent = set_agent(agent_id, {"name": name, "state": "idle", "type": agent_type})
        announcer.announce(agent, event="agent_join")

    def _update(agent_id, name, state):
        agent = set_agent(agent_id, {"name": name, "state": state})
        announcer.announce(agent, event="agent_update")

    def _chat(agent_id, name, message):
        set_agent(agent_id, {"name": name, "state": "writing"})
        announcer.announce({"id": agent_id, "name": name, "message": message}, event="agent_chat")

    def _leave(agent_id):
        removed = remove_agent(agent_id)
        data = removed or {"id": agent_id}
        announcer.announce(data, event="agent_leave")

    def run_basic():
        _update("Explore", "Explorer", "researching"); time.sleep(2)
        _update("frontend", "Frontend", "writing"); time.sleep(1)
        _chat("Explore", "Explorer", "Found the bug!"); time.sleep(3)
        _update("Explore", "Explorer", "executing"); time.sleep(2)
        _update("frontend", "Frontend", "reading"); time.sleep(2)
        _update("Explore", "Explorer", "idle"); time.sleep(3)
        _update("frontend", "Frontend", "idle")

    def run_team():
        time.sleep(1)
        # Batch 1
        _update("main", "Leader", "executing"); time.sleep(0.5)
        _update("frontend", "Frontend", "writing"); time.sleep(0.5)
        _update("Explore", "Explorer", "researching"); time.sleep(3)
        # Batch 2
        _update("backend", "Backend", "writing"); time.sleep(0.5)
        _update("Plan", "Planner", "reading"); time.sleep(3)
        # Batch 3
        _update("frontend", "Frontend", "executing"); time.sleep(0.5)
        _update("Explore", "Explorer", "reading"); time.sleep(0.5)
        _update("main", "Leader", "researching"); time.sleep(3)
        # Chat
        _chat("Explore", "Explorer", "Found the issue!"); time.sleep(2)
        _chat("frontend", "Frontend", "Fixing now..."); time.sleep(3)
        # Back to idle
        _update("main", "Leader", "idle"); time.sleep(0.3)
        _update("frontend", "Frontend", "idle"); time.sleep(0.3)
        _update("backend", "Backend", "idle"); time.sleep(0.3)
        _update("Explore", "Explorer", "idle"); time.sleep(0.3)
        _update("Plan", "Planner", "idle")

    runner = run_basic if scenario == "basic" else run_team
    threading.Thread(target=runner, daemon=True).start()
    return jsonify({"ok": True, "scenario": scenario, "status": "started"})


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(os.path.join(PROJECT_ROOT, "frontend"), filename)


@app.route("/tools/<path:filename>")
def tools_files(filename):
    return send_from_directory(os.path.join(PROJECT_ROOT, "tools"), filename)


@app.route("/tools/save-collision", methods=["POST"])
def save_collision():
    """Save tilemap.json and room_areas.json from the collision editor.
    Only available in debug mode to prevent accidental overwrites."""
    if not DEBUG:
        return jsonify({"error": "save-collision requires PIE_OFFICE_DEBUG=1"}), 403
    data = request.get_json(force=True)
    theme_dir = os.path.join(PROJECT_ROOT, "theme", THEME)
    saved = []
    if "tilemap" in data:
        path = os.path.join(theme_dir, "tilemap.json")
        with open(path, "w") as f:
            json.dump(data["tilemap"], f)
        saved.append("tilemap.json")
    if "room_areas" in data:
        path = os.path.join(theme_dir, "room_areas.json")
        with open(path, "w") as f:
            json.dump(data["room_areas"], f, indent=2)
        saved.append("room_areas.json")
    return jsonify({"ok": True, "saved": saved})


@app.route("/theme/<path:filename>")
def theme_file(filename):
    # For config.json, apply local agent_map overrides (deep merge)
    if filename == "config.json" and _LOCAL_AGENT_MAP:
        theme_dir = os.path.join(PROJECT_ROOT, "theme", THEME)
        cfg_path = os.path.join(theme_dir, "config.json")
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path) as f:
                    cfg = json.load(f)
            except (json.JSONDecodeError, ValueError):
                cfg = {}
            base_map = cfg.get("agent_map", {})
            for key, overrides in _LOCAL_AGENT_MAP.items():
                if key in base_map:
                    base_map[key] = {**base_map[key], **overrides}
                else:
                    base_map[key] = overrides
            cfg["agent_map"] = base_map
            return jsonify(cfg)
    # Try character_theme override first, fall back to default
    if CHARACTER_THEME:
        override_dir = os.path.join(PROJECT_ROOT, "theme", CHARACTER_THEME)
        override_path = os.path.join(override_dir, filename)
        if os.path.isfile(override_path):
            return send_from_directory(override_dir, filename)
    theme_dir = os.path.join(PROJECT_ROOT, "theme", THEME)
    return send_from_directory(theme_dir, filename)


# ---------------------------------------------------------------------------
# Terminal routes
# ---------------------------------------------------------------------------


@app.route("/terminal")
def terminal_page():
    return send_from_directory(os.path.join(PROJECT_ROOT, "frontend"), "terminal.html")


@app.route("/terminal/sessions")
def terminal_sessions():
    """List available Claude tmux sessions (requires token in Authorization header)."""
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not validate_token(token, TERMINAL_TOKEN_PATH):
        return jsonify({"error": "unauthorized"}), 401
    sessions = list_tmux_sessions()
    return jsonify({
        "sessions": [
            {"name": s.name, "windows": s.windows, "attached": s.attached, "cwd": s.cwd}
            for s in sessions
        ]
    })


@sock.route("/terminal/ws/<session_name>")
def terminal_ws(ws, session_name):
    """WebSocket endpoint for terminal I/O relay to a tmux session."""
    handle_terminal_ws(ws, session_name)


# ---------------------------------------------------------------------------
# Stale agent sweep — background thread
# ---------------------------------------------------------------------------
def _stale_sweep_loop():
    """Periodically check for stale agents and broadcast idle transitions."""
    while True:
        time.sleep(5)
        try:
            changed = sweep_stale_agents()
            for agent_data in changed:
                announcer.announce(agent_data, event="agent_update")
            # Remove non-resident agents that have been idle too long
            removed = sweep_idle_nonresident()
            for agent_data in removed:
                announcer.announce(agent_data, event="agent_leave")
            # Clean up orphaned subagent map entries
            sweep_stale_subagents()
            # Release stale instance slots
            stale_instances = sweep_stale_instances()
            for sid in stale_instances:
                announcer.announce({"session_id": sid}, event="instance_slot_release")
            # Sweep stale SSE connections to prevent file descriptor leaks
            announcer.sweep_stale_listeners()
        except Exception as e:
            print(f"[Sweep] Error in stale sweep: {e}", file=sys.stderr)


threading.Thread(target=_stale_sweep_loop, daemon=True).start()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Pie Office backend starting on :{PORT} (theme={THEME})")
    import socketserver

    from config import SOCKET_TIMEOUT
    from werkzeug.serving import WSGIRequestHandler

    # Set socket timeout to detect broken connections faster (e.g., after Mac sleep)
    socketserver.TCPServer.timeout = SOCKET_TIMEOUT
    WSGIRequestHandler.timeout = SOCKET_TIMEOUT

    host = "0.0.0.0" if TERMINAL_LAN_MODE else "127.0.0.1"
    ssl_ctx = None
    if TERMINAL_LAN_MODE:
        token = generate_token(TERMINAL_TOKEN_PATH)
        print(f"[Terminal] LAN mode enabled — host={host}", file=sys.stderr)
        print(f"[Terminal] Auth token: {token}", file=sys.stderr)
        if os.path.isfile(TERMINAL_TLS_CERT) and os.path.isfile(TERMINAL_TLS_KEY):
            ssl_ctx = (TERMINAL_TLS_CERT, TERMINAL_TLS_KEY)
            print("[Terminal] TLS enabled", file=sys.stderr)
        else:
            print("[Terminal] WARNING: No TLS cert found. Run setup-terminal.sh first.",
                  file=sys.stderr)

    app.run(host=host, port=PORT, threaded=True, debug=False, ssl_context=ssl_ctx)
