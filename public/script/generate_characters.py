#!/usr/bin/env python3
"""
Generate character sprites and fountain animation via Gemini API.

Uses Google Gemini image generation (gemini-3.1-flash-image-preview) to create
pixel art character spritesheets for Pie Office.

Characters: loaded from characters/characters.json
Each spritesheet: 512x512 (8 rows x 8 cols of 64x64).
  Row 0: walk-down   (2 frames)
  Row 1: walk-left   (2 frames, horizontal flip of right)
  Row 2: walk-right  (2 frames)
  Row 3: walk-up     (2 frames)
  Row 4: idle        (down, left, right, up — single frames)
  Row 5: working     (2 frames, front view)
  Row 6: happy       (2 frames, front view)
  Row 7: (reserved)

Fountain: 8-frame animation strip (768x96), 2 candidates generated.

Usage:
    python generate_characters.py --all            # Generate all characters
    python generate_characters.py -c coder_a       # Generate one character
    python generate_characters.py --animals         # Just the animal characters
    python generate_characters.py --robot           # Just the robot
    python generate_characters.py --fountain        # Generate fountain sprites
    python generate_characters.py --list            # List available characters
    python generate_characters.py --all --fountain  # Everything
    python generate_characters.py --add "fox_b:arctic fox, white fur, blue scarf"

Requirements:
    pip install google-genai pillow python-dotenv
"""

import argparse
import io
import json
import os
import sys
import time

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from PIL import Image
except ImportError:
    Image = None

# ── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
THEME_DIR = os.path.join(PROJECT_ROOT, "theme", "default")
DEFAULT_OUTPUT = os.path.join(PROJECT_ROOT, "editor", "characters", "generated")

# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_MODEL = "gemini-3.1-flash-image-preview"
FRAME = 128            # final frame size
GEN_FRAME = 256        # generation frame size (2x for quality)
GEN_STRIP_W = GEN_FRAME * 2  # 512px generation strip
GEN_STRIP_H = GEN_FRAME      # 256px generation strip
STRIP_W = FRAME * 2   # 256px final strip
STRIP_H = FRAME        # 128px tall
SHEET_W = FRAME * 8   # 1024px
SHEET_H = FRAME * 8   # 1024px

CHROMA_KEY = "#00FF00"
CHROMA_PRESETS = {
    "green": {"hex": "#00FF00", "rgb": (0, 255, 0), "label": "green"},
    "blue":  {"hex": "#0000FF", "rgb": (0, 0, 255), "label": "blue"},
    "red":   {"hex": "#FF0000", "rgb": (255, 0, 0), "label": "red"},
}

# ── Prompt Templates ─────────────────────────────────────────────────────────

PROMPTS_DIR = os.path.join(SCRIPT_DIR, "prompts")


def load_template(name):
    """Load a prompt template file by name (without extension)."""
    path = os.path.join(PROMPTS_DIR, f"{name}.txt")
    with open(path) as f:
        return f.read().strip()


MOVE_BIPEDAL = "bipedal"
MOVE_FLOAT = "float"
MOVE_QUADRUPED = "quadruped"
MOVE_TYPES = [MOVE_BIPEDAL, MOVE_FLOAT, MOVE_QUADRUPED]

BIPEDAL_TEXT = "bipedal on two short stubby legs like a human NOT on all fours. "


def _apply_style_overrides(base_style, chroma="green", move=MOVE_BIPEDAL):
    """Apply chroma and movement type overrides to base_style string."""
    if chroma == "blue":
        base_style = base_style.replace("#00FF00", "#0000FF").replace("green background", "blue background")
    elif chroma == "red":
        base_style = base_style.replace("#00FF00", "#FF0000").replace("green background", "red background")
    if move == MOVE_FLOAT:
        base_style = base_style.replace(BIPEDAL_TEXT, "floating in air, NO legs, NO feet. ")
    elif move == MOVE_QUADRUPED:
        base_style = base_style.replace(BIPEDAL_TEXT, "on all fours, quadruped. ")
    return base_style


