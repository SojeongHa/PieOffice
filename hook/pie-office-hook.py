#!/usr/bin/env python3
"""
Claude Code hook for Pie Office.
Receives tool events on stdin and forwards them to the local server.
"""
import os
import sys
import json
import urllib.request
import urllib.error

SERVER_URL = os.environ.get("PIE_OFFICE_URL", "http://localhost:10317/hook")
TIMEOUT = 3
DEBUG = os.environ.get("PIE_OFFICE_DEBUG", "").lower() in ("1", "true")

# Project root: hook/ lives one level below
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def debug(msg):
    if DEBUG:
        print(f"[pie-office-hook] {msg}", file=sys.stderr)


def _load_local_config():
    """Load config.local.json from project root (gitignored, personal overrides)."""
    path = os.path.join(_PROJECT_ROOT, "config.local.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# Map Claude Code agent types to display names (base defaults — official Claude agents)
_DEFAULT_AGENT_TYPE_MAP = {
    "general-purpose": "Leader",
    "Explore": "Explorer",
    "Plan": "Planner",
    "superpowers": "Superpowers",
    "code-review": "Reviewer",
    "code-simplifier": "Simplifier",
    "everything-claude-code": "ECC",
}

# Alias agent types to resident agent IDs (base defaults)
_DEFAULT_AGENT_ALIAS_MAP = {
    "code-review": "superpowers",
    "code-simplifier": "everything-claude-code",
}

# Merge with config.local.json overrides
_local_cfg = _load_local_config()
AGENT_TYPE_MAP = {**_DEFAULT_AGENT_TYPE_MAP, **_local_cfg.get("agent_type_map", {})}
AGENT_ALIAS_MAP = {**_DEFAULT_AGENT_ALIAS_MAP, **_local_cfg.get("agent_alias_map", {})}

# Map tool usage to agent states
TOOL_STATE_MAP = {
    "Read": "reading",
    "Grep": "researching",
    "Glob": "researching",
    "Write": "writing",
    "Edit": "writing",
    "Bash": "executing",
    "WebSearch": "researching",
    "WebFetch": "researching",
    "Agent": "executing",
    "TaskCreate": "writing",
    "TaskUpdate": "writing",
    "NotebookEdit": "writing",
    "Skill": "executing",
    "AskUserQuestion": "reporting",
    "SendMessage": "reporting",
}

# Tools that fire too frequently — skip in PostToolUse handler
IGNORE_TOOLS = {"ToolSearch", "EnterPlanMode", "ExitPlanMode", "ListMcpResourcesTool"}

# Substrings that identify a search-oriented MCP tool — route to Explorer
_SEARCH_MCP_KEYWORDS = ("search", "query", "fetch", "read", "resolve", "get", "list", "details")

# Tool → agent routing: {tool_name: state}
_EXPLORER_TOOLS = {
    "Read": "reading",
    "Grep": "researching",
    "Glob": "researching",
    "Bash": "executing",
    "WebSearch": "researching",
    "WebFetch": "researching",
}

_ASSISTANT_TOOLS = {
    "Write": "writing",
    "Edit": "writing",
    "NotebookEdit": "writing",
}

_PLANNER_TOOLS = {
    "Agent": "executing",
    "TaskCreate": "writing",
    "TaskUpdate": "writing",
}


def is_search_mcp_tool(tool_name: str) -> bool:
    """Return True if an mcp__* tool name looks search/read-oriented."""
    lowered = tool_name.lower()
    return any(kw in lowered for kw in _SEARCH_MCP_KEYWORDS)


def extract_detail(tool_name, tool_input):
    """Extract human-readable detail from tool_input based on tool_name."""
    if tool_name in ("Read", "Write", "Edit"):
        path = tool_input.get("file_path", "")
        return path.split("/")[-1] if path else ""
    elif tool_name == "Bash":
        return tool_input.get("description", tool_input.get("command", "")[:60])
    elif tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        return f"searching: {pattern[:40]}" if pattern else ""
    elif tool_name == "Glob":
        pattern = tool_input.get("pattern", "")
        return f"finding: {pattern[:40]}" if pattern else ""
    elif tool_name == "Agent":
        return tool_input.get("description", "")[:60]
    elif tool_name == "Skill":
        return f"skill: {tool_input.get('skill_name', 'unknown')}"
    return ""


def send_to_server(payload):
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            SERVER_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        debug(f"POST {SERVER_URL} <- {payload.get('event', '?')}")
        urllib.request.urlopen(req, timeout=TIMEOUT)
    except urllib.error.URLError as e:
        debug(f"URLError sending to server: {e}")
    except OSError as e:
        debug(f"OSError sending to server: {e}")


def handle_event(event_data):
    hook_event = event_data.get("hook_event_name", "") or event_data.get("hook_event", "")
    tool_name = event_data.get("tool_name", "")
    tool_input = event_data.get("tool_input", {})
    session_id = event_data.get("session_id", "")
    cwd = event_data.get("cwd", "")

    debug(f"event={hook_event} tool={tool_name}")

    if hook_event == "PreToolUse":
        if tool_name in IGNORE_TOOLS:
            return

        detail = extract_detail(tool_name, tool_input) or tool_name

        if tool_name in _EXPLORER_TOOLS:
            send_to_server({
                "event": "agent_update",
                "agent_id": "Explore",
                "agent_name": "Explorer",
                "state": _EXPLORER_TOOLS[tool_name],
                "detail": detail,
                "session_id": session_id,
                "cwd": cwd,
            })
        elif tool_name in _ASSISTANT_TOOLS:
            send_to_server({
                "event": "agent_update",
                "agent_id": "general-purpose",
                "agent_name": "Assistant",
                "state": _ASSISTANT_TOOLS[tool_name],
                "detail": detail,
                "session_id": session_id,
                "cwd": cwd,
            })
        elif tool_name in _PLANNER_TOOLS:
            send_to_server({
                "event": "agent_update",
                "agent_id": "Plan",
                "agent_name": "Planner",
                "state": _PLANNER_TOOLS[tool_name],
                "detail": detail,
                "session_id": session_id,
                "cwd": cwd,
            })
        elif tool_name.startswith("mcp__"):
            short_name = tool_name.split("__")[-1]
            if is_search_mcp_tool(tool_name):
                send_to_server({
                    "event": "agent_update",
                    "agent_id": "Explore",
                    "agent_name": "Explorer",
                    "state": "researching",
                    "detail": short_name[:40],
                    "session_id": session_id,
                    "cwd": cwd,
                })
            else:
                send_to_server({
                    "event": "agent_update",
                    "agent_id": "main",
                    "agent_name": "Leader",
                    "state": "debugging",
                    "detail": short_name[:40],
                    "session_id": session_id,
                    "cwd": cwd,
                })
        else:
            # Permission check — leader stays in place, persistent bubble
            send_to_server({
                "event": "agent_update",
                "agent_id": "main",
                "agent_name": "Leader",
                "state": "permission",
                "detail": f"permission: {detail}"[:60],
                "session_id": session_id,
                "cwd": cwd,
            })

    elif hook_event == "SubagentStart":
        agent_type = tool_input.get("subagent_type", "general-purpose")
        agent_name = tool_input.get("name", agent_type)
        display_name = AGENT_TYPE_MAP.get(agent_type, agent_name)
        detail = tool_input.get("description", tool_input.get("prompt", "")[:80])

        # If agent_type matches a resident agent, update that resident
        # instead of creating a duplicate. Aliases share a resident character.
        agent_id = AGENT_ALIAS_MAP.get(agent_type, agent_type) if agent_type in AGENT_TYPE_MAP else agent_name

        send_to_server({
            "event": "SubagentStart",
            "agent_id": agent_id,
            "agent_type": agent_type,
            "agent_name": display_name,
            "subagent_name": agent_name,
            "detail": detail,
            "state": "executing",
            "session_id": session_id,
            "cwd": cwd,
        })

    elif hook_event == "SubagentStop":
        agent_name = event_data.get("agent_name", "unknown")
        # Server resolves subagent_name → agent_id via register_subagent mapping
        send_to_server({
            "event": "SubagentStop",
            "agent_id": agent_name,
            "agent_name": agent_name,
            "session_id": session_id,
            "cwd": cwd,
        })

    elif hook_event == "PostToolUse":
        if tool_name in IGNORE_TOOLS:
            debug(f"ignoring tool: {tool_name}")
            return

        # Handle MCP tools: search MCP updates Explorer, others are ignored
        if tool_name.startswith("mcp__"):
            if is_search_mcp_tool(tool_name):
                # Search MCP completed — Explorer returns to idle
                send_to_server({
                    "event": "agent_update",
                    "agent_id": "Explore",
                    "agent_name": "Explorer",
                    "state": "idle",
                    "detail": "",
                    "session_id": session_id,
                    "cwd": cwd,
                })
            else:
                debug(f"ignoring non-search mcp tool: {tool_name}")
            return

        if tool_name == "SendMessage":
            msg_type = tool_input.get("type", "message")
            if msg_type == "shutdown_request":
                send_to_server({
                    "event": "shutdown",
                    "agent_id": tool_input.get("recipient", "unknown"),
                    "session_id": session_id,
                    "cwd": cwd,
                })
            elif msg_type in ("message", "broadcast"):
                sender = session_id
                receiver = tool_input.get("recipient", "all")
                message = tool_input.get("summary", tool_input.get("content", "")[:60])
                send_to_server({
                    "event": "agent_chat",
                    "agent_id": sender,
                    "agent_name": sender,
                    "from": sender,
                    "to": receiver,
                    "sender": sender,
                    "receiver": receiver,
                    "message": message,
                    "session_id": session_id,
                    "cwd": cwd,
                })
                # Gather: sender walks to receiver
                if receiver and receiver != "all":
                    send_to_server({
                        "event": "agent_gather",
                        "source_id": sender,
                        "target_id": receiver,
                        "message": message,
                        "session_id": session_id,
                        "cwd": cwd,
                    })

        elif tool_name == "TeamDelete":
            send_to_server({"event": "team_delete", "session_id": session_id, "cwd": cwd})

        elif tool_name in _EXPLORER_TOOLS:
            # Explorer task finished — return to idle
            send_to_server({
                "event": "agent_update",
                "agent_id": "Explore",
                "agent_name": "Explorer",
                "state": "idle",
                "detail": "",
                "session_id": session_id,
                "cwd": cwd,
            })

        elif tool_name in _ASSISTANT_TOOLS:
            # Assistant task finished — return to idle
            send_to_server({
                "event": "agent_update",
                "agent_id": "general-purpose",
                "agent_name": "Assistant",
                "state": "idle",
                "detail": "",
                "session_id": session_id,
                "cwd": cwd,
            })

        elif tool_name in _PLANNER_TOOLS:
            # Planner task finished — return to idle
            detail = extract_detail(tool_name, tool_input)
            send_to_server({
                "event": "agent_update",
                "agent_id": "Plan",
                "agent_name": "Planner",
                "state": "idle",
                "detail": "",
                "session_id": session_id,
                "cwd": cwd,
            })

        elif tool_name == "AskUserQuestion":
            question = tool_input.get("question", tool_input.get("text", ""))[:80]
            detail = question or "waiting for answer..."
            send_to_server({
                "event": "agent_update",
                "agent_id": "main",
                "agent_name": "Leader",
                "state": "reporting",
                "detail": detail,
                "session_id": session_id,
                "cwd": cwd,
            })
            send_to_server({
                "event": "agent_chat",
                "agent_id": "main",
                "agent_name": "Leader",
                "message": detail,
                "session_id": session_id,
                "cwd": cwd,
            })

        else:
            # Remaining tools (Skill, etc.) — Leader handles
            state = TOOL_STATE_MAP.get(tool_name, "executing")
            detail = extract_detail(tool_name, tool_input)

            send_to_server({
                "event": "agent_update",
                "agent_id": "main",
                "agent_name": "Leader",
                "state": state,
                "detail": detail,
                "session_id": session_id,
                "cwd": cwd,
            })

    elif hook_event == "TeammateIdle":
        agent_name = event_data.get("agent_name", "unknown")
        send_to_server({
            "event": "agent_update",
            "agent_id": agent_name,
            "state": "idle",
            "detail": "",
            "session_id": session_id,
            "cwd": cwd,
        })

    elif hook_event == "Notification":
        message = event_data.get("message", "")
        notification_type = event_data.get("notification_type", "")
        debug(f"notification: type={notification_type} msg={message}")

        if notification_type in ("permission_prompt", "idle_prompt"):
            send_to_server({
                "event": "instance_alert",
                "session_id": session_id,
                "cwd": cwd,
                "notification_type": notification_type,
                "message": message,
                "title": event_data.get("title", ""),
            })
        if "compact" in message.lower():
            send_to_server({
                "event": "agent_update",
                "agent_id": "Plan",
                "agent_name": "Planner",
                "state": "writing",
                "detail": "compacting conversation",
                "session_id": session_id,
                "cwd": cwd,
            })

    elif hook_event == "Stop":
        # Claude finished its turn — clear any pending alert for this session
        send_to_server({
            "event": "agent_update",
            "agent_id": "main",
            "agent_name": "Leader",
            "state": "idle",
            "detail": "",
            "session_id": session_id,
            "cwd": cwd,
        })

    elif hook_event == "TaskCompleted":
        send_to_server({
            "event": "agent_update",
            "agent_id": "main",
            "agent_name": "Leader",
            "state": "idle",
            "detail": "Task completed",
            "session_id": session_id,
            "cwd": cwd,
        })


if __name__ == "__main__":
    try:
        raw = sys.stdin.read()
        if raw.strip():
            event_data = json.loads(raw)
            handle_event(event_data)
    except json.JSONDecodeError as e:
        print(f"[pie-office-hook] JSON parse error: {e}", file=sys.stderr)
    except KeyError as e:
        print(f"[pie-office-hook] Missing key: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[pie-office-hook] Unexpected error: {e}", file=sys.stderr)
