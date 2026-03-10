/**
 * AgentManager — Creates, moves, animates, and removes agent character sprites
 * on the Phaser scene.
 *
 * Each agent is an RPG-style character that walks between rooms via A*
 * pathfinding.  Sprites are looked up from the theme config's agent_map,
 * and a name tag + speech bubble float above them.
 *
 * Depends on:
 *   - CONFIG          (from config.js)   — TILE_SIZE, WALK_SPEED
 *   - Pathfinder      (from pathfinding.js) — findPath()
 *   - Theme config    (config.json)      — rooms, agent_map
 */

/* exported AgentManager */
class AgentManager {
    /**
     * @param {Phaser.Scene} scene            - The active Phaser scene.
     * @param {Pathfinder}   pathfinder       - A* pathfinder instance.
     * @param {object}       themeConfig      - Parsed theme/default/config.json.
     */
    constructor(scene, pathfinder, themeConfig) {
        this.scene = scene;
        this.pathfinder = pathfinder;
        this.config = themeConfig;
        /** @type {Map<string, object>} agentId -> agent object */
        this.agents = new Map();
        /** @type {Map<string, string>} "tx,ty" -> room key (prebuilt lookup) */
        this._roomTileLookup = this._buildRoomTileLookup();
    }

    /**
     * Build a reverse lookup map from tile coords to room key for O(1) access.
     * @returns {Map<string, string>}
     * @private
     */
    _buildRoomTileLookup() {
        const lookup = new Map();
        const areas = this.config._roomAreas;
        if (!areas) return lookup;
        for (const [room, tiles] of Object.entries(areas)) {
            for (const [tx, ty] of tiles) {
                lookup.set(`${tx},${ty}`, room);
            }
        }
        return lookup;
    }

    // ── Public API ──────────────────────────────────────────────────

    /**
     * Return an existing agent or create a new one.
     *
     * @param {string} agentId  - Unique identifier (e.g. hook agent name).
     * @param {object} data     - Upstream state payload ({ name, state, room, … }).
     * @returns {object} The agent object stored in the Map.
     */
    getOrCreate(agentId, data) {
        if (this.agents.has(agentId)) {
            return this.agents.get(agentId);
        }

        // ── Resolve sprite key & display name from config agent_map ─
        // Lookup order: agentId → data.type → data.name → fallback robot
        const mapping = this.config.agent_map[agentId]
            || this.config.agent_map[data.type]
            || this.config.agent_map[data.name]
            || null;

        const spriteKey = mapping ? mapping.sprite : "robot";
        const displayName = mapping
            ? mapping.displayName
            : (data.name || agentId);

        // ── Determine spawn position ────────────────────────────────
        const room = data.room || "break";
        const spawn = this._roomSpawn(room);

        // ── Create Phaser sprite ────────────────────────────────────
        const sprite = this.scene.add.sprite(spawn.x, spawn.y, spriteKey);
        sprite.setScale(CONFIG.CHAR_SCALE || 1);
        sprite.setDepth(100);

        // Apply tint: config value for mapped agents, random color for fallback robot
        if (mapping && mapping.tint) {
            sprite.setTint(parseInt(mapping.tint));
        } else if (!mapping) {
            // Random vivid color for unmapped agents (Ditto style)
            const hue = Math.random() * 360;
            const h = hue / 60;
            const x = 1 - Math.abs(h % 2 - 1);
            let r, g, b;
            if (h < 1) { r = 1; g = x; b = 0; }
            else if (h < 2) { r = x; g = 1; b = 0; }
            else if (h < 3) { r = 0; g = 1; b = x; }
            else if (h < 4) { r = 0; g = x; b = 1; }
            else if (h < 5) { r = x; g = 0; b = 1; }
            else { r = 1; g = 0; b = x; }
            // Mix with white for pastel (0.5 saturation)
            r = Math.floor((r * 0.5 + 0.5) * 255);
            g = Math.floor((g * 0.5 + 0.5) * 255);
            b = Math.floor((b * 0.5 + 0.5) * 255);
            sprite.setTint((r << 16) | (g << 8) | b);
        }

        // ── Name tag (DOM overlay — immune to pixelArt scaling) ─
        const nameTag = document.createElement("div");
        nameTag.className = "agent-nametag";
        nameTag.textContent = displayName;
        const container = document.getElementById("game-container");
        container.appendChild(nameTag);

        // ── Play default idle animation ─────────────────────────────
        const idleKey = `${spriteKey}_idle-down`;
        if (this.scene.anims.exists(idleKey)) {
            sprite.play(idleKey);
        }

        // ── Compose agent object ────────────────────────────────────
        const agent = {
            id: agentId,
            sprite,
            nameTag,
            displayName,
            spriteKey,
            state: data.state || "idle",
            room,
            moving: false,
            path: null,
            pathIndex: 0,
            bubble: null,
            wanderTimer: null,
            lastUpdate: Date.now(),
        };

        this.agents.set(agentId, agent);
        this._scheduleWander(agent);
        return agent;
    }

