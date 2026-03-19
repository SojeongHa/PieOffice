// frontend/js/terminal-client.js
// Slack-style terminal client with auto-sync session list

(function () {
  "use strict";

  const SYNC_INTERVAL = 5000; // Auto-sync session list every 5s

  let token = localStorage.getItem("pie-terminal-token") || "";
  let ws = null;
  let term = null;
  let fitAddon = null;
  let currentSession = null;
  let reconnectTimeout = null;
  let syncTimer = null;
  let lastSessionsJson = "";

  // ── Auth ──────────────────────────────────────────────

  window.authenticate = function () {
    var input = document.getElementById("token-input");
    token = input.value.trim();
    if (!token) return;
    localStorage.setItem("pie-terminal-token", token);
    fetchSessionsAndShow();
  };

  // Auto-auth if token saved
  if (token) {
    fetchSessionsAndShow();
  }

  // ── Session List (auto-sync) ──────────────────────────

  function fetchSessions() {
    return fetch(location.origin + "/terminal/sessions", {
      headers: { Authorization: "Bearer " + token },
    }).then(function (r) {
      if (r.status === 401) {
        localStorage.removeItem("pie-terminal-token");
        location.reload();
        return null;
      }
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
      .catch(function () {
        document.getElementById("auth-error").textContent = "Connection failed";
      })
      .finally(function () {
        if (dot) dot.classList.remove("syncing");
      });
  }

  function startAutoSync() {
    if (syncTimer) return;
    syncTimer = setInterval(function () {
      var dot = document.getElementById("sync-dot");
      if (dot) dot.classList.add("syncing");

      fetchSessions()
        .then(function (data) {
          if (!data) return;
          // Only re-render if sessions changed (avoid flicker)
          var json = JSON.stringify(data.sessions);
          if (json !== lastSessionsJson) {
            renderSessionList(data.sessions);
          }
        })
        .finally(function () {
          if (dot) dot.classList.remove("syncing");
        });
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
      list.innerHTML =
        '<div class="no-sessions">No active sessions.<br>Start Claude with the tmux wrapper.</div>';
      return;
    }

    sessions.forEach(function (s) {
      var item = document.createElement("div");
      item.className = "session-item" + (s.name === currentSession ? " active" : "");
      item.onclick = function () {
        connectSession(s.name);
        closeSidebarOnMobile();
      };

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

  // ── Sidebar toggle (mobile) ───────────────────────────

  window.toggleSidebar = function () {
    document.getElementById("sidebar").classList.toggle("open");
    document.getElementById("sidebar-overlay").classList.toggle("open");
  };

  function closeSidebarOnMobile() {
    document.getElementById("sidebar").classList.remove("open");
    document.getElementById("sidebar-overlay").classList.remove("open");
  }

  // ── Terminal Connection ────────────────────────────────

  function connectSession(sessionName) {
    if (ws) ws.close();
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout);
      reconnectTimeout = null;
    }
    currentSession = sessionName;

    // Re-render to update active state
    if (lastSessionsJson) {
      renderSessionList(JSON.parse(lastSessionsJson));
    }

    // Show terminal header
    var header = document.getElementById("terminal-header");
    header.style.display = "flex";
    document.getElementById("session-title").textContent = sessionName;
    setStatus("connecting", "Connecting...");

    // Hide empty state, show terminal
    document.getElementById("empty-state").style.display = "none";
    var termContainer = document.getElementById("terminal-container");
    termContainer.style.display = "block";
    termContainer.innerHTML = "";

    // Init xterm.js
    term = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: '"Menlo", "Courier New", monospace',
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

    // Delay fit to ensure container has dimensions
    requestAnimationFrame(function () { fitAddon.fit(); });

    // WebSocket
    var wsProto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(wsProto + "://" + location.host + "/terminal/ws/" + sessionName);

    ws.onopen = function () {
      ws.send(JSON.stringify({ type: "auth", token: token }));
    };

    ws.onmessage = function (event) {
      var msg = JSON.parse(event.data);
      if (msg.type === "connected") {
        setStatus("connected", "Connected");
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      } else if (msg.type === "output") {
        term.write(msg.data);
      } else if (msg.type === "error") {
        setStatus("disconnected", msg.message);
        term.write("\r\n\x1b[31m" + msg.message + "\x1b[0m\r\n");
      }
    };

    ws.onclose = function () {
      setStatus("disconnected", "Disconnected");
      scheduleReconnect(sessionName);
    };

    ws.onerror = function () {
      setStatus("disconnected", "Error");
    };

    // Input relay
    term.onData(function (data) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "input", data: data }));
      }
    });

    // Resize handling
    window.removeEventListener("resize", handleResize);
    window.addEventListener("resize", handleResize);

    term.onResize(function (size) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols: size.cols, rows: size.rows }));
      }
    });
  }

  function handleResize() {
    if (fitAddon) fitAddon.fit();
  }

  function setStatus(state, text) {
    var dot = document.getElementById("status-dot");
    var label = document.getElementById("status-text");
    if (dot) dot.className = "status-dot " + state;
    if (label) label.textContent = text;
  }

  function scheduleReconnect(sessionName) {
    if (reconnectTimeout) clearTimeout(reconnectTimeout);
    reconnectTimeout = setTimeout(function () {
      if (currentSession === sessionName) connectSession(sessionName);
    }, 3000);
  }
})();
