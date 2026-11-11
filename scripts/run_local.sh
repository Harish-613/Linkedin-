#!/usr/bin/env bash
# One-command local setup for LinkedIn++ on macOS (Homebrew).
#
#   ./scripts/run_local.sh            # full run: install deps, load real data, start API, build extension
#   DETAILS=100 ./scripts/run_local.sh    # fetch SEC financials for fewer companies (faster)
#
# Safe to re-run: every step skips work that's already done.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/.run"
mkdir -p "$RUN_DIR"
DETAILS="${DETAILS:-300}"
PORT="${PORT:-8787}"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- dependencies
step "Checking Homebrew packages"
command -v brew >/dev/null || die "Homebrew is required: https://brew.sh"
for pkg in postgresql@16 redis python@3.12 node; do
  if brew list --versions "$pkg" >/dev/null 2>&1; then
    echo "  $pkg: installed"
  else
    echo "  $pkg: installing..."
    brew install "$pkg"
  fi
done
BREW="$(brew --prefix)"
export PATH="$BREW/opt/postgresql@16/bin:$PATH"
PY="$BREW/opt/python@3.12/bin/python3.12"

step "Starting Postgres and Redis"
brew services start postgresql@16 >/dev/null 2>&1 || true
brew services start redis >/dev/null 2>&1 || true
for _ in $(seq 1 30); do pg_isready -q -h localhost && break; sleep 1; done
pg_isready -q -h localhost || die "Postgres did not start (try: brew services restart postgresql@16)"
redis-cli ping >/dev/null 2>&1 && echo "  redis: up" || echo "  redis: not responding (the API will run without a cache)"
createdb -h localhost linkedinpp 2>/dev/null && echo "  created database linkedinpp" || echo "  database linkedinpp exists"
export DATABASE_URL="postgresql://localhost/linkedinpp"

# SEC requires a User-Agent with contact details.
EMAIL="$(git -C "$ROOT" config user.email || true)"
export LPP_USER_AGENT="${LPP_USER_AGENT:-LinkedIn++ research ${EMAIL:-unknown@example.com}}"

# ---------------------------------------------------------------- pipeline
step "Installing the pipeline"
cd "$ROOT/pipeline"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e .

step "Loading real data (SEC + career pages${CRUNCHBASE_API_KEY:+ + Crunchbase}${BUILTWITH_API_KEY:+ + BuiltWith})"
echo "  SEC financials for the $DETAILS largest companies; this takes a few minutes."
.venv/bin/lpp all --details "$DETAILS" 2>&1 | tee "$RUN_DIR/pipeline.log"
.venv/bin/lpp stats | tee -a "$RUN_DIR/pipeline.log"

# ---------------------------------------------------------------- API
step "Building and starting the API on port $PORT"
cd "$ROOT/server"
npm install --silent --no-audit --no-fund
npm run build --silent
if [ -f "$RUN_DIR/server.pid" ] && kill -0 "$(cat "$RUN_DIR/server.pid")" 2>/dev/null; then
  kill "$(cat "$RUN_DIR/server.pid")" && sleep 1
fi
PORT="$PORT" nohup node dist/server.js > "$RUN_DIR/server.log" 2>&1 &
echo $! > "$RUN_DIR/server.pid"
for _ in $(seq 1 20); do curl -sf "localhost:$PORT/health" >/dev/null && break; sleep 0.5; done
curl -sf "localhost:$PORT/health" >/dev/null || die "API did not start; see $RUN_DIR/server.log"
echo "  API running (pid $(cat "$RUN_DIR/server.pid")), logs in .run/server.log"

# ---------------------------------------------------------------- extension
step "Building the Chrome extension"
cd "$ROOT/extension"
npm install --silent --no-audit --no-fund
npm run build --silent >/dev/null

# ---------------------------------------------------------------- smoke test
step "Sample answers from the API"
"$PY" "$ROOT/scripts/smoke.py" "http://localhost:$PORT"

cat <<EOF

Done. Last step (one time):
  1. Open chrome://extensions and turn on Developer mode (top right)
  2. Click "Load unpacked" and choose: $ROOT/extension/dist
  3. Open any job on https://www.linkedin.com/jobs/

Stop the API later with:  kill \$(cat $RUN_DIR/server.pid)
EOF
