/**
 * Dialogue — Hybrid speech bubble text generator.
 *
 * Priority: context-based detail > state template fallback.
 */

/* exported Dialogue */
const Dialogue = (() => {
  const TEMPLATES = {
    idle:        ["break time~", "coffee...", "taking a breather", "zZz..."],
    writing:     ["coding...", "let me fix this", "writing...", "almost done..."],
    executing:   ["running!", "let's see...", "building...", "executing..."],
    researching: ["hmm let me check...", "searching...", "where is it...", "reading..."],
    reporting:   ["reporting in!", "boss!", "need your input", "excuse me..."],
    debugging:   ["found a bug...", "this is weird...", "checking logs...", "hmm..."],
    error:       ["error!", "uh oh...", "we have a problem", "this broke..."],
  };

  function _pick(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
  }

  /**
   * Generate bubble text for a state change.
   *
   * @param {string} state  - Agent state (idle, writing, executing, ...).
   * @param {string} [detail] - Optional context from hook (file name, command, question).
   * @returns {{ text: string, duration: number }}
   */
  function forStateChange(state, detail) {
    if (detail && detail.trim()) {
      const trimmed = detail.length > 40 ? detail.slice(0, 37) + "..." : detail;
      return { text: trimmed, duration: 5000 };
    }
    const pool = TEMPLATES[state] || TEMPLATES.idle;
    return { text: _pick(pool), duration: 3000 };
  }

  return { forStateChange };
})();