    /**
     * Move an agent to its configured idle position (from agent_map.idlePosition).
     * Falls back to the "break" room if no idle position is set.
     *
     * @param {string} agentId - Agent identifier.
     */
    async moveToIdle(agentId) {
        const agent = this.agents.get(agentId);
        if (!agent) return;

        const mapping = this.config.agent_map[agentId] || {};
        const ts = CONFIG.TILE_SIZE;
        const occupied = this._getOccupiedTiles();
        // Exclude self from occupied check
        const selfTX = Math.floor(agent.sprite.x / ts);
        const selfTY = Math.floor(agent.sprite.y / ts);
        occupied.delete(`${selfTX},${selfTY}`);

        if (mapping.idlePosition) {
            // Pick a random walkable tile near idlePosition (within 3-tile radius)
            const cx = mapping.idlePosition.x;
            const cy = mapping.idlePosition.y;
            const target = this._findRandomNearby(cx, cy, 3, occupied)
                || { x: cx * ts + ts / 2, y: cy * ts + ts / 2 };

            const path = await this.pathfinder.findPath(
                agent.sprite.x, agent.sprite.y, target.x, target.y,
            );
            if (path && path.length >= 2) {
                agent.moving = true;
                agent.path = path;
                agent.pathIndex = 1;
                agent.state = "idle";
                return;
            }
            // Teleport if no path
            agent.sprite.setPosition(target.x, target.y);
            this._syncAttachments(agent);
        } else {
            await this.moveTo(agentId, "break", "idle");
            return;
        }
        agent.state = "idle";
        const dir = agent.lastDir || "down";
        this._playAnim(agent, `idle-${dir}`);
    }

    /**
     * Move an agent to the spawn point of the given room using A* pathfinding.
     *
     * If no walkable path is found (or path is too short), the agent is
     * teleported directly.
     *
     * @param {string} agentId  - Agent identifier.
     * @param {string} room     - Target room key (e.g. "manager", "work").
     * @param {string} [detail] - Optional detail string (stored on agent.state).
     */
    async moveTo(agentId, room, detail) {
        const agent = this.agents.get(agentId);
        if (!agent) return;

        agent.state = detail || room;
        agent.room = room;

        let target = this._roomSpawn(room);

        // Avoid stacking: if target tile is occupied, find adjacent empty
        const ts = CONFIG.TILE_SIZE;
        const targetTX = Math.floor(target.x / ts);
        const targetTY = Math.floor(target.y / ts);
        const occupied = this._getOccupiedTiles();
        const selfTX = Math.floor(agent.sprite.x / ts);
        const selfTY = Math.floor(agent.sprite.y / ts);
        occupied.delete(`${selfTX},${selfTY}`);

        if (occupied.has(`${targetTX},${targetTY}`)) {
            const alt = this._findAdjacentEmpty(targetTX, targetTY, occupied);
            if (alt) target = alt;
        }

        const path = await this.pathfinder.findPath(
            agent.sprite.x, agent.sprite.y,
            target.x, target.y,
        );

        if (!path || path.length < 2) {
            // Teleport when pathfinding yields no useful route
            agent.sprite.setPosition(target.x, target.y);
            this._syncAttachments(agent);
            this._playArrivalAnim(agent);
            return;
        }

        agent.moving = true;
        agent.path = path;
        agent.pathIndex = 1; // index 0 is current position
    }

