#!/bin/bash
# Pie Office dev server launcher
# Usage: ./dev.sh [port]  (default: 10318)
PORT=${1:-10318}
DIR="$(cd "$(dirname "$0")" && pwd)"

# Kill existing process on port
lsof -ti:"$PORT" 2>/dev/null | xargs kill -9 2>/dev/null

# Activate venv and start server
cd "$DIR"
source venv/bin/activate
echo "Starting Pie Office on :$PORT ..."
PORT=$PORT python3 backend/app.py
