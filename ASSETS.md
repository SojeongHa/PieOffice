# Pie Office — Asset Attribution

## Tileset & Characters

| Asset | Source | License | Notes |
|-------|--------|---------|-------|
| Default tileset | AI-generated (Gemini API) + Pillow processing | MIT | `theme/default/tileset.png` — 32x32 tiles |
| Character spritesheets | AI-generated (Gemini API) + chroma key cleanup | MIT | `theme/default/characters/*.png` — 128x128 frames, 1024x1024 sheets |
| Object sprites | AI-generated (Gemini API) + Pillow processing | MIT | `theme/default/objects/*.png` — static and animated |
| Window backgrounds | AI-generated (Gemini API) + seasonal variants | MIT | `theme/default/background/windows/` — 16 images (4 seasons x 4 times) |

## Fonts

- **Press Start 2P** — Google Fonts (OFL license). Used for in-game name tags and speech bubbles.

## Theme Structure

```
theme/default/
├── config.json              # Theme metadata, agent map, room positions, objects
├── tileset.png              # Tile graphics (32x32 per tile)
├── tilemap.json             # Room layout (Tiled-compatible)
├── room_areas.json          # Walkable tiles per room
├── background/
│   └── windows/             # 16 seasonal window panoramas
├── characters/
│   ├── characters.json      # Character definitions
│   ├── sprites.json         # Animation frame definitions
│   ├── leader.png           # Penguin (1024x1024, 8x8 grid of 128x128)
│   ├── coder_a.png          # Cat
│   ├── coder_b.png          # Dog
│   ├── coder_c.png          # Squirrel
│   ├── coder_d.png          # Duck
│   ├── coder_e.png          # Raccoon
│   ├── explorer.png         # Fox
│   ├── planner.png          # Bear
│   └── robot.png            # Robot (grayscale, tinted at runtime)
└── objects/
    ├── bookshelf_a.png      # Static object sprites
    ├── desk_large_b.png
    ├── desk_large_c.png
    ├── desk_manager.png
    ├── whiteboard.png
    ├── coffee_table.png
    ├── bench_c.png
    ├── bench_back.png
    ├── robot_vacuum.png     # 4-frame animated spritesheet
    ├── alert_exclamation.png # 2-frame alert sprite
    └── alert_question.png   # 2-frame alert sprite
```

## License Summary

| Component | License | Attribution Required |
|-----------|---------|---------------------|
| Code (`.py`, `.js`, `.html`) | MIT | Yes |
| AI-generated art (`theme/default/`) | MIT | Yes |
| Press Start 2P font | OFL 1.1 | Yes |
| Custom themes (if added) | Per-asset | Per-asset |