    /**
     * Per-frame update — advances walking agents and keeps attachments in sync.
     * Call from Phaser Scene.update().
     *
     * @param {number} time  - Scene elapsed time (ms).
     * @param {number} delta - Time since last frame (ms).
     */
    update(time, delta) {
        const now = Date.now();
        const ts = CONFIG.TILE_SIZE;

        // Track tiles occupied this frame for overlap detection
        const tileAgents = new Map(); // "tx,ty" -> first agent

        for (const agent of this.agents.values()) {
            if (agent.moving) {
                this._walkStep(agent, delta);
            }
            this._syncAttachments(agent);

            // Client-side fallback: 30s hard timeout (server sweep handles normal cases)
            if (agent.state !== "idle" && agent.state !== "reporting"
                && agent.state !== "permission" && agent.state !== "lingering"
                && now - agent.lastUpdate > 30000) {
                agent.state = "idle";
                agent.lastUpdate = now;
                this.moveToIdle(agent.id);
            }

            // Overlap detection: nudge if sharing tile with another agent
            if (!agent.moving) {
                const tx = Math.floor(agent.sprite.x / ts);
                const ty = Math.floor(agent.sprite.y / ts);
                const key = `${tx},${ty}`;
                if (tileAgents.has(key)) {
                    if (!agent._nudging) {
                        this._nudgeApart(agent, tx, ty);
                    }
                } else {
                    tileAgents.set(key, agent);
                }
            }
        }
    }

    /**
     * Nudge an agent to a nearby empty walkable tile to resolve overlap.
     * @private
     */
    _nudgeApart(agent, fromTX, fromTY) {
        if (agent.moving || agent._nudging) return;
        const occupied = this._getOccupiedTiles();
        const alt = this._findAdjacentEmpty(fromTX, fromTY, occupied);
        if (!alt) return;

        agent._nudging = true;
        this.pathfinder.findPath(
            agent.sprite.x, agent.sprite.y, alt.x, alt.y,
        ).then((path) => {
            agent._nudging = false;
            if (!path || path.length < 2 || agent.moving) return;
            agent.moving = true;
            agent.path = path;
            agent.pathIndex = 1;
        });
    }

    /**
     * Display a short speech bubble above the agent's sprite.
     *
     * @param {string} agentId       - Agent identifier.
     * @param {string} text          - Message text (truncated to 30 chars).
     * @param {number} [duration=3000] - How long the bubble stays visible (ms).
     */
    showBubble(agentId, text, duration = 3000) {
        const agent = this.agents.get(agentId);
        if (!agent) return;

        // Destroy any existing bubble first
        if (agent.bubble) {
            agent.bubble.destroy();
            agent.bubble = null;
        }

        // Truncate long messages
        const display = text.length > 30 ? text.slice(0, 27) + "..." : text;

        const bubble = this.scene.add.text(
            agent.sprite.x,
            agent.sprite.y - 44 * (CONFIG.CHAR_SCALE || 1),
            display,
            {
                fontFamily: "'Press Start 2P', monospace",
                fontSize: "8px",
                color: "#ffffff",
                backgroundColor: "#333333",
                stroke: "#000000",
                strokeThickness: 2,
                padding: { x: 4, y: 3 },
            },
        );
        bubble.setOrigin(0.5, 1);
        bubble.setDepth(200);

        agent.bubble = bubble;

        // Auto-destroy after duration (0 = persistent, stays until replaced)
        if (duration > 0) {
            this.scene.time.delayedCall(duration, () => {
                if (agent.bubble === bubble) {
                    bubble.destroy();
                    agent.bubble = null;
                }
            });
        }
    }

    /**
     * Completely remove an agent — destroys sprite, name tag, and bubble.
     *
     * @param {string} agentId - Agent identifier.
     */
    remove(agentId) {
        const agent = this.agents.get(agentId);
        if (!agent) return;

        if (agent.wanderTimer) {
            agent.wanderTimer.remove(true);
        }
        agent.sprite.destroy();
        agent.nameTag.remove();
        if (agent.bubble) {
            agent.bubble.destroy();
        }
        this.agents.delete(agentId);
    }

    /**
     * Return all active agent objects as an array.
     *
     * @returns {object[]}
     */
    getAll() {
        return Array.from(this.agents.values());
    }

    // ── Private helpers ─────────────────────────────────────────────

