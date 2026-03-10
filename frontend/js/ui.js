/**
 * Pie Office — UI Manager (Side Panel)
 *
 * Manages the side-panel overlay that displays agent status cards and an
 * event log.  Works alongside the Phaser canvas — the game renders on
 * <canvas>, while this module operates on regular DOM elements layered
 * on top.
 *
 * Depends on: I18N (i18n.js), CONFIG (config.js)
 */

/* exported UIManager */
class UIManager {
  /**
   * @param {object} agentManager - AgentManager instance with getAll() method.
   */
  constructor(agentManager) {
    this.agentManager = agentManager;
    this.panel = document.getElementById("side-panel");
    this.agentList = document.getElementById("agent-list");
    this.logList =
      document.getElementById("event-log") ||
      document.getElementById("log-list");
    this.toggle = document.getElementById("panel-toggle");

    // Toggle panel open / close
    this.toggle.addEventListener("click", () => {
      this.panel.classList.toggle("open");
      this.toggle.classList.toggle("shifted");
    });

    // Re-apply translations when language changes at runtime
    window.addEventListener("langchange", () => this.applyI18n());
  }

  // ── Internationalisation ────────────────────────────────────────

  /**
   * Apply translated strings to all static UI elements in the panel.
   */
  applyI18n() {
    // Panel section titles
    const panelTitle = document.getElementById("panel-title");
    if (panelTitle) {
      panelTitle.textContent = I18N.t("panel.agents");
    }

    const logTitle = document.getElementById("log-title");
    if (logTitle) {
      logTitle.textContent = I18N.t("panel.log");
    }

    // Document title
    document.title = I18N.t("app.title");

    // Re-render the agent list so state / room labels update
    this.updateAgentList();
  }

  // ── Agent List ──────────────────────────────────────────────────

  /** Active-state set used to determine the status-dot colour. */
  static ACTIVE_STATES = new Set([
    "writing",
    "executing",
    "researching",
    "reading",
    "reporting",
  ]);

  /** Error-state set. */
  static ERROR_STATES = new Set(["error", "debugging"]);

  /**
   * Return the CSS class for the status dot based on agent state.
   * @param {string} state
   * @returns {"active"|"idle"|"error"}
   */
  _dotClass(state) {
    if (UIManager.ACTIVE_STATES.has(state)) return "active";
    if (UIManager.ERROR_STATES.has(state)) return "error";
    return "idle";
  }

  /**
   * Re-render the agent list inside the side panel.
   * Each agent is displayed as a card with a coloured status dot,
   * display name, translated state, and room label.
   */
  updateAgentList() {
    const agents = this.agentManager.getAll();

    if (!agents || agents.length === 0) {
      this.agentList.innerHTML =
        '<div class="agent-card">' +
        '<span class="agent-state" style="color:#5a5a7c">' +
        "No agents connected" +
        "</span></div>";
      return;
    }

    const cards = agents.map((agent) => {
      const dot = this._dotClass(agent.state);
      const stateTxt = I18N.t(`state.${agent.state}`);
      const roomTxt = I18N.t(`room.${agent.room}`);

      return (
        '<div class="agent-card">' +
        `<span class="status-dot ${dot}"></span>` +
        '<div class="agent-info">' +
        `<div class="agent-name">${this._esc(agent.displayName || agent.name)}</div>` +
        `<div class="agent-state">${this._esc(stateTxt)} &middot; ${this._esc(roomTxt)}</div>` +
        "</div></div>"
      );
    });

    this.agentList.innerHTML = cards.join("");
  }

  // ── Event Log ───────────────────────────────────────────────────

  /** Maximum number of log entries kept in the DOM. */
  static MAX_LOG_ENTRIES = 50;

  /**
   * Add a timestamped entry to the event log (newest first).
   * Entries beyond MAX_LOG_ENTRIES are pruned from the bottom.
   *
   * @param {string} text - Human-readable log line.
   */
  addLogEntry(text) {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    const ss = String(now.getSeconds()).padStart(2, "0");
    const timestamp = `[${hh}:${mm}:${ss}]`;

    const entry = document.createElement("div");
    entry.className = "log-entry";
    entry.innerHTML =
      `<span class="log-time">${timestamp}</span>` +
      `<span class="log-msg">${this._esc(text)}</span>`;

    // Prepend so newest entries appear at the top
    this.logList.prepend(entry);

    // Prune oldest entries
    while (this.logList.children.length > UIManager.MAX_LOG_ENTRIES) {
      this.logList.removeChild(this.logList.lastChild);
    }
  }

  // ── Helpers ─────────────────────────────────────────────────────

  /**
   * Minimal HTML-escape to prevent injection when building innerHTML.
   * @param {string} str
   * @returns {string}
   */
  _esc(str) {
    if (typeof str !== "string") return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}
