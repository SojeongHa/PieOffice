/**
 * Pie Office — Global configuration.
 *
 * All magic numbers and endpoint URLs live here so every other module can
 * simply reference CONFIG.* without hard-coding values.
 */

/* exported CONFIG */
const CONFIG = {
  // ── Tilemap ───────────────────────────────────────────────────
  TILE_SIZE: 32,
  SCALE: 1,
  MAP_WIDTH: 44,
  MAP_HEIGHT: 24,
  CANVAS_WIDTH: 1408,
  CANVAS_HEIGHT: 768,
  WINDOW_BG_Y: 0,

  // ── Movement ──────────────────────────────────────────────────
  WALK_SPEED: 120,
  CHAR_SCALE: 0.75,

  // ── Endpoints ─────────────────────────────────────────────────
  SSE_URL: "/stream",
  STATE_URL: "/state",
  THEME_URL: "/theme",

  // ── Rooms ─────────────────────────────────────────────────────
  ROOMS: {
    manager: { label: "Manager Room", color: "#e8d44d" },
    work: { label: "Cafeteria", color: "#7ec8e3" },
    break: { label: "Balcony", color: "#4caf50" },
    server: { label: "Server Room", color: "#f44336" },
  },

};