    /**
     * Schedule the next random wander for an agent (7-20s).
     * @private
     */
    _scheduleWander(agent) {
        if (agent.wanderTimer) {
            agent.wanderTimer.remove(false);
        }
        const delay = 7000 + Math.random() * 13000;
        agent.wanderTimer = this.scene.time.delayedCall(delay, () => {
            this._tryWander(agent);
            this._scheduleWander(agent);
        });
    }

    /**
     * Try to wander the agent to a random nearby walkable tile (2-5 tiles away).
     * Stays within the agent's current room area if room_areas are defined.
     * @private
     */
    _tryWander(agent) {
        if (agent.moving || agent.state !== "idle") return;

        const ts = CONFIG.TILE_SIZE;
        const curTX = Math.floor(agent.sprite.x / ts);
        const curTY = Math.floor(agent.sprite.y / ts);

        // Collect occupied tiles from all other agents
        const occupied = this._getOccupiedTiles();
        occupied.delete(`${curTX},${curTY}`);

        // Determine which room the agent is in based on room_areas
        const room = this._getRoomForTile(curTX, curTY) || agent.room || "break";
        const areas = this.config._roomAreas;
        const roomTiles = areas && areas[room] ? areas[room] : null;

        if (roomTiles && roomTiles.length > 1) {
            // Pick a random walkable tile from the same room, 2+ tiles away
            const shuffled = roomTiles.slice();
            for (let i = shuffled.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
            }
            for (const [tx, ty] of shuffled) {
                const dist = Math.abs(tx - curTX) + Math.abs(ty - curTY);
                if (dist < 2 || dist > 6) continue;
                if (occupied.has(`${tx},${ty}`)) continue;
                if (!this.pathfinder.isWalkable(tx, ty)) continue;

                const worldX = tx * ts + ts / 2;
                const worldY = ty * ts + ts / 2;
                this.pathfinder.findPath(
                    agent.sprite.x, agent.sprite.y, worldX, worldY,
                ).then((path) => {
                    if (!path || path.length < 2 || agent.moving) return;
                    agent.moving = true;
                    agent.path = path;
                    agent.pathIndex = 1;
                });
                return;
            }
        }

        // Fallback: move 1 tile in a random cardinal direction
        const dirs = [
            { dx: 0, dy: -1 }, { dx: 0, dy: 1 },
            { dx: -1, dy: 0 }, { dx: 1, dy: 0 },
        ];
        for (let i = dirs.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [dirs[i], dirs[j]] = [dirs[j], dirs[i]];
        }
        for (const d of dirs) {
            const nx = curTX + d.dx;
            const ny = curTY + d.dy;
            if (occupied.has(`${nx},${ny}`)) continue;
            if (!this.pathfinder.isWalkable(nx, ny)) continue;

            const worldX = nx * ts + ts / 2;
            const worldY = ny * ts + ts / 2;
            this.pathfinder.findPath(
                agent.sprite.x, agent.sprite.y, worldX, worldY,
            ).then((path) => {
                if (!path || path.length < 2 || agent.moving) return;
                agent.moving = true;
                agent.path = path;
                agent.pathIndex = 1;
            });
            return;
        }
    }

    /**
     * Advance the agent one step along its A* path.
     *
     * Determines walk direction for the correct animation, moves toward the
     * current waypoint, and advances the path index when close enough.
     *
     * @param {object} agent - Agent object.
     * @param {number} delta - Frame delta in ms.
     * @private
     */
    _walkStep(agent, delta) {
        const target = agent.path[agent.pathIndex];
        const dx = target.x - agent.sprite.x;
        const dy = target.y - agent.sprite.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        // Pixels to move this frame
        const step = CONFIG.WALK_SPEED * (delta / 1000);

        if (dist <= step) {
            // Snap to waypoint and advance
            agent.sprite.setPosition(target.x, target.y);
            agent.pathIndex++;

            if (agent.pathIndex >= agent.path.length) {
                // Path complete
                agent.moving = false;
                agent.path = null;
                agent.pathIndex = 0;
                this._playArrivalAnim(agent);
                return;
            }
        } else {
            // Move toward waypoint
            const nx = dx / dist;
            const ny = dy / dist;
            agent.sprite.x += nx * step;
            agent.sprite.y += ny * step;
        }

        // Pick directional walk animation based on dominant axis
        const animDir = this._walkDirection(dx, dy);
        agent.lastDir = animDir;
        this._playAnim(agent, `walk-${animDir}`);
    }

