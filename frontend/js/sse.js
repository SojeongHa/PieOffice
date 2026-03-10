/**
 * Pie Office — SSE Client.
 *
 * Wraps the native EventSource with a simple event-emitter interface and
 * auto-reconnect (EventSource reconnects natively, we just log warnings).
 *
 * Usage:
 *   const sse = new SSEClient(CONFIG.SSE_URL);
 *   sse.on("agent_update", (data) => { ... });
 *   sse.connect();
 */

/* global CONFIG */
/* exported SSEClient */

class SSEClient {
  /**
   * @param {string} url — SSE endpoint (defaults to CONFIG.SSE_URL).
   */
  constructor(url) {
    this.url = url || CONFIG.SSE_URL;
    /** @type {EventSource|null} */
    this._source = null;
    /** @type {Object<string, Function[]>} */
    this._handlers = {};
  }

  // ── Public API ────────────────────────────────────────────────

  /**
   * Open the EventSource connection and wire up all registered events.
   */
  connect() {
    if (this._source) {
      this.close();
    }

    this._source = new EventSource(this.url);

    this._source.onopen = () => {
      console.log("[SSE] Connected to", this.url);
    };

    this._source.onerror = (err) => {
      console.warn("[SSE] Connection error — browser will auto-reconnect", err);
      this._emit("_error", err);
    };

    this._rebindAll();
  }

  /**
   * Register a handler for a named SSE event.
   *
   * @param {string} event — event name (e.g. "agent_update").
   * @param {Function} handler — receives the parsed JSON data object.
   * @returns {SSEClient} — for chaining.
   */
  on(event, handler) {
    if (!this._handlers[event]) {
      this._handlers[event] = [];
    }
    this._handlers[event].push(handler);

    if (this._source) {
      this._bindEvent(event);
    }

    return this;
  }

  /**
   * Remove a previously registered handler.
   *
   * @param {string} event
   * @param {Function} handler
   * @returns {SSEClient}
   */
  off(event, handler) {
    const list = this._handlers[event];
    if (list) {
      this._handlers[event] = list.filter((h) => h !== handler);
    }
    return this;
  }

  /**
   * Close the underlying EventSource connection.
   */
  close() {
    if (this._source) {
      this._source.close();
      this._source = null;
      console.log("[SSE] Connection closed");
    }
  }

  // ── Internals ─────────────────────────────────────────────────

  /**
   * Emit to all internal handlers for a given event name.
   */
  _emit(event, data) {
    const list = this._handlers[event];
    if (!list) return;
    for (const handler of list) {
      try {
        handler(data);
      } catch (err) {
        console.error(`[SSE] Handler error for event '${event}':`, err);
      }
    }
  }

  /**
   * Bind a single named event on the EventSource so that incoming messages
   * with that event name are dispatched through our handler map.
   */
  _bindEvent(event) {
    if (event.startsWith("_")) return;
    if (!this._source) return;

    const tag = `__bound_${event}`;
    if (this._source[tag]) return;
    this._source[tag] = true;

    this._source.addEventListener(event, (e) => {
      let data;
      try {
        data = JSON.parse(e.data);
      } catch (err) {
        console.error("[SSE] Failed to parse event data:", e.data, err);
        return;
      }
      this._emit(event, data);
    });
  }

  /**
   * Re-bind all currently registered event names on the active EventSource.
   */
  _rebindAll() {
    for (const event of Object.keys(this._handlers)) {
      this._bindEvent(event);
    }
  }
}