def build_prompt(template_name, chroma="green", move=MOVE_BIPEDAL, **kwargs):
    """Build a full prompt from a template, injecting base_style automatically."""
    base_style = _apply_style_overrides(load_template("base_style"), chroma, move)
    template = load_template(template_name)
    return template.format(base_style=base_style, **kwargs)


# ── Character Definitions ────────────────────────────────────────────────────

CHARACTERS_JSON = os.path.join(THEME_DIR, "characters", "characters.json")


def load_characters():
    """Load character definitions from JSON file."""
    if os.path.exists(CHARACTERS_JSON):
        with open(CHARACTERS_JSON) as f:
            return json.load(f)
    return {}


CHARACTERS = load_characters()

ANIMAL_KEYS = [k for k in CHARACTERS if k != "robot"]
ROBOT_KEYS = ["robot"]
ALL_KEYS = list(CHARACTERS.keys())

# Direction generation order: down, right, up (left = flip of right)
DIRECTIONS = ["down", "right", "up"]

# ── Fountain Definition ──────────────────────────────────────────────────────

FOUNTAIN_TILE = 96  # 3x3 tiles = 96x96 per frame (9x character size)
_STYLE_BASE = load_template("base_style")
FOUNTAIN_PROMPT = (
    f"{_STYLE_BASE}, "
    "horizontal sprite strip animation, exactly 8 frames side by side, "
    f"each frame {FOUNTAIN_TILE}x{FOUNTAIN_TILE} pixels, total image {FOUNTAIN_TILE * 8}x{FOUNTAIN_TILE} pixels, "
    f"solid bright green background ({CHROMA_KEY}) behind the object, "
    "large ornamental stone fountain with water splash cycle animation, "
    "detailed stone basin with decorative rim, "
    "water rises and falls in a looping sequence across the 8 frames, "
    "frame 1: calm water, frame 2-3: water rising, frame 4-5: water at peak with droplets, "
    "frame 6-7: water falling, frame 8: settling back to calm, "
    "gray stone base, blue water, small white splash highlights, "
    "top-down RPG game style, consistent stone base across all frames"
)

FOUNTAIN_FRAMES = 8
FOUNTAIN_STRIP_W = FOUNTAIN_TILE * FOUNTAIN_FRAMES  # 768px

# ── Gemini Client ────────────────────────────────────────────────────────────

def _require_deps():
    """Check that required dependencies are available."""
    if Image is None:
        print("ERROR: Pillow is required. Install with: pip install pillow")
        sys.exit(1)


def load_api_key():
    """Load Gemini API key from .env or environment."""
    # Try python-dotenv first
    # Check pie-office root first, then project root
    pie_root = PROJECT_ROOT
    env_path = os.path.join(pie_root, ".env")
    if os.path.exists(env_path) and load_dotenv is not None:
        load_dotenv(env_path)

    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key

    print("ERROR: GEMINI_API_KEY not found.")
    print("Set it in .env at project root or as an environment variable.")
    sys.exit(1)


def create_client(api_key):
    """Create Gemini API client."""
    from google import genai
    return genai.Client(api_key=api_key)


def generate_image(client, prompt, ref_img=None, model=DEFAULT_MODEL):
    """Generate an image via Gemini API. Optionally takes a reference image."""
    from google.genai.types import GenerateContentConfig, Part

    if ref_img is not None:
        buf = io.BytesIO()
        ref_img.save(buf, format="PNG")
        image_part = Part.from_bytes(data=buf.getvalue(), mime_type="image/png")
        contents = [image_part, prompt]
    else:
        contents = prompt

    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    return Image.open(io.BytesIO(part.inline_data.data))
        print("  WARNING: No image data in API response")
        return None
    except Exception as e:
        print(f"  ERROR generating image: {e}")
        return None


# ── Image Processing ─────────────────────────────────────────────────────────

