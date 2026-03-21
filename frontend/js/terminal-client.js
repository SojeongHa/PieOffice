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

      var statusDot = document.createElement("span");
      statusDot.className = "session-status " + statusClass;

      var nameEl = document.createElement("div");
      nameEl.className = "session-name";
      nameEl.textContent = projectName;

      var cwdEl = document.createElement("div");
      cwdEl.className = "session-cwd";
      cwdEl.textContent = shortCwd;

      var infoEl = document.createElement("div");
      infoEl.className = "session-info";
      infoEl.appendChild(nameEl);
      infoEl.appendChild(cwdEl);

      // Alert message line + badge for permission_prompt / idle_prompt
      if (s.alert_type) {
        var msgEl = document.createElement("div");
        msgEl.className = "session-alert-msg " + s.alert_type;
        msgEl.textContent = s.alert_message || s.alert_type;
        infoEl.appendChild(msgEl);
        item.classList.add("has-alert");
      }

      item.appendChild(statusDot);
      item.appendChild(infoEl);

      if (s.alert_type) {
        var badge = document.createElement("span");
        badge.className = "session-alert " + s.alert_type;
        badge.textContent = s.alert_type === "permission_prompt" ? "!" : "?";
        item.appendChild(badge);
      }

      list.appendChild(item);
    });
  }

  // ── Sidebar ───────────────────────────────────────────

  function toggleSidebar() {
    var sidebar = document.getElementById("sidebar");
    var overlay = document.getElementById("sidebar-overlay");
    var toggle = document.getElementById("sidebar-toggle");
    sidebar.classList.toggle("open");
    overlay.classList.toggle("open");
    toggle.style.display = sidebar.classList.contains("open") ? "none" : "flex";
  }

  document.getElementById("sidebar-toggle").addEventListener("click", toggleSidebar);
  document.getElementById("sidebar-overlay").addEventListener("click", toggleSidebar);

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
      var msg;
      try { msg = JSON.parse(event.data); } catch (e) { return; }
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

  function disconnectSession() {
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
  }

  // ── Quick Actions ────────────────────────────────────

  function termSend(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "input", data: data }));
    }
  }

  function termSendInput() {
    var input = document.getElementById("term-input");
    if (!input) return;
    var text = input.value;
    if (text) {
      termSend(text + "\r");
    }
    input.value = "";
    input.focus();
  }

  function termClearInput() {
    var input = document.getElementById("term-input");
    if (!input) return;
    input.value = "";
    input.focus();
  }

  var scrollMode = false;
  var touchStartY = 0;

  function termToggleScroll() {
    var btn = document.getElementById("btn-scroll-mode");
    if (!scrollMode) {
      termSend("\x02[");
      scrollMode = true;
      btn.textContent = "Exit Scroll";
      btn.style.background = "var(--bg-sidebar-active)";
      btn.style.color = "#fff";
    } else {
      termSend("q");
      scrollMode = false;
      btn.textContent = "Scroll";
      btn.style.background = "";
      btn.style.color = "";
    }
  }

  // Bind all quick action buttons (CSP blocks inline handlers)
  document.getElementById("disconnect-btn").addEventListener("click", disconnectSession);
  document.getElementById("btn-send").addEventListener("touchend", termSendInput);
  document.getElementById("btn-scroll-mode").addEventListener("touchend", termToggleScroll);
  document.getElementById("btn-up").addEventListener("touchend", function () { termSend("\x1b[A"); });
  document.getElementById("btn-down").addEventListener("touchend", function () { termSend("\x1b[B"); });
  document.getElementById("btn-1").addEventListener("touchend", function () { termSend("1"); });
  document.getElementById("btn-2").addEventListener("touchend", function () { termSend("2"); });
  document.getElementById("btn-3").addEventListener("touchend", function () { termSend("3"); });
  document.getElementById("btn-clear").addEventListener("touchend", termClearInput);
  document.getElementById("btn-enter").addEventListener("touchend", function () { termSend("\r"); });

  // Touch scroll when in scroll mode — send arrow keys to tmux
  document.addEventListener("touchstart", function (e) {
    if (scrollMode) touchStartY = e.touches[0].clientY;
  }, { passive: true });

  document.addEventListener("touchmove", function (e) {
    if (!scrollMode) return;
    var container = document.getElementById("terminal-container");
    if (!container || !container.contains(e.target)) return;
    var dy = touchStartY - e.touches[0].clientY;
    if (Math.abs(dy) > 5) {
      var key = dy > 0 ? "\x1b[B" : "\x1b[A";
      var lines = Math.floor(Math.abs(dy) / 5);
      for (var i = 0; i < lines; i++) termSend(key);
      touchStartY = e.touches[0].clientY;
      e.preventDefault();
    }
  }, { passive: false });

  document.getElementById("term-input").addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      termSendInput();
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
