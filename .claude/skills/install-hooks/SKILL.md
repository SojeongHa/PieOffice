---
name: install-hooks
description: Install Pie Office hooks into Claude Code and/or Antigravity CLI settings. Safely merges with existing hooks without overwriting. Triggers on "/install-hooks", "install hooks", "connect pie office", "setup hooks".
---

# Install Pie Office Hooks

Safely install Pie Office hooks into Claude Code and/or Antigravity CLI (`agy`) configuration, merging with any existing hook configuration.

## Process

### Step 1: Detect hook script path

Resolve the absolute path to `hook/pie-office-hook.py` relative to the project root. Store it as `HOOK_SCRIPT`.

### Step 2: Ask target CLI and scope

Ask the user:

1. **Target CLI**:
   - Claude Code
   - Antigravity CLI (`agy`)
   - Both (recommended)
2. **Scope**:
   - Global (applies to all projects)
   - Project-only (applies to this repository)

---

### Step 3A: Antigravity CLI (`agy`) Configuration

Target files:
- **Global**: `~/.gemini/config/hooks.json`
- **Project**: `.agents/hooks.json`

Read the target file. If it doesn't exist, start with `{}`.

#### Hook structure for Antigravity:
```json
{
  "pie-office": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 <HOOK_SCRIPT> --event PreToolUse"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 <HOOK_SCRIPT> --event PostToolUse"
          }
        ]
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "python3 <HOOK_SCRIPT> --event Stop"
      }
    ]
  }
}
```

#### Antigravity Merge rules:
- Top-level key `"pie-office"` is used to namespace the hook.
- If `"pie-office"` key already exists, merge the events (`PreToolUse`, `PostToolUse`, `Stop`).
- If other top-level keys exist in `hooks.json`, preserve them untouched.
- Write back with 2-space JSON formatting.

---

### Step 3B: Claude Code Configuration

Target files:
- **Global**: `~/.claude/settings.json`
- **Project**: `.claude/settings.json`

Read the target file. If it doesn't exist, start with `{}`.

#### Required Claude Code hook events:
Command for all events: `python3 <HOOK_SCRIPT>`

| Event | Matcher |
|-------|---------|
| PreToolUse | `*` |
| PostToolUse | `*` |
| Stop | `*` |
| SubagentStart | `*` |
| SubagentStop | `*` |
| Notification | `*` |
| TaskCompleted | `*` |

#### Claude Code Merge rules:
- If the settings file has no `hooks` key, create it.
- For each event above, check if the event key already exists in `hooks`.
  - If the event key exists, check if a hook entry with the same `command` already exists. If yes, skip (already installed). If no, **append** the new hook entry to the existing array.
  - If the event key does not exist, create it with the new hook entry.
- **NEVER overwrite or remove existing hook entries.** Only append.
- Preserve all other keys in the settings file (env, permissions, plugins, etc.).

---

### Step 4: Write and confirm

Write the merged settings back to the file(s) with 2-space JSON indentation.

Show the user a summary:

```
Pie Office hooks installed:
  [Antigravity CLI]
    - PreToolUse ✓
    - PostToolUse ✓
    - Stop ✓
    Target: <path to Antigravity hooks.json>

  [Claude Code]
    - PreToolUse ✓
    - PostToolUse ✓
    - Stop ✓
    - SubagentStart ✓
    - SubagentStop ✓
    - Notification ✓
    - TaskCompleted ✓
    Target: <path to Claude settings.json>

Restart your CLI session for hooks to take effect.
```

If any hooks were already present, note them as "already installed (skipped)".

Then suggest:
```
Run /distribute-character to assign characters to your agents.
Settings are saved to config.local.json (gitignored, personal to you).
```

---

### Step 5: Uninstall option

If the user says "uninstall" or "remove hooks":
- For **Antigravity**: Remove the `"pie-office"` key from `hooks.json`. If `hooks.json` is now empty, leave `{}`.
- For **Claude Code**:
  - Remove only the hook entries whose command contains `pie-office-hook.py`.
  - If an event's hook array becomes empty after removal, remove the event key entirely.
  - If `hooks` becomes empty, remove the `hooks` key.
  - Preserve everything else.