def remove_chroma_key(img, key_color=(0, 255, 0), tolerance=60):
    """
    Replace chroma key background with transparency using HSV-based
    channel strength detection + despill to remove fringing on edges.
    Supports green (0,255,0) and blue (0,0,255) chroma keys.
    """
    import colorsys

    is_blue_key = key_color[2] > key_color[1] and key_color[2] > key_color[0]
    is_red_key = key_color[0] > key_color[1] and key_color[0] > key_color[2]

    img = img.convert("RGBA")
    data = list(img.getdata())
    new_data = []

    for r, g, b, a in data:
        r_f, g_f, b_f = r / 255.0, g / 255.0, b / 255.0
        h, s, v = colorsys.rgb_to_hsv(r_f, g_f, b_f)
        hue_deg = h * 360

        kr, kg, kb = key_color
        is_simple_match = (abs(r - kr) < tolerance and
                           abs(g - kg) < tolerance and
                           abs(b - kb) < tolerance)

        if is_red_key:
            red_strength = r - max(g, b)
            is_chroma_bg = (red_strength > 30 and (hue_deg < 30 or hue_deg > 330) and s > 0.3)
        elif is_blue_key:
            blue_strength = b - max(r, g)
            is_chroma_bg = (blue_strength > 30 and 200 < hue_deg < 280 and s > 0.3)
        else:
            green_strength = g - max(r, b)
            is_chroma_bg = (green_strength > 30 and 80 < hue_deg < 160 and s > 0.3)

        if is_chroma_bg or is_simple_match:
            new_data.append((0, 0, 0, 0))
        else:
            # Despill: reduce key color fringing on edge pixels
            if is_red_key:
                red_strength = r - max(g, b)
                if red_strength > 10 and (hue_deg < 40 or hue_deg > 320):
                    avg_gb = (g + b) // 2
                    r_despilled = min(r, avg_gb + 10)
                    new_data.append((r_despilled, g, b, a))
                else:
                    new_data.append((r, g, b, a))
            elif is_blue_key:
                blue_strength = b - max(r, g)
                if blue_strength > 10 and 180 < hue_deg < 300:
                    avg_rg = (r + g) // 2
                    b_despilled = min(b, avg_rg + 10)
                    new_data.append((r, g, b_despilled, a))
                else:
                    new_data.append((r, g, b, a))
            else:
                green_strength = g - max(r, b)
                if green_strength > 10 and 60 < hue_deg < 180:
                    avg_rb = (r + b) // 2
                    g_despilled = min(g, avg_rb + 10)
                    new_data.append((r, g_despilled, b, a))
                else:
                    new_data.append((r, g, b, a))

    img.putdata(new_data)
    return img


def process_strip(raw_img, gen_w, gen_h, final_w=None, final_h=None,
                   key_color=(0, 255, 0)):
    """
    Process raw API output: resize to gen size → chroma key → resize to final.
    Auto-rotates if orientation doesn't match target.
    If final_w/final_h not set, gen size IS the final size.
    """
    if final_w is None:
        final_w = gen_w
    if final_h is None:
        final_h = gen_h

    w, h = raw_img.size
    # Rotation detection: if target is landscape but image is portrait
    if gen_w > gen_h and h > w:
        print(f"    Rotating 90° CW (portrait {w}x{h} -> landscape)")
        raw_img = raw_img.rotate(-90, expand=True)

    # Step 1: resize to generation size (larger, for clean chroma key)
    if raw_img.size != (gen_w, gen_h):
        print(f"    Resizing {raw_img.size} -> {gen_w}x{gen_h}")
        raw_img = raw_img.resize((gen_w, gen_h), Image.LANCZOS)

    # Step 2: chroma key at high resolution
    result = remove_chroma_key(raw_img, key_color=key_color)

    # Step 3: downscale to final size
    if (final_w, final_h) != (gen_w, gen_h):
        print(f"    Downscaling {gen_w}x{gen_h} -> {final_w}x{final_h}")
        result = result.resize((final_w, final_h), Image.LANCZOS)

    return result


