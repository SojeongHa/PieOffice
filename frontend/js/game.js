/**
 * Pie Office — Main Game Scene
 *
 * Boots Phaser 3, loads the tilemap and character spritesheets, wires up
 * pathfinding, agent management, UI, and SSE event streaming.
 *
 * Depends on (loaded before this script):
 *   - Phaser 3        (global)
 *   - EasyStar.js     (global)
 *   - CONFIG          (config.js)
 *   - I18N            (i18n.js)
 *   - SSEClient       (sse.js)
 *   - Pathfinder      (pathfinding.js)
 *   - AgentManager    (agents.js)
 *   - UIManager       (ui.js)
 */

class OfficeScene extends Phaser.Scene {
  constructor() {
    super({ key: "OfficeScene" });

    /** @type {Pathfinder} */
    this.pathfinder = null;
    /** @type {AgentManager} */
    this.agentManager = null;
    /** @type {UIManager} */
    this.ui = null;
    /** @type {SSEClient} */
    this.sse = null;
    /** @type {object} Parsed theme config.json */
    this.themeConfig = null;
    /** @type {object} Parsed sprites.json */
    this.spritesConfig = null;
  }

  // ── Preload ──────────────────────────────────────────────────────

  preload() {
    // Tileset image and tilemap JSON
    this.load.image("tiles", "/theme/tileset.png");
    this.load.tilemapTiledJSON("map", "/theme/tilemap.json");

    // Fountain animated sprite (96x96 per frame, 8 frames)
    this.load.spritesheet("fountain", "/theme/fountain.png", {
      frameWidth: 96,
      frameHeight: 96,
    });

    // Window background image (season + time of day)
    const { season, time } = this._getSeasonTime();
    this._windowBgKey = `window_${season}_${time}`;
    this.load.image(this._windowBgKey, `/theme/background/windows/window_${season}_${time}.png`);

    // Load sprites config so we know which character sheets to load.
    // Phaser's JSON loader makes it available via this.cache.json.
    this.load.json("sprites-config", "/theme/characters/sprites.json");

    // We need to wait for sprites.json before loading character sheets,
    // so we queue a second load pass in a "filecomplete" callback.
    this.load.once("filecomplete-json-sprites-config", () => {
      const config = this.cache.json.get("sprites-config");
      if (!config || !config.characters) return;

      this.spritesConfig = config;

      for (const [key, charDef] of Object.entries(config.characters)) {
        this.load.spritesheet(key, `/theme/characters/${charDef.file}`, {
          frameWidth: config.frameWidth,
          frameHeight: config.frameHeight,
        });
      }
    });

    // Alert indicator sprites (2-frame spritesheets, 64x64 per frame)
    this.load.spritesheet("obj_alert_exclamation", "/theme/objects/alert_exclamation.png", {
      frameWidth: 64, frameHeight: 64,
    });
    this.load.spritesheet("obj_alert_question", "/theme/objects/alert_question.png", {
      frameWidth: 64, frameHeight: 64,
    });
  }

  // ── Create ───────────────────────────────────────────────────────

