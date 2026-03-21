"""Thread-safe in-memory agent state management."""

import collections
import threading
import time

from config import (
    HOOK_LOG_MAX,
    IDLE_REMOVE_THRESHOLD,
    INSTANCE_SLOT_TIMEOUT,
    LINGER_THRESHOLD,
    STALE_EXEMPT_STATES,
    STALE_THRESHOLD,
)

STATE_ROOM_MAP: dict[str, str] = {}


def init_room_map(room_map: dict[str, str]) -> None:
    """Initialize STATE_ROOM_MAP from external config (theme config.json)."""
    global STATE_ROOM_MAP
    STATE_ROOM_MAP = room_map

_lock = threading.Lock()
_agents: dict[str, dict] = {}
_hook_log: collections.deque = collections.deque(maxlen=HOOK_LOG_MAX)
_subagent_map: dict[str, str] = {}  # subagent instance name → resolved agent_id

# Instance tracking: session_id → assigned slot + alert state
_instances: dict[str, dict] = {}
_slot_assignments: dict[int, str] = {}  # slot_index → session_id


def get_agents() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _agents.items()}


def get_agent(agent_id: str) -> dict | None:
    with _lock:
        agent = _agents.get(agent_id)
        return dict(agent) if agent else None


def set_agent(agent_id: str, agent_data: dict, resident: bool | None = None) -> dict:
    with _lock:
        existing = _agents.get(agent_id, {})
        updated = {**existing, **agent_data}
        updated["id"] = agent_id
        updated["updated_at"] = time.time()
        if resident is not None:
            updated["resident"] = resident
        state = updated.get("state", "idle")
        # "permission" state: agent stays in current room (no reassignment)
        if state != "permission":
            updated["room"] = STATE_ROOM_MAP.get(state, "break")
        _agents[agent_id] = updated
        return dict(updated)


def remove_agent(agent_id: str) -> dict | None:
    with _lock:
        return _agents.pop(agent_id, None)


def clear_agents() -> None:
    with _lock:
        _agents.clear()


def get_hook_log(limit: int = 20) -> list:
    with _lock:
        return list(_hook_log)[-limit:]


def sweep_stale_agents() -> list[dict]:
    """Two-phase stale sweep: active → lingering → idle.

    Phase 1: Active agents past STALE_THRESHOLD become "lingering" (stay in current room).
    Phase 2: Lingering agents past LINGER_THRESHOLD become "idle" (return to break room).
    Returns list of agents that were changed (for SSE broadcast).
    """
    now = time.time()
    changed = []
    with _lock:
        for agent_id, agent in _agents.items():
            state = agent.get("state", "idle")
            if state in STALE_EXEMPT_STATES:
                # Check lingering agents for phase 2 transition
                if state == "lingering":
                    age = now - agent.get("updated_at", 0)
                    if age > LINGER_THRESHOLD:
                        updated = {**agent, "state": "idle", "room": STATE_ROOM_MAP.get("idle", "break"), "updated_at": now}
                        _agents[agent_id] = updated
                        changed.append(dict(updated))
                continue
            age = now - agent.get("updated_at", 0)
            if age > STALE_THRESHOLD:
                # Phase 1: stay in current room, just go lingering
                updated = {**agent, "state": "lingering", "updated_at": now}
                _agents[agent_id] = updated
                changed.append(dict(updated))
    return changed


def sweep_idle_nonresident() -> list[dict]:
    """Remove non-resident agents that have been idle for IDLE_REMOVE_THRESHOLD.
    Returns list of removed agents (for SSE broadcast)."""
    now = time.time()
    to_remove = []
    with _lock:
        for agent_id, agent in _agents.items():
            if agent.get("resident"):
                continue
            if agent.get("state") != "idle":
                continue
            age = now - agent.get("updated_at", 0)
            if age > IDLE_REMOVE_THRESHOLD:
                to_remove.append(agent_id)
        removed = []
        for agent_id in to_remove:
            agent = _agents.pop(agent_id, None)
            if agent:
                removed.append(dict(agent))
    return removed


def register_subagent(subagent_name: str, agent_id: str) -> None:
    """Track subagent instance name → resolved agent_id for SubagentStop lookup."""
    with _lock:
        _subagent_map[subagent_name] = agent_id