def normalize_strips(strips, frame_w=FRAME, frame_h=FRAME, target_ratio=0.8):
    """
    Normalize character size across all strips.
    Uses frame 1 (standing pose) of each strip to measure character height,
    then scales the entire strip so all standing poses match target_ratio.
    """
    # Measure frame 1 (left half) height from each strip
    heights = {}
    for key, strip in strips.items():
        frame1 = strip.crop((0, 0, frame_w, frame_h))
        bbox = frame1.getbbox()
        if bbox:
            heights[key] = bbox[3] - bbox[1]

    if not heights:
        return strips

    target_h = int(frame_h * target_ratio)
    print(f"  [normalize] Frame 1 heights: {heights}, target={target_h}")

    result = {}
    for key, strip in strips.items():
        if key not in heights:
            result[key] = strip
            continue

        char_h = heights[key]
        if abs(char_h - target_h) < 3:
            result[key] = strip
            continue

        scale = target_h / char_h

        # Scale entire strip
        new_sw = max(1, int(strip.width * scale))
        new_sh = max(1, int(strip.height * scale))
        scaled = strip.resize((new_sw, new_sh), Image.LANCZOS)

        # Place back into correct strip size, bottom-aligned
        out = Image.new("RGBA", (strip.width, strip.height), (0, 0, 0, 0))
        paste_x = (strip.width - new_sw) // 2
        paste_y = strip.height - new_sh
        out.paste(scaled, (paste_x, paste_y))
        result[key] = out
        print(f"    [{key}] scaled {char_h}px -> {target_h}px ({scale:.2f}x)")

    return result


def center_frames_horizontally(strips, frame_w=FRAME, frame_h=FRAME):
    """
    Center each frame's content horizontally within the frame.
    AI-generated sprites often have inconsistent x-positions between frames,
    causing visual jitter during walk animations.
    """
    result = {}
    for key, strip in strips.items():
        n_frames = strip.width // frame_w
        out = Image.new("RGBA", strip.size, (0, 0, 0, 0))
        for i in range(n_frames):
            x = i * frame_w
            frame = strip.crop((x, 0, x + frame_w, frame_h))
            bbox = frame.getbbox()
            if not bbox:
                continue
            content = frame.crop(bbox)
            # Center horizontally, keep vertical position
            cx = (frame_w - content.width) // 2
            out.paste(content, (x + cx, bbox[1]))
        result[key] = out
        print(f"    [{key}] centered {n_frames} frames horizontally")
    return result


def flip_strip_horizontal(strip):
    """
    Flip each 32x32 frame in a horizontal strip individually.
    This produces the left-facing strip from the right-facing one.
    """
    frames = strip.width // FRAME
    flipped = Image.new("RGBA", strip.size, (0, 0, 0, 0))
    for i in range(frames):
        x = i * FRAME
        frame = strip.crop((x, 0, x + FRAME, FRAME))
        frame = frame.transpose(Image.FLIP_LEFT_RIGHT)
        flipped.paste(frame, (x, 0))
    return flipped


def assemble_spritesheet(down_strip, right_strip, up_strip,
                         idle_strip=None, working_strip=None,
                         happy_strip=None):
    """
    Assemble a 512x512 spritesheet from direction strips and action strips.
    Layout:
      Row 0: walk-down   (frames 0-3)
      Row 1: walk-left   (frames 4-7, flipped from right)
      Row 2: walk-right  (frames 8-11)
      Row 3: walk-up     (frames 12-15)
      Row 4: idle        (down, left, right, up — single frames)
      Row 5: working     (2-frame animation, front view)
      Row 6: happy       (2-frame animation, front view)
      Row 7: (reserved)
    """
    sheet = Image.new("RGBA", (SHEET_W, SHEET_H), (0, 0, 0, 0))

    # Row 0: walk-down
    sheet.paste(down_strip, (0, 0 * FRAME))

    # Row 1: walk-left (horizontal flip of right)
    left_strip = flip_strip_horizontal(right_strip)
    sheet.paste(left_strip, (0, 1 * FRAME))

    # Row 2: walk-right
    sheet.paste(right_strip, (0, 2 * FRAME))

    # Row 3: walk-up
    sheet.paste(up_strip, (0, 3 * FRAME))

    # Row 4: idle
    if idle_strip is not None:
        sheet.paste(idle_strip, (0, 4 * FRAME))

    # Row 5: working
    if working_strip is not None:
        sheet.paste(working_strip, (0, 5 * FRAME))

    # Row 6: happy
    if happy_strip is not None:
        sheet.paste(happy_strip, (0, 6 * FRAME))

    return sheet


