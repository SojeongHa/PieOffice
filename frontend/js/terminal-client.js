// frontend/js/terminal-client.js
// Terminal client — connects to ttyd instances managed by the terminal server

(function () {
  "use strict";

  var SYNC_INTERVAL = 5000;

  var token = "";
  var currentSession = null;
  var syncTimer = null;
  var lastSessionsJson = "";
  var currentTtydPort = null;

  // ── Auto-init: acquire session token (mTLS handles device auth) ───

  acquireSessionToken();

  function acquireSessionToken() {
    fetch(location.origin + "/session-token", { method: "POST" })
      .then(function (r) {
        if (!r.ok) {
          showError("Device not authorized. Install client certificate.");
          return null;
        }
        return r.json();
      })
      .then(function (data) {
        if (!data) return;
        token = data.token;
        fetchSessionsAndShow();
      })
      .catch(function () {
        showError("Connection failed. Is the server running?");
      });
  }

  function showError(msg) {
    var el = document.getElementById("auth-error");
    if (el) el.textContent = msg;
  }

  // ── Session List (auto-sync) ──────────────────────────

  function fetchSessions() {
    return fetch(location.origin + "/sessions", {
      headers: { Authorization: "Bearer " + token },
    }).then(function (r) {
      if (r.status === 401) {
        acquireSessionToken();
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
        showError("Connection failed");
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

  // ── Terminal Connection (via ttyd) ─────────────────────

  function connectSession(sessionName) {
    // Disconnect previous
    if (currentSession && currentSession !== sessionName) {
      doDisconnect(currentSession);
    }
    currentSession = sessionName;

    if (lastSessionsJson) {
      renderSessionList(JSON.parse(lastSessionsJson));
    }

    var header = document.getElementById("terminal-header");
    header.style.display = "flex";
    document.getElementById("session-title").textContent = sessionName;
    setStatus("connecting", "Connecting...");

    document.getElementById("empty-state").style.display = "none";
    document.getElementById("quick-actions").style.display = "flex";

    // Ask server to start ttyd for this session
    fetch(location.origin + "/connect/" + sessionName, {
      method: "POST",
      headers: { Authorization: "Bearer " + token },
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          setStatus("disconnected", data.error);
          return;
        }
        currentTtydPort = data.port;
        // Load ttyd in iframe — ttyd serves its own xterm.js
        var container = document.getElementById("terminal-container");
        container.style.display = "block";
        container.innerHTML = "";
        var iframe = document.createElement("iframe");
        iframe.id = "ttyd-frame";
        iframe.src = "http://127.0.0.1:" + data.port;
        iframe.style.cssText = "width:100%;height:100%;border:none;";
        container.appendChild(iframe);
        setStatus("connected", "Connected");
      })
      .catch(function () {
        setStatus("disconnected", "Connection failed");
      });
  }

  // ── Disconnect ─────────────────────────────────────────

  function doDisconnect(sessionName) {
    fetch(location.origin + "/disconnect/" + sessionName, {
      method: "POST",
      headers: { Authorization: "Bearer " + token },
    }).catch(function () {});
    currentTtydPort = null;
  }

  window.disconnectSession = function () {
    if (currentSession) {
      doDisconnect(currentSession);
    }
    currentSession = null;

    document.getElementById("terminal-header").style.display = "none";
    document.getElementById("terminal-container").style.display = "none";
    document.getElementById("terminal-container").innerHTML = "";
    document.getElementById("quick-actions").style.display = "none";
    document.getElementById("empty-state").style.display = "flex";
    document.getElementById("main-layout").style.height = "";

    if (lastSessionsJson) {
      renderSessionList(JSON.parse(lastSessionsJson));
    }
  };

  // ── Quick Actions ───────────────────────────────────────

  window.sendQuick = function (data) {
    // Send keystrokes to ttyd via its iframe
    var iframe = document.getElementById("ttyd-frame");
    if (iframe && iframe.contentWindow) {
      // ttyd uses its own WebSocket; we can post a message or
      // directly interact. Simplest: focus iframe and use keyboard events.
      iframe.focus();
      // For quick actions, use tmux send-keys as fallback
      fetch(location.origin + "/send-keys/" + currentSession, {
        method: "POST",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ keys: data }),
      }).catch(function () {});
    }
  };

  window.scrollBottom = function () {
    var iframe = document.getElementById("ttyd-frame");
    if (iframe) iframe.focus();
  };

  function setStatus(state, text) {
    var dot = document.getElementById("status-dot");
    var label = document.getElementById("status-text");
    if (dot) dot.className = "status-dot " + state;
    if (label) label.textContent = text;
  }
})();
