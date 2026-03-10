---
name: install-hooks
description: Install Pie Office hooks into Claude Code settings. Safely merges with existing hooks without overwriting. Triggers on "/install-hooks", "install hooks", "connect pie office", "setup hooks".
---

# Install Pie Office Hooks

Safely install Pie Office hooks into Claude Code settings, merging with any existing hook configuration.

## Process

### Step 1: Detect hook script path

Resolve the absolute path to `hook/pie-office-hook.py` relative to the project root. Store it as `HOOK_SCRIPT`.

### Step 2: Ask scope

Ask the user:

> Install hooks globally (`~/.claude/settings.json`) or for this project only (`.claude/settings.json`)?

### Step 3: Read existing settings

Read the target settings file. If it doesn't exist, start with `{}`.

### Step 4: Merge hooks

The following hooks need to be registered. The command for all hooks is:

```
python3 <HOOK_SCRIPT>
```

Required hook events and matchers:

| Event | Matcher |
|-------|---------|
| PreToolUse | `*` |
| PostToolUse | `*` |
| SubagentStart | `*` |
| SubagentStop | `*` |
| Notification | `*` |
| TaskCompleted | `*` |

**Merge rules:**
- If the settings file has no `hooks` key, create it.
- For each event above, check if the event key already exists in `hooks`.
  - If the event key exists, check if a hook entry with the same `command` already exists. If yes, skip (already installed). If no, **append** the new hook entry to the existing array.
  - If the event key does not exist, create it with the new hook entry.
- **NEVER overwrite or remove existing hook entries.** Only append.
- Preserve all other keys in the settings file (env, plugins, etc.).

### Step 5: Write and confirm

Write the merged settings back to the file with 2-space JSON indentation.

Show the user a summary:

```
Pie Office hooks installed:
  - PreToolUse ✓
  - PostToolUse ✓
  - SubagentStart ✓
  - SubagentStop ✓
  - Notification ✓
  - TaskCompleted ✓

Target: <path to settings file>
Restart Claude Code for hooks to take effect.
```

If any hooks were already present, note them as "already installed (skipped)".

Then suggest:

```
Run /distribute-character to assign characters to your agents.
Settings are saved to config.local.json (gitignored, personal to you).
```

### Step 6: Uninstall option

If the user says "uninstall" or "remove hooks", reverse the process:
- Remove only the hook entries whose command contains `pie-office-hook.py`.
- If an event's hook array becomes empty after removal, remove the event key entirely.
- If `hooks` becomes empty, remove the `hooks` key.
- Preserve everything else.
