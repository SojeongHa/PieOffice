---
name: add-character
description: Add a new character to Pie Office. Use when the user wants to create a new character sprite. Triggers on "/add-character", "add character", "new character".
---

# Add Character to Pie Office

Interactive workflow for adding a new character sprite to the project.

## Prerequisites

- `GEMINI_API_KEY` set in `.env` or environment variable
- Python dependencies: `pip install google-genai pillow python-dotenv`

## Process

### Step 1: Gather Character Info

Ask the user two questions (one at a time):

1. **Character name** (snake_case, e.g. `fox_b`, `owl_a`, `hamster`)
   - Must be unique — check `theme/default/characters/characters.json` for existing names
   - Must be snake_case, lowercase, no spaces

2. **Character concept** (free text description)
   - Example: "arctic fox, white fur, blue scarf, ice mage"
   - Example: "wise owl, brown feathers, tiny reading glasses, holds a book"
   - Should include: animal type, colors, accessories, personality items

### Step 2: Preview & Confirm

Show the user what will be generated:

```
Character: {name}
Concept: {concept}

Will generate:
  - 2-step pipeline: base frame → reference-guided strips
  - 3 walk strips (down, right, up) × 2 frames each
  - 1 working animation (2 frames, front-facing)
  - 1 happy animation (2 frames, front-facing)
  - idle extracted from walk frame 1
  - Final spritesheet: 512x512 PNG (8x8 grid of 64x64 frames)
  - Gemini API calls: ~6 (1 base + 3 walk + 1 working + 1 happy)
  - Post-processing: normalize_strips for consistent sizing
```

Ask for confirmation before proceeding.

### Step 3: Generate Sprites

Run the generation command:

```bash
cd /path/to/pie-office && python public/script/generate_characters.py --add "{name}:{concept}"
```

This outputs to `theme/default/characters/generated/{name}.png`.

The pipeline:
1. Generates a 128x128 base frame (front-facing, standing)
2. Uses the base frame as a reference image for all 5 strip generations
3. Each strip is 256x128 (2 frames at 128x128 each)
4. Chroma key removal at high resolution, then downscale to 128x64 (2×64x64 frames)
5. normalize_strips equalizes character size across all strips using frame 1 height
6. Assembles into 512x512 spritesheet

### Step 4: Review Generated Sprite

Read the generated spritesheet image file and show it to the user for visual review.

Ask: "Does this look good? If not, I can regenerate."

If the user wants to regenerate, run the command again.

### Step 5: Install Sprite

Once approved, copy the generated sprite to the characters directory:

```bash
cp theme/default/characters/generated/{name}.png theme/default/characters/{name}.png
```

### Step 6: Register in characters.json

Add the new character definition to `theme/default/characters/characters.json`.
Direction prompts should be SHORT — just the direction info, not repeating the description:

```json
"{name}": {
    "animal": "{animal type, capitalized}",
    "description": "{full concept with animal, colors, accessories}",
    "prompts": {
        "down": "facing front",
        "right": "facing right, side view, {tail/distinguishing feature}",
        "up": "facing away, back view, {tail/distinguishing feature}"
    }
}
```

### Step 7: Register in sprites.json

Add the new character to `theme/default/characters/sprites.json`.
All animations are 2-frame:

```json
"{name}": {
    "file": "{name}.png",
    "anims": {
        "idle-down":  { "start": 32, "end": 32, "frameRate": 1 },
        "walk-down":  { "start": 0,  "end": 1,  "frameRate": 8 },
        "idle-left":  { "start": 33, "end": 33, "frameRate": 1 },
        "walk-left":  { "start": 8,  "end": 9,  "frameRate": 8 },
        "idle-right": { "start": 34, "end": 34, "frameRate": 1 },
        "walk-right": { "start": 16, "end": 17, "frameRate": 8 },
        "idle-up":    { "start": 35, "end": 35, "frameRate": 1 },
        "walk-up":    { "start": 24, "end": 25, "frameRate": 8 },
        "working":    { "start": 40, "end": 41, "frameRate": 6 },
        "happy":      { "start": 48, "end": 49, "frameRate": 8 }
    }
}
```

### Step 8: Summary

Report what was created and remind the user:

> To use this character in-game, add an entry to `theme/default/config.json` under `agent_map`:
> ```json
> "your_agent_id": {
>     "sprite": "{name}",
>     "displayName": "Display Name",
>     "resident": true,
>     "idlePosition": { "x": 10, "y": 10 }
> }
> ```

## Troubleshooting

**Green fringing on edges**: The generator uses HSV-based chroma key removal with despill. If green edges persist, the tolerance can be adjusted in `generate_characters.py`'s `remove_chroma_key()` function.

**Size inconsistency between strips**: The normalize_strips post-processor uses frame 1 (standing pose) height to equalize all strips. If still off, regenerate — AI generation is non-deterministic.

**Multiple characters in one frame**: Shorten the prompt. Long prompts cause Gemini to generate multiple characters. The base_style.txt emphasizes "Only ONE character exists in the entire image, shown twice."

**Character generated as quadruped**: The base_style includes "bipedal on two short stubby legs like a human NOT on all fours" but some animals (especially dogs) may still appear 4-legged in side view.

**Character too fat/round**: Add "slim petite body NOT chubby" to the character description in `characters.json`.

## Notes

- Each generation uses ~6 Gemini API calls (1 base + 3 walk + 1 working + 1 happy)
- Generation is at 128x128 per frame, downscaled to 64x64 for quality
- 2-step pipeline: base frame generated first, then used as reference for all strips
- The robot character uses grayscale + tinting — new characters should use full color
- Does NOT auto-update config.json agent_map (mapping agents to sprites is separate)
- Chroma key removal uses HSV green_strength + despill (not simple RGB tolerance)
- normalize_strips uses frame 1 standing height, scales entire strip proportionally