  async create() {
    // ── Sprites config (may already be cached from preload) ──────
    if (!this.spritesConfig) {
      this.spritesConfig = this.cache.json.get("sprites-config");
    }

    // ── Tilemap setup ────────────────────────────────────────────
    this.map = this.make.tilemap({ key: "map" });
    const tileset = this.map.addTilesetImage("tileset", "tiles");

    // Create layers in order (bottom to top).  Names must match
    // the layer names exported from Tiled.
    this.map.createLayer("Floor", tileset);
    const wallLayer = this.map.createLayer("Walls", tileset);
    this.map.createLayer("Furniture", tileset);
    const furnitureCollisionLayer = this.map.createLayer(
      "FurnitureCollision",
      tileset,
    );

    // Enable collision on the two blocking layers
    if (wallLayer) {
      wallLayer.setCollisionByProperty({ collides: true });
    }
    if (furnitureCollisionLayer) {
      furnitureCollisionLayer.setCollisionByProperty({ collides: true });
      furnitureCollisionLayer.setVisible(false);
    }

    // ── Window background (behind tile layers) ──────────────────
    if (this.textures.exists(this._windowBgKey)) {
      this._windowBg = this.add.image(0, CONFIG.WINDOW_BG_Y, this._windowBgKey);
      this._windowBg.setOrigin(0, 0);
      this._windowBg.setDepth(-1);
    }

    // Check every hour if the background needs to change
    this.time.addEvent({
      delay: 60 * 60 * 1000,
      loop: true,
      callback: () => this._refreshWindowBg(),
    });

    // ── Pathfinding ──────────────────────────────────────────────
    const collisionLayers = [wallLayer, furnitureCollisionLayer].filter(
      Boolean,
    );
    this.pathfinder = new Pathfinder(this.map, collisionLayers);

    // ── Character animations ─────────────────────────────────────
    this._setupAnimations();

    // ── Fountain animation ─────────────────────────────────────
    this.anims.create({
      key: "fountain_splash",
      frames: this.anims.generateFrameNumbers("fountain", { start: 0, end: 1 }),
      frameRate: 3,
      repeat: -1,
    });

    // ── Theme config (fetched at runtime, not via Phaser loader) ─
    try {
      const resp = await fetch("/theme/config.json");
      this.themeConfig = await resp.json();

      // ── Fountain sprite ────────────────────────────────────────
      const fountainPos = this.themeConfig.fountain_position || { x: 8, y: 8 };
      const fts = CONFIG.TILE_SIZE;
      const fountain = this.add.sprite(
        fountainPos.x * fts + fts / 2,
        fountainPos.y * fts + fts / 2,
        "fountain",
      );
      fountain.play("fountain_splash");
      fountain.setDepth(50);
    } catch (err) {
      console.error("[Game] Failed to load theme config:", err);
      this.themeConfig = { agent_map: {}, rooms: {}, objects: [] };
    }

    // ── Room areas (optional) ────────────────────────────────────
    try {
      const raResp = await fetch("/theme/room_areas.json");
      if (raResp.ok) this.themeConfig._roomAreas = await raResp.json();
    } catch { /* room_areas.json not found, use spawn fallback */ }

    // ── Manager instances ────────────────────────────────────────
    this.agentManager = new AgentManager(
      this,
      this.pathfinder,
      this.themeConfig,
    );
    this.ui = new UIManager(this.agentManager);
    this.ui.applyI18n();

    // ── Instance alert indicators ─────────────────────────────────
    this.instanceAlerts = new InstanceAlertManager(this, this.themeConfig);

    // ── SSE connection ───────────────────────────────────────────
    this._setupSSE();

    // ── Spawn resident agents ─────────────────────────────────────
    this._spawnResidents();

    // ── Place static objects ───────────────────────────────────────
    this._loadAndPlaceObjects();

    // ── Robot vacuum ─────────────────────────────────────────────
    this._initRobotVacuum();

    // ── Load initial state ───────────────────────────────────────
    this._loadInitialState();
  }

  // ── Update (per frame) ───────────────────────────────────────────

  update(time, delta) {
    if (this.agentManager) {
      this.agentManager.update(time, delta);
    }
    if (this._vacuum) {
      this._updateRobotVacuum(time, delta);
    }
  }

  // ── Private: Animation setup ─────────────────────────────────────

  /**
   * Register Phaser animations for every character in sprites.json.
   *
   * For characters with `anims: "same_as:leader"` we re-use the leader's
   * animation frame definitions but bind them to the character's own
   * spritesheet key.
   */
  _setupAnimations() {
    const config = this.spritesConfig;
    if (!config || !config.characters) return;

    const chars = config.characters;

    // First pass: find the leader's raw animation definitions so
    // "same_as:leader" entries can copy them.
    const leaderAnims =
      chars.leader && typeof chars.leader.anims === "object"
        ? chars.leader.anims
        : {};

    for (const [charKey, charDef] of Object.entries(chars)) {
      // Resolve animation definitions
      let animDefs;
      if (
        typeof charDef.anims === "string" &&
        charDef.anims.startsWith("same_as:")
      ) {
        const refKey = charDef.anims.split(":")[1];
        const refChar = chars[refKey];
        animDefs =
          refChar && typeof refChar.anims === "object"
            ? refChar.anims
            : leaderAnims;
      } else if (typeof charDef.anims === "object") {
        animDefs = charDef.anims;
      } else {
        continue;
      }

      // Create a Phaser animation for each defined anim
      for (const [animName, animConfig] of Object.entries(animDefs)) {
        const key = `${charKey}_${animName}`;

        // Skip if already registered (e.g. hot-reload)
        if (this.anims.exists(key)) continue;

        this.anims.create({
          key,
          frames: this.anims.generateFrameNumbers(charKey, {
            start: animConfig.start,
            end: animConfig.end,
          }),
          frameRate: animConfig.frameRate || 8,
          repeat: -1,
        });
      }
    }
  }

