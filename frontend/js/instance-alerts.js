/**
 * Pie Office — Instance Alert Manager
 *
 * Displays animated alert sprites on server room computer slots when
 * Claude Code instances need user input (permission/idle prompts).
 * Click a slot to see session details in a DOM popup.
 *
 * Depends on: CONFIG (config.js)
 */

/* exported InstanceAlertManager */
class InstanceAlertManager {
  /**
   * @param {Phaser.Scene} scene
   * @param {object} themeConfig - Parsed theme config.json
   */
  constructor(scene, themeConfig) {
    this.scene = scene;
    this.slots = themeConfig.instance_slots || [];
    /** @type {Map<number, object>} slot_index → { sprite, tweens, data } */
    this._active = new Map();
    /** @type {number|null} slot_index of the most recent alert */
    this._latestSlot = null;
    /** @type {HTMLElement|null} current popup DOM element */
    this._popup = null;
    /** @type {string|null} session_id of the currently shown popup */
    this._popupSessionId = null;

    // Click handler on scene
    this.scene.input.on("pointerdown", (pointer) => this._onClick(pointer));
    // Dismiss popup on click outside
    this._onDocPointerDown = (e) => {
      if (this._popup && !this._popup.contains(e.target)) {
        this._dismissPopup();
      }
    };
    document.addEventListener("pointerdown", this._onDocPointerDown);
  }

  /**
   * Clean up DOM listeners and resources.
   * Call when the Phaser scene is destroyed.
   */
  destroy() {
    document.removeEventListener("pointerdown", this._onDocPointerDown);
    this._dismissPopup();
    for (const [idx] of this._active) {
      this._removeSlot(idx);
    }
    this._active.clear();
  }

  // ── Public API ────────────────────────────────────────────────

  /**
   * Show or update an alert at the given slot.
   * @param {object} data - { slot_index, alert_type, alert_message, cwd, alert_at, session_id }
   */
  showAlert(data) {
    const idx = data.slot_index;
    if (idx == null || idx < 0 || idx >= this.slots.length) return;

    const slot = this.slots[idx];
    const ts = CONFIG.TILE_SIZE;
    const wx = slot.x * ts + ts / 2;
    const wy = slot.y * ts; // Sprite sits above the tile

    // Determine sprite key
    const spriteKey = data.alert_type === "permission_prompt"
      ? "obj_alert_exclamation"
      : "obj_alert_question";

    // Remove existing alert at this slot if any
    this._removeSlot(idx);

    // Create sprite
    const sprite = this.scene.add.sprite(wx, wy, spriteKey);
    sprite.setDepth(150);
    sprite.setOrigin(0.5, 1);

    // Create frame animation if not exists
    const animKey = data.alert_type === "permission_prompt"
      ? "anim_alert_exclamation"
      : "anim_alert_question";
    if (!this.scene.anims.exists(animKey)) {
      this.scene.anims.create({
        key: animKey,
        frames: this.scene.anims.generateFrameNumbers(spriteKey, { start: 0, end: 1 }),
        frameRate: 3,
        repeat: -1,
      });
    }
    sprite.play(animKey);

    // Demote previous latest to slow float
    if (this._latestSlot !== null && this._latestSlot !== idx) {
      this._setSlowFloat(this._latestSlot);
    }

    // Set this as latest with fast pulse
    const tweens = this._addFastPulse(sprite);
    this._active.set(idx, { sprite, tweens, data });
    this._latestSlot = idx;
  }

  /**
   * Clear the alert at the slot for the given session.
   * @param {string} sessionId
   */
  clearAlert(sessionId) {
    // Dismiss popup if it belongs to this session
    if (this._popupSessionId === sessionId) {
      this._dismissPopup();
    }
    for (const [idx, entry] of this._active) {
      if (entry.data.session_id === sessionId) {
        this._removeSlot(idx);
        if (this._latestSlot === idx) {
          this._latestSlot = null;
          this._promoteNewestRemaining();
        }
        break;
      }
    }
  }

  /**
   * Release a slot entirely (session timed out).
   * @param {string} sessionId
   */
  releaseSlot(sessionId) {
    this.clearAlert(sessionId);
  }

