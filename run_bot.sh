#!/usr/bin/env bash
set -euo pipefail

# Automatically switch to docker group if member but session does not have it
# active yet. `getent`/`sg` are Linux-specific and deliberately guarded behind
# `command -v` -- macOS (Docker Desktop) and other platforms without them
# simply skip this and rely on `docker info` having already succeeded above.
if ! docker info >/dev/null 2>&1; then
  if command -v getent >/dev/null 2>&1 && command -v sg >/dev/null 2>&1 \
      && getent group docker | grep -qw "${USER:-$(whoami)}"; then
    exec sg docker -c "$0 $*"
  fi
fi

# Loads .env into this shell's exported environment for the host-run backend
# below -- docker-compose reads .env automatically for the containers it
# manages, but this script launches app_api directly via uvicorn (no compose
# layer in between), so without this, provider switches made via .env (e.g.
# by setup.sh's interactive prompts) would silently never reach the process,
# and only server/project_config.yml's committed defaults would ever apply.
#
# Deliberately NOT a plain `set -a; source .env; set +a`: two precedence
# rules need to hold that a blind source wouldn't get right.
#   1. An already-exported var (e.g. `FOO=bar ./run_bot.sh`) should win over
#      .env, matching docker-compose's own precedence -- a blind source
#      would instead let .env clobber it.
#   2. A blank value in .env (e.g. `LLM_MODEL=`, meaning "use
#      project_config.yml's default") must be treated as unset, not as "set
#      to empty string" -- docker-compose's `${VAR:-default}` interpolation
#      already treats blank and absent identically, but core_config's
#      _resolve() does NOT: `os.getenv()` returns "" (not None) for a
#      set-but-blank var, which _resolve() treats as a real override and
#      uses in place of the YAML default. A blind source would export
#      LLM_MODEL="" and silently break the "blank = use the real default"
#      contract .env.example documents.
load_env_file() {
  local file="$1" line key value
  [[ -f "${file}" ]] || return 0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ "${line}" =~ ^[[:space:]]*(#.*)?$ ]] && continue
    [[ "${line}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    [[ -n "${!key+x}" ]] && continue
    [[ -z "${value}" ]] && continue
    export "${key}=${value}"
  done < "${file}"
}
load_env_file ".env"

VENV_DIR=".venv"
DEFAULT_OLLAMA_URL="http://localhost:11435"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Missing ${VENV_DIR}. Run ./setup.sh first."
  exit 1
fi

if ! curl -s "${DEFAULT_OLLAMA_URL}/api/version" >/dev/null 2>&1; then
  if ! command -v ollama >/dev/null 2>&1; then
    echo "Error: 'ollama' command not found. Please install Ollama or ensure it is running on ${DEFAULT_OLLAMA_URL}."
    exit 1
  fi
  echo "Starting Ollama in background..."
  ./scripts/run_ollama.sh > ollama.log 2>&1 &
  for _ in $(seq 1 30); do
    if curl -s "${DEFAULT_OLLAMA_URL}/api/version" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if ! curl -s "${DEFAULT_OLLAMA_URL}/api/version" >/dev/null 2>&1; then
    echo "Error: Ollama failed to start on ${DEFAULT_OLLAMA_URL}. Check ollama.log."
    exit 1
  fi
fi

export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-${DEFAULT_OLLAMA_URL}}"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker-compose)
else
  echo "docker compose is required to run rules-mcp/scryfall-mcp/searxng. Install Docker."
  exit 1
fi

echo "Ensuring rules-mcp, scryfall-mcp, and searxng are up (docker compose)..."
"${DOCKER_COMPOSE[@]}" up -d --build rules-mcp scryfall-mcp searxng

for entry in "rules-mcp:http://localhost:8100/health:600" "scryfall-mcp:http://localhost:3000/health:60" "searxng:http://localhost:8080/:60"; do
  name="${entry%%:*}"
  rest="${entry#*:}"
  timeout="${rest##*:}"
  url="${rest%:*}"
  echo -n "Waiting for ${name} (up to ${timeout}s)..."
  ready=false
  for i in $(seq 1 "${timeout}"); do
    if curl -s -o /dev/null "${url}"; then
      echo " ready."
      ready=true
      break
    fi
    if (( i % 15 == 0 )); then
      echo -n " (${i}s)..."
    fi
    sleep 1
  done
  if [[ "${ready}" != "true" ]]; then
    echo " timed out after ${timeout}s! Check docker compose logs for ${name}."
    exit 1
  fi
done

# PYTHONPATH=server, not `cd server` -- see setup.sh's comment on the same
# pattern: keeps cwd-relative config defaults (data/conversations/...)
# pointed at the real repo-root data/ directory.
export PYTHONPATH="server${PYTHONPATH:+:${PYTHONPATH}}"
APP_HOST="$("${VENV_DIR}/bin/python" -c 'from core_config import Config; print(Config.HOST)')"
APP_PORT="$("${VENV_DIR}/bin/python" -c 'from core_config import Config; print(Config.PORT)')"

exec "${VENV_DIR}/bin/python" -m uvicorn app_api.main:app --host "${APP_HOST}" --port "${APP_PORT}"
