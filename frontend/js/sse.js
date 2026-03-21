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
    /** @type {number|null} Reconnection timer */
    this._reconnectTimer = null;
    /** @type {number} Current backoff delay (ms) */
    this._backoff = 1000;
    /** @type {boolean} Whether connect() was called by the user */
    this._wantConnected = false;
  }

  // ── Public API ────────────────────────────────────────────────

  /**
   * Open the EventSource connection and wire up all registered events.
   * Uses manual reconnection with exponential backoff instead of
   * relying on EventSource's built-in auto-reconnect (which lacks backoff
   * and can cause FD exhaustion after Mac sleep).
   */
  connect() {
    this._wantConnected = true;
    this._backoff = 1000;
    this._doConnect();
  }

  /**
   * Internal: create the EventSource and set up handlers.
   */
  _doConnect() {
    if (this._source) {
      this._source.close();
      this._source = null;
    }

    this._source = new EventSource(this.url);

    this._source.onopen = () => {
      console.log("[SSE] Connected to", this.url);
      this._backoff = 1000; // reset backoff on successful connection
      this._emit("_open", null);
    };

    this._source.onerror = () => {
      // Close immediately to release the socket — we handle reconnection manually
      if (this._source) {
        this._source.close();
        this._source = null;
      }
      this._scheduleReconnect();
      this._emit("_error", null);
    };

    this._rebindAll();
  }

  /**
   * Schedule a reconnection with exponential backoff (1s → 2s → 4s → … → 30s max).
   */
  _scheduleReconnect() {
    if (!this._wantConnected) return;
    if (this._reconnectTimer) return; // already scheduled

    const delay = this._backoff;
    this._backoff = Math.min(this._backoff * 2, 30000);
    console.log(`[SSE] Reconnecting in ${delay}ms`);

    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      if (this._wantConnected) {
        this._doConnect();
      }
    }, delay);
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
   * Close the underlying EventSource connection and stop reconnection.
   */
  close() {
    this._wantConnected = false;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
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
