#!/bin/bash
# Install Pie Office hooks into Claude Code settings
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK_CMD="python3 ${SCRIPT_DIR}/pie-office-hook.py"
# Note: actual hook script is pie-office-hook.py in this directory

echo "Pie Office Hook Installer"
echo "============================"
echo ""
echo "Add the following to your ~/.claude/settings.json (or .claude/settings.json):"
echo ""
cat << EOF
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Agent|SendMessage|TeamDelete|Read|Write|Edit|Bash|Grep|Glob|WebSearch|WebFetch",
        "hooks": [
          { "type": "command", "command": "${HOOK_CMD}" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Agent|SendMessage|TeamDelete|Read|Write|Edit|Bash|Grep|Glob|WebSearch|WebFetch",
        "hooks": [
          { "type": "command", "command": "${HOOK_CMD}" }
        ]
      }
    ],
    "SubagentStart": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "${HOOK_CMD}" }
        ]
      }
    ],
    "SubagentStop": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "${HOOK_CMD}" }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "${HOOK_CMD}" }
        ]
      }
    ],
    "TaskCompleted": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "${HOOK_CMD}" }
        ]
      }
    ]
  }
}
EOF
echo ""
echo "Done! Restart Claude Code for hooks to take effect."