  // ── Private: Season / time of day ────────────────────────────────

  /**
   * Determine the current season and time-of-day bucket based on
   * the local clock. Used to pick the correct window background.
   */
  _getSeasonTime() {
    const now = new Date();
    const month = now.getMonth(); // 0-11
    const hour = now.getHours();  // 0-23

    let season;
    if (month >= 2 && month <= 4) season = 'spring';
    else if (month >= 5 && month <= 7) season = 'summer';
    else if (month >= 8 && month <= 10) season = 'autumn';
    else season = 'winter';

    let time;
    if (hour >= 5 && hour < 9) time = 'dawn';
    else if (hour >= 9 && hour < 17) time = 'day';
    else if (hour >= 17 && hour < 21) time = 'evening';
    else time = 'night';

    return { season, time };
  }

  // ── Private: Refresh window background on time change ────────────

  _refreshWindowBg() {
    const { season, time } = this._getSeasonTime();
    const newKey = `window_${season}_${time}`;
    if (newKey === this._windowBgKey) return;

    this._windowBgKey = newKey;
    const url = `/theme/background/windows/${newKey}.png`;

    this.load.image(newKey, url);
    this.load.once("complete", () => {
      if (this._windowBg) {
        this._windowBg.setTexture(newKey);
      }
    });
    this.load.start();
  }

  // ── Private: SSE wiring ──────────────────────────────────────────

  _setupSSE() {
    this.sse = new SSEClient(CONFIG.SSE_URL);

    // ── agent_join ───────────────────────────────────────────────
    this.sse.on("agent_join", (data) => {
      const agentId = data.agent_id || data.id;
      const agent = this.agentManager.getOrCreate(agentId, data);
      const room = data.room || (this.themeConfig.state_room_map || {})[data.state] || "break";
      this.agentManager.moveTo(agentId, room);
      this.agentManager.showBubble(
        agentId,
        I18N.t("bubble.arrived", { name: agent.displayName }),
      );
      this.ui.addLogEntry(I18N.t("log.join", { name: agent.displayName }));
      this.ui.updateAgentList();
    });

    // ── agent_update ─────────────────────────────────────────────
    this.sse.on("agent_update", (data) => {
      const agentId = data.agent_id || data.id;
      const agent = this.agentManager.getOrCreate(agentId, data);
      agent.state = data.state || agent.state;
      agent.lastUpdate = Date.now();

      if (data.state === "permission") {
        // Stay in place, show persistent bubble until next state change
        const detail = data.detail || "permission check";
        this.agentManager.showBubble(agentId, detail, 0);
      } else if (data.state === "lingering") {
        // Stay in current room, play idle animation (no movement)
        this.agentManager._playIdleInPlace(agentId);
      } else if (data.state === "idle") {
        this.agentManager.moveToIdle(agentId);
      } else {
        const room = (this.themeConfig.state_room_map || {})[data.state] || agent.room || "break";
        this.agentManager.moveTo(agentId, room, data.state);
      }

      // Show dialogue bubble (skip for permission/lingering)
      if (data.state !== "permission" && data.state !== "lingering") {
        const { text, duration } = Dialogue.forStateChange(
          data.state || "idle",
          data.detail,
        );
        this.agentManager.showBubble(agentId, text, duration);
      }

      this.ui.addLogEntry(
        I18N.t("log.update", {
          name: agent.displayName,
          state: data.state || "",
        }),
      );
      this.ui.updateAgentList();
    });

    // ── agent_leave ──────────────────────────────────────────────
    this.sse.on("agent_leave", (data) => {
      const agentId = data.agent_id || data.id;
      const agent = this.agentManager.agents.get(agentId);
      const name = agent ? agent.displayName : agentId;

      // Resident agents don't leave — just return to idle
      const mapping = this.themeConfig.agent_map?.[agentId];
      if (mapping && mapping.resident) {
        this.agentManager.moveToIdle(agentId);
        return;
      }

      this.agentManager.showBubble(agentId, I18N.t("bubble.leaving", { name }));
      this.ui.addLogEntry(I18N.t("log.leave", { name }));

      // Delay removal so the leaving bubble is visible
      this.time.delayedCall(2000, () => {
        this.agentManager.remove(agentId);
        this.ui.updateAgentList();
      });
    });

    // ── agent_chat ───────────────────────────────────────────────
    this.sse.on("agent_chat", (data) => {
      const sender = data.sender || data.agent_id || data.id;
      const receiver = data.receiver;
      const message = data.message || data.summary || "";

      this.agentManager.showBubble(sender, message, 5000);
      if (receiver && receiver !== "all") {
        this.agentManager.showBubble(receiver, "...", 2000);
      }
      this.ui.addLogEntry(
        I18N.t("log.chat", { sender, receiver: receiver || "all", message }),
      );
    });

    // ── agent_gather (team conversations — sender walks to receiver) ─
    this.sse.on("agent_gather", (data) => {
      const sourceId = data.source_id;
      const targetId = data.target_id;
      if (sourceId && targetId) {
        this.agentManager.gatherTo(sourceId, targetId);
      }
    });

    // ── instance_alert ─────────────────────────────────────────────
    this.sse.on("instance_alert", (data) => {
      if (this.instanceAlerts) {
        this.instanceAlerts.showAlert(data);
      }
      const project = (data.cwd || "").split("/").pop() || "unknown";
      const type = data.alert_type === "permission_prompt" ? "permission" : "input";
      this.ui.addLogEntry(`${project}: ${type} needed`);
    });

    // ── instance_alert_clear ───────────────────────────────────────
    this.sse.on("instance_alert_clear", (data) => {
      if (this.instanceAlerts) {
        this.instanceAlerts.clearAlert(data.session_id);
      }
    });

    // ── instance_slot_release ──────────────────────────────────────
    this.sse.on("instance_slot_release", (data) => {
      if (this.instanceAlerts) {
        this.instanceAlerts.releaseSlot(data.session_id);
      }
    });

    // After SSE reconnect (sleep wake), ack idle alerts after 10s
    let ackTimer = null;
    let hasConnectedOnce = false;
    this.sse.on("_open", () => {
      if (!hasConnectedOnce) {
        hasConnectedOnce = true;
        return;
      }
      if (ackTimer) clearTimeout(ackTimer);
      ackTimer = setTimeout(() => {
        fetch("/alerts/ack", { method: "POST" }).catch(() => {});
      }, 10000);
    });

    this.sse.connect();
  }