# ── Character Generation ─────────────────────────────────────────────────────

def extract_idle_strip(down_strip, right_strip, up_strip):
    """
    Extract idle strip from walk strips by taking the first frame of each
    direction. No API calls needed — reuses walk frame 0.
    Returns a 256x64 strip: [idle-down, idle-left, idle-right, idle-up].
    """
    strip = Image.new("RGBA", (FRAME * 4, STRIP_H), (0, 0, 0, 0))

    # Frame 0 of each walk direction
    down_frame = down_strip.crop((0, 0, FRAME, FRAME))
    right_frame = right_strip.crop((0, 0, FRAME, FRAME))
    left_frame = right_frame.transpose(Image.FLIP_LEFT_RIGHT)
    up_frame = up_strip.crop((0, 0, FRAME, FRAME))

    strip.paste(down_frame, (0 * FRAME, 0))
    strip.paste(left_frame, (1 * FRAME, 0))
    strip.paste(right_frame, (2 * FRAME, 0))
    strip.paste(up_frame, (3 * FRAME, 0))

    print("  [idle] Extracted from walk frame 0 (no API call)")
    return strip


def generate_strip(client, prompt, ref_img=None, model=DEFAULT_MODEL,
                    key_color=(0, 255, 0)):
    """
    Generate a 2-frame strip at 256x128, chroma key, downscale to 128x64.
    Optionally takes a reference image for character consistency.
    """
    raw_img = generate_image(client, prompt, ref_img=ref_img, model=model)
    if raw_img is None:
        return None
    return process_strip(raw_img, GEN_STRIP_W, GEN_STRIP_H, STRIP_W, STRIP_H,
                         key_color=key_color)


def generate_base_frame(client, char, model=DEFAULT_MODEL, chroma="green",
                        move=MOVE_BIPEDAL):
    """
    Step 1: Generate a single 128x128 front-facing reference frame.
    This establishes the character's look for all subsequent strips.
    Returns the RAW image (not resized) for use as reference.
    """
    base_style = _apply_style_overrides(load_template("base_style"), chroma, move)
    pose = "floating" if move == MOVE_FLOAT else "standing still"
    prompt = (
        f"{base_style} Single {GEN_FRAME}x{GEN_FRAME} image, not a strip. "
        f"Front view, {pose}. {char['description']}."
    )
    print(f"\n  [base] Generating {GEN_FRAME}x{GEN_FRAME} reference frame ...")
    raw_img = generate_image(client, prompt, model=model)
    if raw_img is None:
        return None
    print(f"    Raw size: {raw_img.size}")
    return raw_img