    /**
     * Determine the cardinal walk direction from a movement delta.
     *
     * @param {number} dx - Horizontal delta (positive = right).
     * @param {number} dy - Vertical delta (positive = down).
     * @returns {string} One of "left", "right", "up", "down".
     * @private
     */
    _walkDirection(dx, dy) {
        if (Math.abs(dx) >= Math.abs(dy)) {
            return dx >= 0 ? "right" : "left";
        }
        return dy >= 0 ? "down" : "up";
    }

    /**
     * Play idle animation in place (no movement). Used for "lingering" state.
     */
    _playIdleInPlace(agentId) {
        const agent = this.agents.get(agentId);
        if (!agent) return;
        const dir = agent.lastDir || "down";
        this._playAnim(agent, `idle-${dir}`);
    }

    /**
     * Play the appropriate animation when an agent arrives at its destination.
     * Uses "working" for active states, falls back to "idle-down".
     * @private
     */
    _playArrivalAnim(agent) {
        const state = agent.state;
        if (state === "executing" || state === "writing") {
            if (this.scene.anims.exists(`${agent.spriteKey}_working`)) {
                this._playAnim(agent, "working");
                return;
            }
        }
        const dir = agent.lastDir || "down";
        this._playAnim(agent, `idle-${dir}`);
    }

    _playAnim(agent, key) {
        const fullKey = `${agent.spriteKey}_${key}`;

        // Avoid restarting the same animation
        if (agent.sprite.anims.currentAnim
            && agent.sprite.anims.currentAnim.key === fullKey) {
            return;
        }

        if (this.scene.anims.exists(fullKey)) {
            agent.sprite.play(fullKey);
        }
    }

    /**
     * Keep the name tag and speech bubble positioned relative to the sprite.
     *
     * @param {object} agent - Agent object.
     * @private
     */
    _syncAttachments(agent) {
        // Name tag is a DOM element — convert world coords to screen position
        const canvas = this.scene.game.canvas;
        const rect = canvas.getBoundingClientRect();
        const scaleX = rect.width / canvas.width;
        const scaleY = rect.height / canvas.height;
        const camera = this.scene.cameras.main;
        const wx = (agent.sprite.x - camera.scrollX) * camera.zoom;
        const wy = (agent.sprite.y - 36 * (CONFIG.CHAR_SCALE || 1) - camera.scrollY) * camera.zoom;
        agent.nameTag.style.left = `${rect.left + wx * scaleX}px`;
        agent.nameTag.style.top = `${rect.top + wy * scaleY}px`;

        if (agent.bubble) {
            agent.bubble.setPosition(agent.sprite.x, agent.sprite.y - 44 * (CONFIG.CHAR_SCALE || 1));
        }
    }

    /**
     * Convert a room's tile-based spawn coords to world pixel coords
     * (center of the tile).
     *
     * Falls back to the "break" room if the requested room is unknown.
     *
     * @param {string} room - Room key.
     * @returns {{ x: number, y: number }} World-pixel position.
     * @private
     */
    _roomSpawn(room) {
        const ts = CONFIG.TILE_SIZE;
        const areas = this.config._roomAreas;

        // If room areas are defined, pick a random walkable tile from the area
        if (areas && areas[room] && areas[room].length > 0) {
            const tiles = areas[room];
            // Fisher-Yates shuffle for unbiased random tile selection
            const shuffled = tiles.slice();
            for (let i = shuffled.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
            }
            for (const [tx, ty] of shuffled) {
                if (this.pathfinder.isWalkable(tx, ty)) {
                    return { x: tx * ts + ts / 2, y: ty * ts + ts / 2 };
                }
            }
        }

        // Fallback to fixed spawn point
        const roomDef = this.config.rooms[room] || this.config.rooms["break"];
        const tile = roomDef.spawn;
        return {
            x: tile.x * ts + ts / 2,
            y: tile.y * ts + ts / 2,
        };
    }