  // ── Private: Robot Vacuum ───────────────────────────────────────

  _initRobotVacuum() {
    const cfg = this.themeConfig.robot_vacuum;
    if (!cfg) return;

    const key = "obj_robot_vacuum";
    const ts = CONFIG.TILE_SIZE;

    // Load spritesheet if not already loaded by objects
    if (!this.textures.exists(key)) {
      this.load.spritesheet(key, `/theme/objects/${cfg.sprite}.png`, {
        frameWidth: cfg.frameWidth || 64,
        frameHeight: cfg.frameHeight || 64,
      });
      this.load.once("complete", () => this._spawnRobotVacuum(cfg));
      this.load.start();
    } else {
      this._spawnRobotVacuum(cfg);
    }
  }

  _spawnRobotVacuum(cfg) {
    const key = "obj_robot_vacuum";
    const ts = CONFIG.TILE_SIZE;
    const startX = cfg.startTile.x;
    const startY = cfg.startTile.y;

    // Create animation
    const animKey = "anim_robot_vacuum";
    if (!this.anims.exists(animKey)) {
      this.anims.create({
        key: animKey,
        frames: this.anims.generateFrameNumbers(key, { start: 0, end: (cfg.frames || 4) - 1 }),
        frameRate: cfg.frameRate || 4,
        repeat: -1,
      });
    }

    // Create sprite at tile center
    const sprite = this.add.sprite(
      startX * ts + ts / 2,
      startY * ts + ts / 2,
      key,
    );
    sprite.setDepth(25);
    sprite.play(animKey);
    // Directions: right=0, down=1, left=2, up=3
    const dirs = [
      { dx: 1, dy: 0 },
      { dx: 0, dy: 1 },
      { dx: -1, dy: 0 },
      { dx: 0, dy: -1 },
    ];

    this._vacuum = {
      sprite,
      tileX: startX,
      tileY: startY,
      dirIndex: 0, // facing right
      paused: false,
      lastTick: 0,
      interval: cfg.turnInterval || 2000,
      dirs,
      moving: false,
      moveFrom: null,
      moveTo: null,
      moveProgress: 0,
      visited: new Map(), // "x,y" -> visit count
    };
    this._vacuum.visited.set(`${startX},${startY}`, 1);
    this._vacuum.visitedResetAt = Date.now();

    // Click to toggle pause
    this.input.on("pointerdown", (pointer) => {
      if (!this._vacuum) return;
      const v = this._vacuum;
      const dist = Phaser.Math.Distance.Between(
        pointer.worldX, pointer.worldY, v.sprite.x, v.sprite.y,
      );
      if (dist > 40) return;
      v.paused = !v.paused;
      if (v.paused) {
        v.sprite.anims.pause();
      } else {
        v.sprite.anims.resume();
        v.lastTick = this.time.now;
      }
    });
  }