def generate_character(client, char_key, output_dir, model=DEFAULT_MODEL,
                       delay=2.0, chroma="green", move=MOVE_BIPEDAL,
                       reuse_base=False):
    """
    Generate a single character's spritesheet in 2 steps:
    Step 1: Generate a 128x128 front-facing reference frame (or reuse existing).
    Step 2: Use that as input for all strip generations.
    API calls: 5-6 (0-1 base + 3 walk + working + happy).
    """
    if char_key not in CHARACTERS:
        print(f"ERROR: Unknown character '{char_key}'")
        print(f"Available: {', '.join(ALL_KEYS)}")
        return None

    char = CHARACTERS[char_key]
    print(f"\n{'=' * 60}")
    print(f"Character: {char_key} ({char['animal']})")
    print(f"  {char['description']}")
    print(f"  Output: {output_dir}")
    print(f"  Model: {model}")
    print(f"  2-step: base frame -> strips with reference")
    print(f"  Chroma key: {chroma}")
    print(f"{'=' * 60}")

    chroma_preset = CHROMA_PRESETS[chroma]
    key_color = chroma_preset["rgb"]

    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Generate or load base reference frame
    base_path = os.path.join(output_dir, f"{char_key}_base.png")
    if reuse_base and os.path.exists(base_path):
        base_raw = Image.open(base_path)
        print(f"  [base] Reusing existing: {base_path} ({base_raw.size})")
    else:
        base_raw = generate_base_frame(client, char, model=model, chroma=chroma,
                                           move=move)
        if base_raw is None:
            print("  [base] FAILED — skipping character")
            return None

        base_raw.save(base_path)
        print(f"  [base] Saved: {base_path}")

        if delay > 0:
            time.sleep(delay)

    strips = {}

    # Step 2: Generate walk strips with reference
    for i, direction in enumerate(DIRECTIONS):
        direction_prompt = char["prompts"][direction]
        full_prompt = build_prompt("walk", chroma=chroma, move=move,
                                   description=char["description"],
                                   direction_prompt=direction_prompt)

        print(f"\n  [{direction}] Generating 2-frame walk strip (with ref) ...")
        strip = generate_strip(client, full_prompt, ref_img=base_raw, model=model,
                               key_color=key_color)

        if strip is None:
            print(f"  [{direction}] FAILED — skipping character")
            return None

        strip_path = os.path.join(output_dir, f"{char_key}_{direction}.png")
        strip.save(strip_path)
        print(f"  [{direction}] Saved: {strip_path}")
        strips[direction] = strip

        if delay > 0:
            time.sleep(delay)

    # Idle strip from walk frame 0 (no API call)
    idle_strip = extract_idle_strip(
        strips["down"], strips["right"], strips["up"]
    )
    idle_path = os.path.join(output_dir, f"{char_key}_idle.png")
    idle_strip.save(idle_path)

    # Working strip with reference
    working_prompt = build_prompt("working", chroma=chroma, move=move, description=char["description"])
    print(f"\n  [working] Generating 2-frame strip (with ref) ...")
    working_strip = generate_strip(client, working_prompt, ref_img=base_raw, model=model,
                                   key_color=key_color)
    if working_strip is not None:
        working_path = os.path.join(output_dir, f"{char_key}_working.png")
        working_strip.save(working_path)
        print(f"  [working] Saved: {working_path}")

    if delay > 0:
        time.sleep(delay)

    # Happy strip with reference
    happy_prompt = build_prompt("happy", chroma=chroma, move=move, description=char["description"])
    print(f"\n  [happy] Generating 2-frame strip (with ref) ...")
    happy_strip = generate_strip(client, happy_prompt, ref_img=base_raw, model=model,
                                 key_color=key_color)
    if happy_strip is not None:
        happy_path = os.path.join(output_dir, f"{char_key}_happy.png")
        happy_strip.save(happy_path)
        print(f"  [happy] Saved: {happy_path}")

    # Normalize character sizes across all strips
    all_strips = dict(strips)
    if working_strip is not None:
        all_strips["working"] = working_strip
    if happy_strip is not None:
        all_strips["happy"] = happy_strip

    all_strips = normalize_strips(all_strips)
    all_strips = center_frames_horizontally(all_strips)

    strips["down"] = all_strips["down"]
    strips["right"] = all_strips["right"]
    strips["up"] = all_strips["up"]
    working_strip = all_strips.get("working")
    happy_strip = all_strips.get("happy")

    # Re-extract idle after normalization
    idle_strip = extract_idle_strip(
        strips["down"], strips["right"], strips["up"]
    )

    # Assemble spritesheet
    sheet = assemble_spritesheet(
        strips["down"], strips["right"], strips["up"],
        idle_strip=idle_strip,
        working_strip=working_strip,
        happy_strip=happy_strip,
    )

    sheet_path = os.path.join(output_dir, f"{char_key}.png")
    sheet.save(sheet_path)
    print(f"\n  [DONE] Spritesheet: {sheet_path} ({SHEET_W}x{SHEET_H})")

    return sheet_path


