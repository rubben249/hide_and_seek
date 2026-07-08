#!/usr/bin/env bash
# run.sh — One-command launcher for TAG! — The Playground Chase
# Usage: ./run.sh
set -euo pipefail

# ── Colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[TAG!]${NC} $*"; }
ok()    { echo -e "${GREEN}[TAG!]${NC} $*"; }
warn()  { echo -e "${YELLOW}[TAG!]${NC} $*"; }
err()   { echo -e "${RED}[TAG!]${NC} $*" >&2; }

# ── Script location ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Detect container runtime (docker or podman) ──────────────────────────────
detect_runtime() {
    if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
        echo "docker"
    elif command -v podman &>/dev/null; then
        echo "podman"
    else
        err "Neither Docker nor Podman found. Install one and try again."
        exit 1
    fi
}

RUNTIME=$(detect_runtime)
info "Container runtime: $RUNTIME"

# Compose command: prefer docker compose (plugin) over docker-compose (legacy)
if [[ "$RUNTIME" == "docker" ]]; then
    if docker compose version &>/dev/null 2>&1; then
        COMPOSE="docker compose"
    else
        COMPOSE="docker-compose"
    fi
else
    if command -v podman-compose &>/dev/null; then
        COMPOSE="podman-compose"
    else
        err "podman-compose not found. Install it: pip install podman-compose"
        exit 1
    fi
fi

# ── Step 1: Update uv ────────────────────────────────────────────────────────
info "Step 1/4 — Updating uv..."
if command -v uv &>/dev/null; then
    uv self update 2>/dev/null && ok "uv updated" || warn "uv self-update skipped (may not be supported in this install method)"
else
    warn "uv not found in PATH — skipping uv update (Docker build will use its own uv)"
fi

# ── Step 2: Update pinned dependencies in pyproject.toml ────────────────────
info "Step 2/4 — Updating dependencies..."
UV_BIN=""
if command -v uv &>/dev/null; then
    UV_BIN="uv"
elif [[ -f "$HOME/snap/code/242/.local/bin/uv" ]]; then
    UV_BIN="$HOME/snap/code/242/.local/bin/uv"
elif [[ -f "$HOME/.local/bin/uv" ]]; then
    UV_BIN="$HOME/.local/bin/uv"
fi

if [[ -n "$UV_BIN" ]]; then
    (cd backend && "$UV_BIN" lock --upgrade) && ok "Dependencies updated in uv.lock" || warn "Could not update lock file — using existing"
else
    warn "uv not found — skipping dependency update"
fi

# ── Step 3: Build and launch container ──────────────────────────────────────
info "Step 3/4 — Building and launching container..."

# Read PORT from .env (default 8000)
PORT=8000
if [[ -f .env ]]; then
    PARSED_PORT=$(grep -E '^PORT=' .env | head -1 | cut -d'=' -f2 | tr -d '[:space:]')
    [[ -n "$PARSED_PORT" ]] && PORT="$PARSED_PORT"
fi
info "Port: $PORT"

# Stop any running instance
$COMPOSE down --remove-orphans 2>/dev/null || true

# Build + start
$COMPOSE up --build -d
ok "Container started"

# ── Step 4: Wait for server and open browser ─────────────────────────────────
info "Step 4/4 — Waiting for server to be ready..."
URL="http://localhost:$PORT"
MAX_RETRIES=60
for i in $(seq 1 $MAX_RETRIES); do
    if curl -sf "$URL/api/health" &>/dev/null; then
        ok "Server is up at $URL"
        break
    fi
    if [[ $i -eq $MAX_RETRIES ]]; then
        warn "Server didn't respond after ${MAX_RETRIES}s — check logs with: $COMPOSE logs -f"
        break
    fi
    echo -n "."
    sleep 2
done
echo ""

# Open browser — prefer Chrome/Chromium, fall back to system default
ADMIN_URL="$URL/admin.html"
info "Opening Chrome: game at $URL and admin panel at $ADMIN_URL ..."
OPENED=false
for CHROME_CMD in \
    "google-chrome" "google-chrome-stable" \
    "chromium-browser" "chromium" \
    "microsoft-edge" "microsoft-edge-stable"; do
    if command -v "$CHROME_CMD" &>/dev/null; then
        # Open game window first, then admin in a new tab
        "$CHROME_CMD" --new-window "$URL" "$ADMIN_URL" &>/dev/null &
        OPENED=true
        ok "Opened with $CHROME_CMD (game + admin tabs)"
        break
    fi
done
if [[ "$OPENED" == "false" ]]; then
    # WSL2
    if command -v wslview &>/dev/null; then
        wslview "$URL"; OPENED=true
    # macOS
    elif command -v open &>/dev/null; then
        open -a "Google Chrome" "$URL" 2>/dev/null || open "$URL"; OPENED=true
    # Linux fallback
    elif command -v xdg-open &>/dev/null; then
        xdg-open "$URL" &
        OPENED=true
    fi
fi
[[ "$OPENED" == "false" ]] && warn "Could not auto-open browser — navigate to: $URL"

echo ""
ok "TAG! is running! 🎮"
echo -e "  Game:       ${CYAN}$URL${NC}"
echo -e "  Admin:      ${CYAN}$URL/admin.html${NC}"
echo -e "  Logs:       ${CYAN}$COMPOSE logs -f${NC}"
echo -e "  Stop:       ${CYAN}$COMPOSE down${NC}"