def resolve_subagent(subagent_name: str) -> str:
    """Pop and return the agent_id for a subagent name, or return the name as fallback."""
    with _lock:
        return _subagent_map.pop(subagent_name, subagent_name)


SUBAGENT_STALE_THRESHOLD = 600  # 10 min — orphaned subagent entries removed


def sweep_stale_subagents() -> int:
    """Remove subagent map entries whose agent_id no longer exists in _agents.

    Prevents unbounded growth when SubagentStop events are missed.
    Returns the number of entries removed.
    """
    with _lock:
        orphaned = [name for name, aid in _subagent_map.items() if aid not in _agents]
        for name in orphaned:
            del _subagent_map[name]
        return len(orphaned)


def append_hook_log(entry: dict) -> None:
    entry.setdefault("timestamp", time.time())
    with _lock:
        _hook_log.append(entry)


# ---------------------------------------------------------------------------
# Instance slot tracking
# ---------------------------------------------------------------------------

def get_instances() -> dict:
    """Return a copy of all tracked instances (thread-safe)."""
    with _lock:
        return {k: dict(v) for k, v in _instances.items()}


def track_instance(session_id: str, cwd: str = "", slot_count: int = 12) -> dict | None:
    """Track a Claude Code session, assigning it a server-room slot.

    If the session already exists, update last_event and cwd.
    If new, find the first free slot index (0..slot_count-1).
    Returns the instance dict, or None if no free slots available.
    """
    with _lock:
        if session_id in _instances:
            _instances[session_id]["last_event"] = time.time()
            if cwd:
                _instances[session_id]["cwd"] = cwd
            return dict(_instances[session_id])

        # Find first free slot
        for idx in range(slot_count):
            if idx not in _slot_assignments:
                instance = {
                    "session_id": session_id,
                    "slot_index": idx,
                    "cwd": cwd,
                    "last_event": time.time(),
                    "alert_type": None,
                    "alert_message": None,
                    "alert_at": None,
                }
                _instances[session_id] = instance
                _slot_assignments[idx] = session_id
                return dict(instance)

        return None


def set_instance_alert(session_id: str, alert_type: str, message: str) -> dict | None:
    """Set an alert on an existing instance. Returns updated dict or None."""
    with _lock:
        instance = _instances.get(session_id)
        if instance is None:
            return None
        instance["alert_type"] = alert_type
        instance["alert_message"] = message
        instance["alert_at"] = time.time()
        instance["last_event"] = time.time()
        return dict(instance)


def clear_instance_alert(session_id: str) -> dict | None:
    """Clear alert fields on an instance.

    Returns the instance dict only if there WAS an alert (so caller
    knows whether to broadcast). Returns None otherwise.
    """
    with _lock:
        instance = _instances.get(session_id)
        if instance is None:
            return None
        if instance["alert_type"] is None:
            return None
        instance["alert_type"] = None
        instance["alert_message"] = None
        instance["alert_at"] = None
        instance["last_event"] = time.time()
        return dict(instance)


def count_pending_alerts() -> int:
    """Return the number of instances with an active alert."""
    with _lock:
        return sum(1 for inst in _instances.values() if inst.get("alert_type") is not None)


def clear_idle_alerts() -> list[dict]:
    """Clear all idle_prompt alerts (user has seen them).

    Returns list of cleared instance dicts (for SSE broadcast).
    """
    cleared = []
    with _lock:
        for _sid, inst in _instances.items():
            if inst.get("alert_type") == "idle_prompt":
                inst["alert_type"] = None
                inst["alert_message"] = None
                inst["alert_at"] = None
                cleared.append(dict(inst))
    return cleared


def sweep_stale_instances() -> list[str]:
    """Remove instances whose last_event exceeds INSTANCE_SLOT_TIMEOUT.

    Cleans up both _instances and _slot_assignments.
    Returns list of removed session_ids.
    """
    now = time.time()
    removed = []
    with _lock:
        stale_ids = [
            sid for sid, inst in _instances.items()
            if now - inst.get("last_event", 0) > INSTANCE_SLOT_TIMEOUT
        ]
        for sid in stale_ids:
            inst = _instances.pop(sid)
            _slot_assignments.pop(inst["slot_index"], None)
            removed.append(sid)
    return removed
