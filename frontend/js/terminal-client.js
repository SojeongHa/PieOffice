// frontend/js/terminal-client.js
// Terminal client — connects to asyncio terminal server via WebSocket

(function () {
  "use strict";

  var SYNC_INTERVAL = 5000;

  var token = "";
  var ws = null;
  var term = null;
  var fitAddon = null;
  var currentSession = null;
  var reconnectTimeout = null;
  var syncTimer = null;
  var lastSessionsJson = "";

  // ── Auto-init ─────────────────────────────────────────

  acquireSessionToken();

  function acquireSessionToken() {
    fetch(location.origin + "/session-token")
      .then(function (r) {
        if (!r.ok) { showError("Device not authorized."); return null; }
        return r.json();
      })
      .then(function (data) {
        if (!data) return;
        token = data.token;
        fetchSessionsAndShow();
      })
      .catch(function () { showError("Connection failed."); });
  }

  function showError(msg) {
    var el = document.getElementById("auth-error");
    if (el) el.textContent = msg;
  }

  // ── Session List ──────────────────────────────────────

  function fetchSessions() {
    return fetch(location.origin + "/sessions", {
      headers: { Authorization: "Bearer " + token },
    }).then(function (r) {
      if (r.status === 401) { acquireSessionToken(); return null; }
      return r.json();
    });
  }

  function fetchSessionsAndShow() {
    var dot = document.getElementById("sync-dot");
    if (dot) dot.classList.add("syncing");
    fetchSessions()
      .then(function (data) {
        if (!data) return;
        showMainLayout();
        renderSessionList(data.sessions);
        startAutoSync();
      })
      .catch(function () { showError("Connection failed"); })
      .finally(function () { if (dot) dot.classList.remove("syncing"); });
  }

  function startAutoSync() {
    if (syncTimer) return;
    syncTimer = setInterval(function () {
      var dot = document.getElementById("sync-dot");
      if (dot) dot.classList.add("syncing");
      fetchSessions()
        .then(function (data) {
          if (!data) return;
          var json = JSON.stringify(data.sessions);
          if (json !== lastSessionsJson) renderSessionList(data.sessions);
        })
        .finally(function () { if (dot) dot.classList.remove("syncing"); });
    }, SYNC_INTERVAL);
  }

  function showMainLayout() {
    document.getElementById("auth-screen").style.display = "none";
    document.getElementById("main-layout").style.display = "flex";
  }

  function renderSessionList(sessions) {
    lastSessionsJson = JSON.stringify(sessions);
    var list = document.getElementById("session-list");
    list.innerHTML = "";
    if (sessions.length === 0) {
      list.innerHTML = '<div class="no-sessions">No active sessions.<br>Start Claude with claude-tmux.</div>';
      return;
    }
    sessions.forEach(function (s) {
      var item = document.createElement("div");
      item.className = "session-item" + (s.name === currentSession ? " active" : "");
      item.onclick = function () { connectSession(s.name); closeSidebarOnMobile(); };
      var statusClass = s.attached > 0 ? "attached" : "detached";
      var shortCwd = s.cwd.replace(/^\/Users\/[^/]+\//, "~/");
      var projectName = shortCwd.split("/").pop() || s.name;
      item.innerHTML =
        '<span class="session-status ' + statusClass + '"></span>' +
        '<div class="session-info">' +
          '<div class="session-name">' + projectName + '</div>' +
          '<div class="session-cwd">' + shortCwd + '</div>' +
        '</div>';
      list.appendChild(item);
    });
  }

  // ── Sidebar ───────────────────────────────────────────

  window.toggleSidebar = function () {
    var sidebar = document.getElementById("sidebar");
    var overlay = document.getElementById("sidebar-overlay");
    var toggle = document.getElementById("sidebar-toggle");
    sidebar.classList.toggle("open");
    overlay.classList.toggle("open");
    toggle.style.display = sidebar.classList.contains("open") ? "none" : "flex";
  };

  function closeSidebarOnMobile() {
    document.getElementById("sidebar").classList.remove("open");
    document.getElementById("sidebar-overlay").classList.remove("open");
    document.getElementById("sidebar-toggle").style.display = "";
  }

  // ── Terminal Connection ────────────────────────────────

  function connectSession(sessionName) {
    if (ws) ws.close();
    if (reconnectTimeout) { clearTimeout(reconnectTimeout); reconnectTimeout = null; }
    currentSession = sessionName;
    if (lastSessionsJson) renderSessionList(JSON.parse(lastSessionsJson));

    document.getElementById("terminal-header").style.display = "flex";
    document.getElementById("session-title").textContent = sessionName;
    setStatus("connecting", "Connecting...");

    document.getElementById("empty-state").style.display = "none";
    document.getElementById("quick-actions").style.display = "flex";
    var termContainer = document.getElementById("terminal-container");
    termContainer.style.display = "block";
    termContainer.innerHTML = "";

    term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: '"Menlo", "Courier New", monospace',
      scrollback: 5000,
      scrollSensitivity: 3,
      theme: {
        background: "#1a1a2e",
        foreground: "#D1D2D3",
        cursor: "#E8D44D",
        selectionBackground: "rgba(81,54,131,0.5)",
        black: "#1a1a2e",
        brightBlack: "#696969",
      },
      allowProposedApi: true,
    });

    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon.WebLinksAddon());
    term.open(termContainer);

    new ResizeObserver(function () { fitAddon.fit(); }).observe(termContainer);



    // WebSocket to asyncio terminal server
    var wsProto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(wsProto + "://" + location.host + "/ws/" + sessionName);

    var pingInterval = null;

    ws.onopen = function () {
      ws.send(JSON.stringify({ type: "auth", token: token }));
      pingInterval = setInterval(function () {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, 3000);
    };

    ws.onmessage = function (event) {
      var msg = JSON.parse(event.data);
      if (msg.type === "connected") {
        setStatus("connected", "Connected");
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      } else if (msg.type === "output") {
        term.write(msg.data);
        term.scrollToBottom();
      } else if (msg.type === "error") {
        setStatus("disconnected", msg.message);
        if (msg.message === "unauthorized") acquireSessionToken();
      }
    };

    ws.onclose = function () {
      if (pingInterval) { clearInterval(pingInterval); pingInterval = null; }
      setStatus("disconnected", "Disconnected");
      scheduleReconnect(sessionName);
    };

    ws.onerror = function () { setStatus("disconnected", "Error"); };

    term.onData(function (data) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "input", data: data }));
      }
    });

    term.onResize(function (size) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols: size.cols, rows: size.rows }));
      }
    });
  }

  // ── Disconnect ─────────────────────────────────────────

  window.disconnectSession = function () {
    if (reconnectTimeout) { clearTimeout(reconnectTimeout); reconnectTimeout = null; }
    currentSession = null;
    if (ws) { ws.close(); ws = null; }
    if (term) { term.dispose(); term = null; fitAddon = null; }

    document.getElementById("terminal-header").style.display = "none";
    document.getElementById("terminal-container").style.display = "none";
    document.getElementById("terminal-container").innerHTML = "";
    document.getElementById("quick-actions").style.display = "none";
    document.getElementById("empty-state").style.display = "flex";

    if (lastSessionsJson) renderSessionList(JSON.parse(lastSessionsJson));
  };

  // ── Quick Actions (exposed globally for onclick) ───────

  // Expose on window so HTML onclick can access
  window._termSend = function (data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "input", data: data }));
    }
  };

  window._termSendInput = function () {
    var input = document.getElementById("term-input");
    if (!input) return;
    var text = input.value;
    if (text) {
      window._termSend(text + "\r");
    }
    input.value = "";
    input.focus();
  };

  window._termScrollUp = function () {
    // Send tmux scroll: Ctrl+B [ then Page Up
    window._termSend("\x02[");
    setTimeout(function () { window._termSend("\x1b[5~"); }, 100);
  };

  window._termScrollDown = function () {
    // Send tmux scroll: Ctrl+B [ then Page Down, then q to exit
    window._termSend("\x02[");
    setTimeout(function () { window._termSend("\x1b[6~"); }, 100);
  };

  document.getElementById("term-input").addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      window._termSendInput();
    }
  });

  function setStatus(state, text) {
    var dot = document.getElementById("status-dot");
    var label = document.getElementById("status-text");
    if (dot) dot.className = "status-dot " + state;
    if (label) label.textContent = text;
  }

  function scheduleReconnect(sessionName) {
    if (reconnectTimeout) clearTimeout(reconnectTimeout);
    if (!currentSession) return;
    reconnectTimeout = setTimeout(function () {
      if (currentSession === sessionName) connectSession(sessionName);
    }, 3000);
  }
})();
