#!/usr/bin/env bash
# Bring up PayGuard locally (Postgres assumed running), then seed one clean VERIFIED demo
# scan. The sandbox uses the ISOLATED DOCKER runtime when the daemon is up; it falls back
# to the no-isolation subprocess runner only if Docker is unavailable (with a warning).
#
#   bash scripts/dev-up.sh          # start services + seed
#   bash scripts/dev-up.sh --no-seed
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://payguard:payguard@localhost:5432/payguard}"
export PAYGUARD_ENV="${PAYGUARD_ENV:-TEST}"
# Use the local Ollama analyzer fallback so the console shows llm=ok offline (opt-in so it
# never changes eval semantics). Requires `ollama serve` + the model in config/llm_limits.yml.
export PAYGUARD_OLLAMA_FALLBACK="${PAYGUARD_OLLAMA_FALLBACK:-1}"

echo "▸ preparing sandbox"
# Vendor each target's deps once (used by both runtimes; in Docker they ride in the
# read-only target mount — no in-container network install).
for t in "$ROOT"/examples/targets/*/; do
  if [ -f "$t/package.json" ] && [ ! -d "$t/node_modules" ]; then
    echo "  installing deps in $(basename "$t")"
    ( cd "$t" && npm install --no-audit --no-fund >/dev/null 2>&1 )
  fi
done
if docker info >/dev/null 2>&1; then
  if ! docker image inspect payguard-sandbox-node20 >/dev/null 2>&1; then
    echo "  building sandbox image payguard-sandbox-node20"
    docker build -t payguard-sandbox-node20 "$ROOT/sandbox-images/node20/" >/dev/null
  fi
  echo "  sandbox runtime: DOCKER (isolated)"
else
  export SANDBOX_RUNTIME=subprocess
  echo "  ⚠ Docker daemon not available — sandbox runtime: SUBPROCESS (NO ISOLATION, dev only)"
fi

echo "▸ migrating database"
DATABASE_URL="$DATABASE_URL" "$PY" -m alembic upgrade head >/dev/null 2>&1 || {
  echo "  ! alembic upgrade failed — is Postgres running? (createdb payguard, user payguard)"; exit 1; }

start() { # name  port  cmd...
  local name="$1" port="$2"; shift 2
  if lsof -ti "tcp:$port" >/dev/null 2>&1; then
    echo "▸ $name already on :$port (leaving it)"
  else
    echo "▸ starting $name on :$port"
    nohup "$@" >"/tmp/payguard-$name.log" 2>&1 &
  fi
}

start gateway 8001 "$PY" -m uvicorn payguard.gateway.app:app --host 0.0.0.0 --port 8001
start api     8000 "$PY" -m uvicorn payguard.api.app:app     --host 0.0.0.0 --port 8000

# Worker has no port; (re)start it.
pkill -f "payguard.worker" 2>/dev/null || true
echo "▸ starting worker"
nohup "$PY" -m payguard.worker >/tmp/payguard-worker.log 2>&1 &

# Web (Next dev) if the toolchain is present and not already up.
if [ -d "$ROOT/web/node_modules" ] && ! lsof -ti tcp:3000 >/dev/null 2>&1; then
  echo "▸ starting web on :3000"
  ( cd "$ROOT/web" && nohup npm run dev >/tmp/payguard-web.log 2>&1 & )
fi

echo "▸ waiting for health"
for url in http://localhost:8001/healthz http://localhost:8000/healthz; do
  for _ in $(seq 1 40); do
    if curl -sf "$url" >/dev/null 2>&1; then break; fi
    sleep 0.25
  done
done

if [ "${1:-}" != "--no-seed" ]; then
  echo "▸ seeding demo"
  "$PY" -m payguard.demo.seed
fi

echo ""
echo "PayGuard is up →  http://localhost:3000   (API :8000, gateway :8001)"
echo "Stop:  pkill -f 'uvicorn payguard'; pkill -f payguard.worker"
