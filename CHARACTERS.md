# How to Generate Custom Characters

Turn your Pie Office into a Pokemon gym, a fantasy guild, or anything you can imagine.

## Setup

1. `pip install google-genai pillow python-dotenv`
2. Add `GEMINI_API_KEY=your_key` to `.env` (get one at https://aistudio.google.com/apikey)

## Generate with Claude Code

Run Claude Code in this project and type:

```
Use the add-character skill to generate "<key>:<description>" and install it as <sprite>.png in theme/<theme>/characters/
```

### Examples

**Pikachu** (Leader):

```
Use the add-character skill to generate "pikachu:Pikachu, yellow electric mouse Pokemon, red circle cheeks, pointed ears with black tips, lightning bolt-shaped tail, bright brown eyes" and install it as leader.png in theme/pokemon/characters/
```

**Charmander** (Frontend):

```
Use the add-character skill to generate "charmander:Charmander, orange fire lizard Pokemon, cream belly, big blue eyes, flame burning on tail tip, short arms" --chroma blue and install it as coder_a.png in theme/pokemon/characters/
```

**Bulbasaur** (Backend):

```
Use the add-character skill to generate "bulbasaur:Bulbasaur, teal-green dinosaur Pokemon, dark green bulb on back, red eyes, wide mouth, dark green spots on body" --chroma blue and install it as coder_b.png in theme/pokemon/characters/
```

**Squirtle** (Explorer):

```
Use the add-character skill to generate "squirtle:Squirtle, light blue turtle Pokemon, brown shell on back, curled tail, big red-brown eyes, round head" and install it as explorer.png in theme/pokemon/characters/
```

> **Tip:** Use `--chroma blue` for green/teal characters (Bulbasaur, Charmander) to avoid chroma key conflicts with the default green background removal.

## Using the Script Directly

```bash
cd public/script

python3 generate_characters.py \
  --key "pikachu" \
  --description "Pikachu, yellow electric mouse Pokemon, red cheeks" \
  --output theme/pokemon/characters/
```

### Flags

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--move` | `bipedal`, `float`, `quadruped` | `bipedal` | Movement style |
| `--chroma` | `green`, `blue`, `red` | `green` | Chroma key background color |
| `--reuse-base` | (flag) | off | Reuse existing base frame instead of regenerating |

## Apply Your Theme

Create `config.local.json` in the project root:

```json
{
  "character_theme": "pokemon"
}
```

Restart the server. Only character sprites are overridden — the office layout stays the same.

## Agent-to-Sprite Mapping

| Agent ID | Role | Sprite File |
|----------|------|-------------|
| main | Leader | leader.png |
| frontend | Frontend | coder_a.png |
| backend | Backend | coder_b.png |
| general-purpose | Assistant | coder_c.png |
| datapipeline | DataPipeline | coder_e.png |
| Explore | Explorer | explorer.png |
| Plan | Planner | planner.png |
| coder_d | Misc | coder_d.png |