  _updateRobotVacuum(time, delta) {
    const v = this._vacuum;
    if (!v || v.paused) return;
    const ts = CONFIG.TILE_SIZE;

    // Smooth movement animation
    if (v.moving) {
      v.moveProgress += delta / 1000; // ~1 second to cross a tile (frame-rate independent)
      if (v.moveProgress >= 1) {
        v.moveProgress = 1;
        v.moving = false;
        v.tileX = v.moveTo.x;
        v.tileY = v.moveTo.y;
        v.sprite.setPosition(v.tileX * ts + ts / 2, v.tileY * ts + ts / 2);
      } else {
        const fx = v.moveFrom.x * ts + ts / 2;
        const fy = v.moveFrom.y * ts + ts / 2;
        const tx = v.moveTo.x * ts + ts / 2;
        const ty = v.moveTo.y * ts + ts / 2;
        v.sprite.setPosition(
          fx + (tx - fx) * v.moveProgress,
          fy + (ty - fy) * v.moveProgress,
        );
      }
      return;
    }

    // Turn-based tick
    if (time - v.lastTick < v.interval) return;
    v.lastTick = time;

    // Reset visited map every 2 hours (wall clock, not scene time)
    const wallNow = Date.now();
    if (wallNow - v.visitedResetAt > 2 * 60 * 60 * 1000) {
      v.visited.clear();
      v.visitedResetAt = wallNow;
    }

    // Find all passable neighbors and pick the least-visited one
    const candidates = [];
    for (let di = 0; di < 4; di++) {
      const d = v.dirs[di];
      const nx = v.tileX + d.dx;
      const ny = v.tileY + d.dy;
      if (this._vacuumCanMove(nx, ny)) {
        const visits = v.visited.get(`${nx},${ny}`) || 0;
        candidates.push({ di, nx, ny, visits });
      }
    }

    if (candidates.length > 0) {
      // Fisher-Yates shuffle first, then stable sort by visits (unbiased tie-breaking)
      for (let i = candidates.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [candidates[i], candidates[j]] = [candidates[j], candidates[i]];
      }
      candidates.sort((a, b) => a.visits - b.visits);
      const best = candidates[0];

      // If already facing that direction, move. Otherwise rotate toward it.
      if (best.di === v.dirIndex) {
        v.moving = true;
        v.moveFrom = { x: v.tileX, y: v.tileY };
        v.moveTo = { x: best.nx, y: best.ny };
        v.moveProgress = 0;
        const key = `${best.nx},${best.ny}`;
        v.visited.set(key, (v.visited.get(key) || 0) + 1);
      } else {
        // Rotate 90 degrees toward target direction
        const diff = (best.di - v.dirIndex + 4) % 4;
        v.dirIndex = (v.dirIndex + (diff === 3 ? 3 : 1)) % 4;
      }
    } else {
      // No passable neighbor, just spin
      v.dirIndex = (v.dirIndex + 1) % 4;
    }
  }

  _vacuumCanMove(tx, ty) {
    // Out of bounds
    if (tx < 0 || tx >= this.map.width || ty < 0 || ty >= this.map.height) return false;
    // Collision tile
    if (!this.pathfinder.isWalkable(tx, ty)) return false;
    // Agent occupying that tile
    const ts = CONFIG.TILE_SIZE;
    if (this.agentManager) {
      for (const [, agent] of this.agentManager.agents) {
        const ax = Math.floor(agent.sprite.x / ts);
        const ay = Math.floor(agent.sprite.y / ts);
        if (ax === tx && ay === ty) return false;
      }
    }
    return true;
  }

  // ── Private: Static object sprites ──────────────────────────────