    /**
     * Build a Set of "tx,ty" keys for all tiles currently occupied or
     * targeted by agents (includes path destinations for moving agents).
     * @returns {Set<string>}
     * @private
     */
    _getOccupiedTiles() {
        const ts = CONFIG.TILE_SIZE;
        const occupied = new Set();
        for (const a of this.agents.values()) {
            // Current position
            const tx = Math.floor(a.sprite.x / ts);
            const ty = Math.floor(a.sprite.y / ts);
            occupied.add(`${tx},${ty}`);
            // Destination of moving agents
            if (a.moving && a.path && a.path.length > 0) {
                const dest = a.path[a.path.length - 1];
                const dx = Math.floor(dest.x / ts);
                const dy = Math.floor(dest.y / ts);
                occupied.add(`${dx},${dy}`);
            }
        }
        return occupied;
    }

    /**
     * Find a random walkable, unoccupied tile within a radius of (cx, cy).
     * Returns world-pixel coords or null.
     * @private
     */
    _findRandomNearby(cx, cy, radius, occupied) {
        const ts = CONFIG.TILE_SIZE;
        const candidates = [];
        for (let dx = -radius; dx <= radius; dx++) {
            for (let dy = -radius; dy <= radius; dy++) {
                const tx = cx + dx;
                const ty = cy + dy;
                if (occupied.has(`${tx},${ty}`)) continue;
                if (!this.pathfinder.isWalkable(tx, ty)) continue;
                candidates.push([tx, ty]);
            }
        }
        if (candidates.length === 0) return null;
        const [tx, ty] = candidates[Math.floor(Math.random() * candidates.length)];
        return { x: tx * ts + ts / 2, y: ty * ts + ts / 2 };
    }

    /**
     * Determine which room a tile belongs to based on room_areas config.
     * Returns the room key or null if not found.
     * @private
     */
    _getRoomForTile(tx, ty) {
        // Rebuild lookup if room areas were loaded after construction
        if (this._roomTileLookup.size === 0 && this.config._roomAreas) {
            this._roomTileLookup = this._buildRoomTileLookup();
        }
        return this._roomTileLookup.get(`${tx},${ty}`) || null;
    }

    /**
     * Find a walkable, unoccupied tile adjacent to (tx, ty).
     *
     * @param {number} tx - Target tile X.
     * @param {number} ty - Target tile Y.
     * @param {Set<string>} occupied - Currently occupied tile keys.
     * @returns {{ x: number, y: number } | null} World-pixel coords or null.
     * @private
     */
    _findAdjacentEmpty(tx, ty, occupied) {
        const ts = CONFIG.TILE_SIZE;
        const offsets = [
            [0, -1], [0, 1], [-1, 0], [1, 0],
            [-1, -1], [1, -1], [-1, 1], [1, 1],
            [0, -2], [0, 2], [-2, 0], [2, 0],
        ];
        for (const [dx, dy] of offsets) {
            const nx = tx + dx;
            const ny = ty + dy;
            if (occupied.has(`${nx},${ny}`)) continue;
            if (!this.pathfinder.isWalkable(nx, ny)) continue;
            return { x: nx * ts + ts / 2, y: ny * ts + ts / 2 };
        }
        return null;
    }

    /**
     * Move sourceAgent to an adjacent tile near targetAgent.
     * Used for team-mode conversations.
     *
     * @param {string} sourceId - Agent that moves.
     * @param {string} targetId - Agent to approach.
     */
    async gatherTo(sourceId, targetId) {
        const source = this.agents.get(sourceId);
        const target = this.agents.get(targetId);
        if (!source || !target) return;

        const ts = CONFIG.TILE_SIZE;
        const targetTX = Math.floor(target.sprite.x / ts);
        const targetTY = Math.floor(target.sprite.y / ts);

        const occupied = this._getOccupiedTiles();
        const dest = this._findAdjacentEmpty(targetTX, targetTY, occupied);
        if (!dest) return;

        const path = await this.pathfinder.findPath(
            source.sprite.x, source.sprite.y, dest.x, dest.y,
        );
        if (path && path.length >= 2) {
            source.moving = true;
            source.path = path;
            source.pathIndex = 1;
        } else {
            source.sprite.setPosition(dest.x, dest.y);
            this._syncAttachments(source);
        }
    }
}
