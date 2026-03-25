---
name: distribute-character
description: Use when the user wants to reassign pie-office characters to their agents/subagents based on actual usage patterns. Triggers on "/distribute-character", "distribute characters", "reassign characters", "캐릭터 분배".
---

# Distribute Characters to Agents

Analyze agent/subagent usage and redistribute pie-office characters for optimal coverage.

## Distribution Principles

**Principle 1 — Respect custom names**: If the user renamed agents in `agent_map` (not default `frontend`/`backend`/`datapipeline`), those custom mappings take priority.

**Principle 2 — Balanced spread**: Recommend distribution so all characters get meaningful screen time. Avoid leaving characters permanently idle.

## Fixed Characters (DO NOT redistribute)

These 4 characters are hardwired to tool routing in `hook/pie-office-hook.py`:

| Character | Agent ID | Role | Tools |
|-----------|----------|------|-------|
| leader | main | Leader | Skill, MCP, AskUser, permission |
| explorer | Explore | Explorer | Read, Grep, Glob, Bash, WebSearch, WebFetch |
| coder_c | general-purpose | Assistant | Write, Edit, NotebookEdit |
| planner | Plan | Planner | Agent, TaskCreate, TaskUpdate |

## Redistributable Characters (4 available)

| Sprite | Default Agent | Default Name |
|--------|---------------|--------------|
| coder_a | frontend | Frontend |
| coder_b | backend | Backend |
| coder_d | coder_d | Misc |
| coder_e | datapipeline | DataPipeline |

## Process

### Step 1: Read Current Config

Read these files using the **Read tool** (not Grep/Glob — `config.local.json` is gitignored and invisible to search tools):

```
theme/default/config.json   → agent_map (base defaults)
config.local.json           → agent_map, agent_type_map, agent_alias_map overrides (may not exist yet)
config.local.json.sample    → reference for available options
hook/pie-office-hook.py     → _DEFAULT_AGENT_TYPE_MAP (base defaults, DO NOT modify)
```

Merge base + local to determine the current effective agent_map. Identify any custom overrides the user has already set.

### Step 2: Scan Agent/Subagent Usage

Collect available agent types from these sources **in priority order**:

**Priority 1 (MANDATORY) — Agent tool description in current session:**
This is the definitive source. Extract ALL `subagent_type` values from the Agent tool's description in the system prompt. Parse the full list — do NOT rely on memory or common examples.

**Priority 2 — Skill definitions that spawn agents:**
```
~/.claude/skills/*/SKILL.md
.claude/skills/*/SKILL.md
```
Search for `subagent_type`, `Agent tool`, or agent-spawning patterns.

**Priority 3 — Project CLAUDE.md files:**
```
~/Documents/workspace/*/CLAUDE.md
~/.claude/rules/**/*.md
```
Scan for subagent type references and agent descriptions.

**Priority 4 — Custom agents:**
```
~/.claude/agents/
```
Check for user-defined agent configurations.

#### Handling colon-namespaced types

Types like `feature-dev:code-reviewer` or `pr-review-toolkit:silent-failure-hunter` use `prefix:subtype` format. Rules:

- The **prefix** (e.g., `feature-dev`) is the top-level agent group.
- For `AGENT_TYPE_MAP` and `agent_map`, use the **prefix only** as the key (e.g., `feature-dev`, not `feature-dev:code-reviewer`), because the hook receives the prefix as `agent_type`.
- If multiple subtypes share a prefix, they all map to the same character — this is expected.
- Count ALL subtypes under a prefix toward that prefix's usage score.

### Step 3: Rank by Usage

Create a usage ranking of non-fixed agent types with **concrete scoring**:

| Metric | How to Measure | Weight |
|--------|---------------|--------|
| Registered in Agent tool | Listed as `subagent_type` in current session | +3 |
| Referenced in skills | Mentioned in any SKILL.md | +2 per skill |
| Referenced in CLAUDE.md | Mentioned in any project CLAUDE.md | +1 per project |
| Has subtypes | Colon-namespaced variants exist | +1 per subtype |
| Custom agent defined | Exists in `~/.claude/agents/` | +1 |

**Exclude** types that are already assigned to fixed characters (`general-purpose`, `Explore`, `Plan`).

Present as a scored table:

```
| Rank | Agent Type     | Score | Sources                          |
|------|---------------|-------|----------------------------------|
| 1    | review-critic | 6     | Agent tool, 2 skills, CLAUDE.md  |
| 2    | feature-dev   | 5     | Agent tool, 3 subtypes           |
| ...  | ...           | ...   | ...                              |
```

### Step 4: Propose Distribution

Generate a proposal following these rules:

1. **Keep custom names**: If user already customized an agent_map entry, keep it.
2. **Map top-scored agents**: Assign redistributable characters to the highest-scored agent types.
3. **Show before/after with reasoning for EVERY character** — including those kept unchanged:

```
Before → After:
  coder_a: frontend (Frontend) → code-reviewer (Reviewer)
    Reason: code-reviewer scored 6, frontend scored 2
  coder_b: backend (Backend) → backend (Backend) ← KEPT
    Reason: backend scored 5, already top-4; user customized displayName
  coder_d: coder_d (Misc) → review-critic (Critic)
    Reason: review-critic scored 6, coder_d was unmapped placeholder
  coder_e: datapipeline (DataPipeline) → feature-dev (FeatureDev)
    Reason: feature-dev scored 5 (3 subtypes), datapipeline scored 2
```