def generate_characters_batch(client, char_keys, output_dir, model=DEFAULT_MODEL,
                              delay=2.0, chroma="green", move=MOVE_BIPEDAL,
                              reuse_base=False):
    """Generate multiple characters."""
    print(f"\nGenerating {len(char_keys)} character(s): {', '.join(char_keys)}")
    print(f"Output: {output_dir}")
    print(f"Model: {model}")
    print(f"Chroma key: {chroma}")

    results = {}
    failed = []

    for i, key in enumerate(char_keys):
        result = generate_character(
            client, key, output_dir, model=model, delay=delay, chroma=chroma,
            move=move, reuse_base=reuse_base,
        )
        if result:
            results[key] = result
        else:
            failed.append(key)

        # Extra delay between characters
        if delay > 0 and i < len(char_keys) - 1:
            time.sleep(delay)

    print(f"\n{'=' * 60}")
    print(f"Results: {len(results)} succeeded, {len(failed)} failed")
    if failed:
        print(f"Failed: {', '.join(failed)}")
    if results:
        print("Generated:")
        for key, path in results.items():
            print(f"  {key}: {path}")

    return results, failed


# ── Fountain Generation ──────────────────────────────────────────────────────

def generate_fountain(client, output_dir, model=DEFAULT_MODEL,
                      candidates=2, delay=2.0):
    """
    Generate fountain animation sprite strips.
    Each strip: 768x96 (8 frames of 96x96).
    Generates multiple candidates for manual selection.
    """
    print(f"\n{'=' * 60}")
    print(f"Fountain Animation")
    print(f"  Frames: {FOUNTAIN_FRAMES}, Strip: {FOUNTAIN_STRIP_W}x{FOUNTAIN_TILE}")
    print(f"  Candidates: {candidates}")
    print(f"  Output: {output_dir}")
    print(f"{'=' * 60}")

    os.makedirs(output_dir, exist_ok=True)
    results = []

    for v in range(1, candidates + 1):
        print(f"\n  [v{v}] Generating fountain animation strip ...")
        raw_img = generate_image(client, FOUNTAIN_PROMPT, model=model)

        if raw_img is None:
            print(f"  [v{v}] FAILED")
            continue

        # Process: resize and remove chroma key (no downscale for fountain)
        strip = process_strip(raw_img, FOUNTAIN_STRIP_W, FOUNTAIN_TILE,
                              FOUNTAIN_STRIP_W, FOUNTAIN_TILE)

        out_path = os.path.join(output_dir, f"fountain_v{v}.png")
        strip.save(out_path)
        print(f"  [v{v}] Saved: {out_path}")
        results.append(out_path)

        if delay > 0 and v < candidates:
            time.sleep(delay)

    print(f"\n  Fountain: {len(results)}/{candidates} candidates generated")
    return results


# ── CLI ──────────────────────────────────────────────────────────────────────

def create_character_from_concept(name, concept, move=MOVE_BIPEDAL):
    """Create a character definition dict from a name and concept string."""
    if move == MOVE_FLOAT:
        prompts = {
            "down": "facing front, floating in air",
            "right": "facing right, side view, floating in air",
            "up": "facing away, back view, back of head visible, floating in air",
        }
    elif move == MOVE_QUADRUPED:
        prompts = {
            "down": "facing front, on all fours",
            "right": "facing right, side view, on all fours",
            "up": "facing away, back view, on all fours",
        }
    else:
        prompts = {
            "down": "facing front",
            "right": "facing right, side view",
            "up": "facing away, back view",
        }
    return {
        "animal": concept.split(",")[0].strip().title(),
        "description": concept.strip(),
        "prompts": prompts,
    }


