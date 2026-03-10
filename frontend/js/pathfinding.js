/**
 * Pathfinder — A* pathfinding wrapper bridging EasyStar.js with Phaser 3 tilemaps.
 *
 * Expects EasyStar.js loaded globally from CDN (constructor at `EasyStar.js`).
 * Grid convention: 0 = walkable, 1 = blocked.
 */
class Pathfinder {
    /**
     * @param {Phaser.Tilemaps.Tilemap} map - Phaser tilemap instance.
     * @param {Phaser.Tilemaps.TilemapLayer[]} collisionLayers - Layers whose tiles
     *   may have `properties.collides === true`.
     */
    constructor(map, collisionLayers) {
        this.map = map;
        this.finder = new EasyStar.js();

        this._buildGrid(collisionLayers);

        this.finder.setAcceptableTiles([0]);
    }

    /**
     * Build the walkability grid from collision layers and feed it to EasyStar.
     *
     * Iterates every tile position on the map. If *any* collision layer has a
     * tile whose `collides` property is truthy at that position, the cell is
     * marked blocked (1). Otherwise it is walkable (0).
     *
     * @param {Phaser.Tilemaps.TilemapLayer[]} collisionLayers
     * @private
     */
    _buildGrid(collisionLayers) {
        const { width, height } = this.map;
        const grid = [];

        for (let y = 0; y < height; y++) {
            const row = [];
            for (let x = 0; x < width; x++) {
                let blocked = false;
                for (const layer of collisionLayers) {
                    const tile = layer.getTileAt(x, y);
                    if (tile && tile.properties && tile.properties.collides) {
                        blocked = true;
                        break;
                    }
                }
                row.push(blocked ? 1 : 0);
            }
            grid.push(row);
        }

        this.grid = grid;
        this.finder.setGrid(grid);
    }

    /**
     * Check if a tile coordinate is walkable (no collision).
     * @param {number} tileX
     * @param {number} tileY
     * @returns {boolean}
     */
    isWalkable(tileX, tileY) {
        if (tileY < 0 || tileY >= this.grid.length) return false;
        if (tileX < 0 || tileX >= this.grid[0].length) return false;
        return this.grid[tileY][tileX] === 0;
    }

    /**
     * Find a path between two world-coordinate positions.
     *
     * Converts world coordinates to tile coordinates, runs A*, then converts
     * the resulting tile path back to world coordinates (center of each tile).
     *
     * @param {number} fromX - Start X in world pixels.
     * @param {number} fromY - Start Y in world pixels.
     * @param {number} toX   - End X in world pixels.
     * @param {number} toY   - End Y in world pixels.
     * @returns {Promise<{x: number, y: number}[]|null>} Array of world-coordinate
     *   waypoints, or null if no path exists.
     */
    findPath(fromX, fromY, toX, toY) {
        const startTileX = this.map.worldToTileX(fromX);
        const startTileY = this.map.worldToTileY(fromY);
        const endTileX = this.map.worldToTileX(toX);
        const endTileY = this.map.worldToTileY(toY);

        return new Promise((resolve) => {
            this.finder.findPath(startTileX, startTileY, endTileX, endTileY, (path) => {
                if (path === null) {
                    resolve(null);
                    return;
                }

                const halfW = this.map.tileWidth / 2;
                const halfH = this.map.tileHeight / 2;

                const worldPath = path.map((point) => ({
                    x: this.map.tileToWorldX(point.x) + halfW,
                    y: this.map.tileToWorldY(point.y) + halfH,
                }));

                resolve(worldPath);
            });

            // EasyStar requires an explicit calculate() call to process queued requests
            this.finder.calculate();
        });
    }

}