4. **Every row MUST have a Reason** — "no change needed" is NOT acceptable without a score comparison.

### Step 5: Confirm & Apply

Ask the user to confirm. On approval, update **only `config.local.json`** (gitignored, personal to each user):

- **`agent_map`** — sprite/position overrides for new agent keys. Set `"resident": false` on base keys being replaced to hide them.
- **`agent_type_map`** — agent type → display name mappings. Merged on top of hook's `_DEFAULT_AGENT_TYPE_MAP` at runtime.
- **`agent_alias_map`** — agent type aliases (multiple types share one character). Merged on top of hook's `_DEFAULT_AGENT_ALIAS_MAP`.

**Important**: Do NOT modify `hook/pie-office-hook.py` or `theme/default/config.json`. These are git-shared files. All customizations go into `config.local.json`. The hook reads `agent_type_map` and `agent_alias_map` from this file at startup and merges with its built-in defaults.

When redistributing a character to a NEW agent key (e.g., `coder_d` → `my-agent`), include all fields since the key has no base to merge from. Also set the OLD key to `"resident": false` to prevent duplicate sprites:

```json
{
  "agent_type_map": {
    "my-agent": "MyAgent"
  },
  "agent_map": {
    "my-agent": { "sprite": "coder_d", "displayName": "MyAgent", "resident": true, "idlePosition": { "x": 16, "y": 17 } },
    "review-critic": { "resident": false }
  }
}
```

Show the exact changes before applying.

### Step 6: Verify

After applying:

```bash
python -c "
import json, os
base = json.load(open('theme/default/config.json')).get('agent_map', {})
local_cfg = {}
if os.path.exists('config.local.json'):
    local_cfg = json.load(open('config.local.json')).get('agent_map', {})
merged = {**base}
for k, v in local_cfg.items():
    merged[k] = {**merged.get(k, {}), **v}
print(json.dumps(merged, indent=2))
"
```

Confirm:
- All agent IDs are unique
- No resident character sprite is assigned twice (check `resident: true` entries only)
- Every new agent type has a corresponding `agent_type_map` entry in `config.local.json`
- `config.local.json` only contains overrides, not a full copy of the base config
- Old base keys being replaced are set to `"resident": false`

### Step 7: Done

No commit needed — `config.local.json` is gitignored and personal. Just remind the user to restart the pie-office server.

## Onboarding: Unmapped Agent Types in config.json

When a new user clones the repo, `config.json` ships with agent types they may not have (e.g., `review-critic`, `review-advocate`, `review-neutral`, `feature-dev`). During Step 3, if a config.json agent type scores **0** (not found in Agent tool, skills, CLAUDE.md, or custom agents), handle it as follows:

### 1. Find a similar replacement

Search the user's available agent types for a semantic match:

| Shipped Type | Similar Candidates (check in order) |
|-------------|--------------------------------------|
| `review-critic` | `code-reviewer`, `superpowers:code-reviewer`, any agent with "review" in name |
| `review-advocate` | `code-reviewer`, `review-neutral`, any agent with "review" in name |
| `review-neutral` | `code-reviewer`, `review-advocate`, any agent with "review" in name |
| `feature-dev` | `frontend`, `backend`, `datapipeline`, any project-specific agent |

If a similar agent exists, propose remapping to it.

### 2. If no similar agent exists, recommend enabling plugins

Present the user with options:

```
The following agent types in config.json are not available in your environment:
  - review-critic (Critic, coder_d)
  - review-advocate (Advocate, coder_e)

Options:
  A) Remap to your existing agents (I'll suggest best matches)
  B) Enable the code-review plugin (provides review-critic, review-advocate, review-neutral)
  C) Reset to defaults (frontend/backend/datapipeline)
```

For option B, guide the user to enable the **code-review** plugin in Claude Code settings. This provides all three review agent types out of the box — no manual file creation needed.

### Recommended Agent Plugins

For the best Pie Office experience, recommend these Claude Code plugins that provide the review agent set and other useful agent types:

| Plugin | Agent Types Provided | Install |
|--------|---------------------|---------|
| **code-review** | `review-critic`, `review-advocate`, `review-neutral` | Built-in plugin, enable in settings |
| **superpowers** | `superpowers:code-reviewer`, `superpowers:brainstorming`, and more | Built-in plugin, enable in settings |
| **feature-dev** | `feature-dev:code-explorer`, `feature-dev:code-reviewer`, `feature-dev:code-architect` | Built-in plugin, enable in settings |

The **code-review** plugin is particularly recommended as it provides the 3-perspective review set (Critic, Advocate, Neutral) that maps perfectly to `coder_d`, `coder_e`, and `coder_a`.

### 3. Never leave dead mappings

If a config.json agent type has score 0 AND no similar replacement AND the user declines to create it, **remap to a real agent or reset to default**. Unmapped types cause characters to never activate via SubagentStart.

## Notes

- The `robot` sprite is the **fallback** for unmapped agents (random pastel tint). It should NOT be assigned in agent_map.
- `idlePosition` in agent_map determines where the character sits when idle — keep existing positions unless the user wants to move them.
- After redistribution, restart the pie-office server (`./dev.sh`) for changes to take effect.
- `config.local.json` is the single source for personal overrides (gitignored). The backend deep-merges its `agent_map` on top of `theme/default/config.json` at runtime. If `config.local.json` has no `agent_map`, the theme defaults are used as-is.