  /**
   * Load initial instance state from /state response.
   * @param {object} instances - { session_id: { slot_index, alert_type, ... } }
   */
  loadInitial(instances) {
    if (!instances) return;
    const sorted = Object.values(instances)
      .filter(i => i.alert_type)
      .sort((a, b) => (a.alert_at || 0) - (b.alert_at || 0));
    for (const inst of sorted) {
      this.showAlert(inst);
    }
  }

  // ── Private ───────────────────────────────────────────────────

  _removeSlot(idx) {
    const entry = this._active.get(idx);
    if (!entry) return;
    if (entry.tweens) {
      for (const tw of entry.tweens) tw.destroy();
    }
    entry.sprite.destroy();
    this._active.delete(idx);
  }

  _addFastPulse(sprite) {
    const scaleTween = this.scene.tweens.add({
      targets: sprite,
      scaleX: 1.3,
      scaleY: 1.3,
      alpha: 0.6,
      duration: 300,
      yoyo: true,
      repeat: -1,
      ease: "Sine.easeInOut",
    });
    return [scaleTween];
  }

  _addSlowFloat(sprite) {
    const baseY = sprite.y;
    const floatTween = this.scene.tweens.add({
      targets: sprite,
      y: baseY - 3,
      duration: 1000,
      yoyo: true,
      repeat: -1,
      ease: "Sine.easeInOut",
    });
    sprite.setScale(1);
    sprite.setAlpha(1);
    return [floatTween];
  }

  _setSlowFloat(idx) {
    const entry = this._active.get(idx);
    if (!entry) return;
    if (entry.tweens) {
      for (const tw of entry.tweens) tw.destroy();
    }
    entry.tweens = this._addSlowFloat(entry.sprite);
  }

  _promoteNewestRemaining() {
    let newest = null;
    let newestAt = 0;
    for (const [idx, entry] of this._active) {
      const at = entry.data.alert_at || 0;
      if (at > newestAt) {
        newestAt = at;
        newest = idx;
      }
    }
    if (newest !== null) {
      this._latestSlot = newest;
      const entry = this._active.get(newest);
      if (entry.tweens) {
        for (const tw of entry.tweens) tw.destroy();
      }
      entry.tweens = this._addFastPulse(entry.sprite);
    }
  }

  _onClick(pointer) {
    const ts = CONFIG.TILE_SIZE;
    for (const [idx, entry] of this._active) {
      const slot = this.slots[idx];
      const wx = slot.x * ts + ts / 2;
      const wy = slot.y * ts;
      // Sprite origin is (0.5, 1), so visual center is at (wx, wy - spriteHeight/2)
      const spriteH = entry.sprite.displayHeight || 64;
      const cx = wx;
      const cy = wy - spriteH / 2;
      const dist = Phaser.Math.Distance.Between(
        pointer.worldX, pointer.worldY, cx, cy,
      );
      if (dist < 32) {
        this._showPopup(idx, entry.data, pointer);
        return;
      }
    }
  }

  _showPopup(idx, data, pointer) {
    this._dismissPopup();

    const projectName = (data.cwd || "unknown").split("/").pop();
    const alertLabel = data.alert_type === "permission_prompt"
      ? "Permission Required"
      : "Waiting for Input";
    const message = data.alert_message || "";
    const ago = data.alert_at
      ? Math.round((Date.now() / 1000 - data.alert_at)) + "s ago"
      : "";

    const popup = document.createElement("div");
    popup.className = "instance-popup";
    popup.innerHTML =
      `<div class="popup-label">${alertLabel}</div>` +
      `<div class="popup-project">${this._esc(projectName)}</div>` +
      `<div class="popup-message">${this._esc(message)}</div>` +
      `<div class="popup-time">${ago}</div>`;

    // Position near click point
    const canvas = this.scene.game.canvas;
    const rect = canvas.getBoundingClientRect();
    const scaleX = rect.width / canvas.width;
    const scaleY = rect.height / canvas.height;
    popup.style.left = `${rect.left + pointer.x * scaleX}px`;
    popup.style.top = `${rect.top + pointer.y * scaleY - 10}px`;
    popup.style.transform = "translate(-50%, -100%)";

    document.body.appendChild(popup);
    this._popup = popup;
    this._popupSessionId = data.session_id || null;
  }

  _dismissPopup() {
    if (this._popup) {
      this._popup.remove();
      this._popup = null;
      this._popupSessionId = null;
    }
  }

  _esc(str) {
    if (typeof str !== "string") return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}