  _loadAndPlaceObjects() {
    const objects = this.themeConfig.objects || [];
    if (objects.length === 0) return;

    let loadCount = 0;
    for (const obj of objects) {
      const key = `obj_${obj.sprite}`;
      if (this.textures.exists(key)) continue;
      if (obj.anim) {
        this.load.spritesheet(key, `/theme/objects/${obj.sprite}.png`, {
          frameWidth: obj.anim.frameWidth,
          frameHeight: obj.anim.frameHeight,
        });
      } else {
        this.load.image(key, `/theme/objects/${obj.sprite}.png`);
      }
      loadCount++;
    }

    if (loadCount > 0) {
      this.load.once("complete", () => {
        this._placeObjects(objects);
      });
      this.load.start();
    } else {
      this._placeObjects(objects);
    }
  }

  _placeObjects(objects) {
    const ts = CONFIG.TILE_SIZE;
    for (const obj of objects) {
      const key = `obj_${obj.sprite}`;
      if (!this.textures.exists(key)) continue;

      const x = obj.x * ts;
      const y = obj.y * ts;

      if (obj.anim) {
        const animKey = `anim_${obj.sprite}`;
        if (!this.anims.exists(animKey)) {
          this.anims.create({
            key: animKey,
            frames: this.anims.generateFrameNumbers(key, {
              start: 0,
              end: obj.anim.frames - 1,
            }),
            frameRate: obj.anim.frameRate || 4,
            repeat: -1,
          });
        }
        const sprite = this.add.sprite(x, y, key);
        sprite.setOrigin(0, 0);
        sprite.setDepth(obj.depth || 50);
        sprite.play(animKey);
      } else {
        const sprite = this.add.image(x, y, key);
        sprite.setOrigin(0, 0);
        sprite.setDepth(obj.depth || 50);
      }
    }
  }

  // ── Private: Resident agents ─────────────────────────────────────

  /**
   * Spawn agents marked as resident in config.json agent_map.
   * They stay in the office permanently.
   */
  _spawnResidents() {
    const agentMap = this.themeConfig.agent_map || {};
    for (const [id, mapping] of Object.entries(agentMap)) {
      if (!mapping.resident) continue;
      const agent = this.agentManager.getOrCreate(id, { name: mapping.displayName, state: "idle" });
      // Place at idle position directly (no walking on initial load)
      if (mapping.idlePosition) {
        const ts = CONFIG.TILE_SIZE;
        const wx = mapping.idlePosition.x * ts + ts / 2;
        const wy = mapping.idlePosition.y * ts + ts / 2;
        agent.sprite.setPosition(wx, wy);
        this.agentManager._syncAttachments(agent);
      }
    }
    this.ui.updateAgentList();
  }

  // ── Private: Initial state ───────────────────────────────────────

  /**
   * Fetch the current state snapshot from the backend and create agents
   * for any that already exist.
   */
  async _loadInitialState() {
    try {
      const resp = await fetch(CONFIG.STATE_URL);
      if (!resp.ok) {
        console.warn("[Game] State endpoint returned", resp.status);
        return;
      }

      const state = await resp.json();

      // state may be { agents: { id: { name, state, … }, … } }
      // or an array, or a flat object — handle the common shapes.
      const agents = state.agents || state;

      if (agents && typeof agents === "object") {
        const now = Date.now() / 1000; // seconds
        for (const [id, data] of Object.entries(agents)) {
          if (!data || typeof data !== "object") continue;

          // Skip stale entries (>30s old) — resident agents are
          // already spawned by _spawnResidents at their idle positions
          const age = now - (data.updated_at || 0);
          if (age > 30) continue;

          const agentData = { ...data, agent_id: id };
          this.agentManager.getOrCreate(id, agentData);
          const room =
            (this.themeConfig.state_room_map || {})[data.state] || data.room || "break";
          this.agentManager.moveTo(id, room, data.state);
        }
        this.ui.updateAgentList();
      }

      // Load instance alerts
      if (state.instances && this.instanceAlerts) {
        this.instanceAlerts.loadInitial(state.instances);
      }
    } catch (err) {
      console.warn("[Game] Could not load initial state:", err);
    }
  }
}

// ── Boot sequence ────────────────────────────────────────────────────

(async function () {
  await I18N.init();

  new Phaser.Game({
    type: Phaser.AUTO,
    width: CONFIG.CANVAS_WIDTH,
    height: CONFIG.CANVAS_HEIGHT,
    parent: "game-container",
    pixelArt: true,
    backgroundColor: "#1a1a2e",
    scale: {
      mode: Phaser.Scale.FIT,
      autoCenter: Phaser.Scale.CENTER_BOTH,
    },
    scene: OfficeScene,
  });
})();