def list_characters():
    """Print available character definitions."""
    print("\n=== Characters ===\n")
    print(f"  Source: {CHARACTERS_JSON}")
    for key, char in CHARACTERS.items():
        tag = "[ROBOT/GRAYSCALE]" if key == "robot" else f"[{char['animal']}]"
        print(f"  {key:12s} {tag:22s} {char['description']}")

    print(f"\n  Total: {len(CHARACTERS)} characters")
    print(f"  Animals: {', '.join(ANIMAL_KEYS)}")
    print(f"  Robot: {', '.join(ROBOT_KEYS)}")

    print("\n=== Sprite Format ===\n")
    print(f"  Frame size:   {FRAME}x{FRAME} pixels")
    print(f"  Strip size:   {STRIP_W}x{STRIP_H} (2 frames per animation)")
    print(f"  Sheet size:   {SHEET_W}x{SHEET_H} (8 rows)")
    print(f"  Rows:         walk(down,left,right,up), idle, working, happy, reserved")
    print(f"  Left frames:  auto-flipped from right (not generated)")
    print(f"  Templates:    {PROMPTS_DIR}")

    print("\n=== Fountain ===\n")
    print(f"  Strip size:   {FOUNTAIN_STRIP_W}x{FOUNTAIN_TILE} (8 frames of {FOUNTAIN_TILE}x{FOUNTAIN_TILE})")
    print(f"  Candidates:   2 versions generated for manual selection")


def main():
    parser = argparse.ArgumentParser(
        description="Generate character sprites and fountain animation via Gemini API",
    )

    # Character selection (mutually exclusive group for convenience)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-c", "--character",
        type=str,
        help="Generate a specific character by key name",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Generate all 7 characters",
    )
    group.add_argument(
        "--animals",
        action="store_true",
        help="Generate just the 6 animal characters",
    )
    group.add_argument(
        "--robot",
        action="store_true",
        help="Generate just the robot character",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List available characters and exit",
    )

    # Add new character from concept
    parser.add_argument(
        "--add",
        type=str,
        metavar="NAME:CONCEPT",
        help='Add a new character. Format: "fox_b:arctic fox, white fur, blue scarf"',
    )

    # Fountain flag (can combine with character flags)
    parser.add_argument(
        "--fountain",
        action="store_true",
        help="Generate fountain animation sprites (2 candidates)",
    )

    # Output and model options
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Gemini model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay in seconds between API calls (default: 2.0)",
    )
    parser.add_argument(
        "--chroma",
        type=str,
        choices=["green", "blue", "red"],
        default="green",
        help="Chroma key color (default: green). Use blue for green characters.",
    )
    parser.add_argument(
        "--move",
        type=str,
        choices=MOVE_TYPES,
        default=MOVE_BIPEDAL,
        help="Movement type: bipedal (default), float (no legs), quadruped (4 legs).",
    )
    parser.add_argument(
        "--reuse-base",
        action="store_true",
        help="Reuse existing base frame instead of generating a new one.",
    )

    args = parser.parse_args()

    # Handle --list
    if args.list:
        list_characters()
        return

    # Handle --add
    char_keys = []
    if args.add:
        if ":" not in args.add:
            print('ERROR: --add format is "name:concept"')
            sys.exit(1)
        name, concept = args.add.split(":", 1)
        name = name.strip()
        concept = concept.strip()
        CHARACTERS[name] = create_character_from_concept(name, concept, move=args.move)
        char_keys = [name]

    # Determine what to generate
    elif args.character:
        if args.character not in CHARACTERS:
            print(f"ERROR: Unknown character '{args.character}'")
            print(f"Available: {', '.join(ALL_KEYS)}")
            sys.exit(1)
        char_keys = [args.character]
    elif args.all:
        char_keys = ALL_KEYS
    elif args.animals:
        char_keys = ANIMAL_KEYS
    elif args.robot:
        char_keys = ROBOT_KEYS

    # Must generate something
    if not char_keys and not args.fountain:
        parser.print_help()
        print("\nERROR: Specify --all, --animals, --robot, -c NAME, --fountain, or --list")
        sys.exit(1)

    # Check dependencies and initialize API client
    _require_deps()
    api_key = load_api_key()
    client = create_client(api_key)

    # Generate characters
    if char_keys:
        generate_characters_batch(
            client, char_keys, args.output,
            model=args.model, delay=args.delay, chroma=args.chroma,
            move=args.move, reuse_base=args.reuse_base,
        )

    # Generate fountain
    if args.fountain:
        generate_fountain(
            client, args.output,
            model=args.model, delay=args.delay,
        )

    print("\nAll done.")


if __name__ == "__main__":
    main()
