#!/usr/bin/env bash
set -euo pipefail

# Interactive-by-default installer for MTG Azor. Prepares the environment
# (venv, deps, Ollama, model pulls) and walks through the choices that
# actually vary between deployments -- LLM/embedding provider, and how much
# of the stack you want running -- writing the results to .env rather than
# editing any file this repo tracks in git.
#
# Non-interactive (CI, automation, `curl | bash`-style, or explicit
# --non-interactive/--yes/-y): every prompt is skipped and this behaves like
# the old fixed script did -- local/local providers, local-dev-only shape,
# using whatever's already in .env/project_config.yml for anything not
# passed as a flag. Never blocks waiting on input it won't get.

# --- Output helpers -------------------------------------------------------

if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
  GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; CYAN=$'\033[36m'
else
  BOLD=""; DIM=""; RESET=""; GREEN=""; YELLOW=""; RED=""; CYAN=""
fi

step() { printf '\n%s%s==> %s%s\n' "${BOLD}" "${CYAN}" "$1" "${RESET}"; }
ok()   { printf '  %s✓%s %s\n' "${GREEN}" "${RESET}" "$1"; }
warn() { printf '  %s!%s %s\n' "${YELLOW}" "${RESET}" "$1"; }
err()  { printf '  %s✗%s %s\n' "${RED}" "${RESET}" "$1" >&2; }
info() { printf '  %s%s%s\n' "${DIM}" "$1" "${RESET}"; }

# --- Interactivity ---------------------------------------------------------

INTERACTIVE=true
for arg in "$@"; do
  case "${arg}" in
    --non-interactive|--yes|-y) INTERACTIVE=false ;;
  esac
done
if [[ ! -t 0 ]]; then
  INTERACTIVE=false
fi

# --- .env helpers -----------------------------------------------------------
# Personal provider/model/token choices go into .env (gitignored), never into
# server/project_config.yml (tracked) -- same reasoning as every other
# secret/environment-specific value already documented in .env.example.

ENV_FILE=".env"

ensure_env_file() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    if [[ -f ".env.example" ]]; then
      cp .env.example "${ENV_FILE}"
      ok "Created ${ENV_FILE} from .env.example."
    else
      touch "${ENV_FILE}"
    fi
  fi
}

# Reads KEY's current value out of .env; returns DEFAULT if absent or blank
# (blank is treated as "not meaningfully set" here, matching how every
# provider var in .env.example documents blank as "use the real default").
get_env_var() {
  local key="$1" default="$2" line value
  line=$(grep "^${key}=" "${ENV_FILE}" 2>/dev/null | tail -n1 || true)
  value="${line#*=}"
  if [[ -n "${value}" ]]; then
    printf '%s' "${value}"
  else
    printf '%s' "${default}"
  fi
}

# Upserts KEY=VALUE in .env, preserving every other line (including the
# explanatory comments .env.example seeds it with).
set_env_var() {
  local key="$1" value="$2" escaped
  escaped=$(printf '%s' "${value}" | sed -e 's/[\\&|]/\\&/g')
  if grep -q "^${key}=" "${ENV_FILE}" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${escaped}|" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}

# Appends VALUE into KEY's comma-separated list in .env if not already
# present -- used for DISCORD_API_KEY, which needs to land in its own var
# AND in the shared API_KEYS allowlist (see .env.example's comment on it).
append_env_csv_value() {
  local key="$1" value="$2" current
  [[ -z "${value}" ]] && return
  current="$(get_env_var "${key}" "")"
  if [[ ",${current}," == *",${value},"* ]]; then
    return
  fi
  if [[ -z "${current}" ]]; then
    set_env_var "${key}" "${value}"
  else
    set_env_var "${key}" "${current},${value}"
  fi
}

VENV_DIR=".venv"
OLLAMA_URL="http://localhost:11435"
NEED_OLLAMA=false

echo "${BOLD}MTG Azor — setup${RESET}"
info "This prepares your environment and, unless run with --non-interactive,"
info "asks a few questions about how you want to run it: which LLM/embedding"
info "provider, and how much of the stack (local dev only, vs. the full"
info "Caddy-fronted deployment)."

step "Python environment"
if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
  ok "Created ${VENV_DIR}."
else
  ok "Reusing existing ${VENV_DIR}."
fi
"${VENV_DIR}/bin/pip" install --upgrade pip --quiet
"${VENV_DIR}/bin/pip" install -r server/requirements.txt --quiet
ok "Dependencies installed."

if [[ ! -f server/project_config.yml ]]; then
  err "Missing server/project_config.yml. Restore it before running setup."
  exit 1
fi

ensure_env_file

# PYTHONPATH=server, not `cd server` -- keeps cwd-relative defaults (e.g.
# CONVERSATION_DB_PATH) pointed at the real repo-root data/ directory.
py() { PYTHONPATH=server "${VENV_DIR}/bin/python" -c "$1"; }

# --- LLM provider -----------------------------------------------------------

step "LLM provider (chat model)"
CURRENT_LLM_PROVIDER="$(get_env_var LLM_PROVIDER "$(py 'from core_config import Config; print(Config.LLM_PROVIDER)')")"

if [[ "${INTERACTIVE}" == true ]]; then
  info "Local  -- talks to your own Ollama instance. The out-of-the-box"
  info "         model (gemma4:cloud) still runs on Ollama's cloud"
  info "         infrastructure and needs internet + a one-time sign-in --"
  info "         it is NOT air-gapped by default. Pick a real local weights"
  info "         tag below for genuinely offline inference."
  info "Hosted -- routes chat through OpenRouter. Needs an API key, costs"
  info "         per request, works on any hardware with zero local"
  info "         inference at all."
  read -r -p "Use [L]ocal or [H]osted chat? [${CURRENT_LLM_PROVIDER:0:1}]: " choice
  choice="${choice:-${CURRENT_LLM_PROVIDER:0:1}}"
else
  choice="${CURRENT_LLM_PROVIDER:0:1}"
fi

case "${choice,,}" in
  h)
    set_env_var LLM_PROVIDER hosted
    LLM_PROVIDER=hosted
    if [[ "${INTERACTIVE}" == true ]]; then
      current_key="$(get_env_var OPENROUTER_API_KEY "")"
      while true; do
        if [[ -n "${current_key}" ]]; then
          read -r -s -p "OpenRouter API key [keep existing]: " key; echo
          key="${key:-${current_key}}"
        else
          read -r -s -p "OpenRouter API key: " key; echo
        fi
        [[ -n "${key}" ]] && break
        warn "An API key is required for hosted mode."
      done
      set_env_var OPENROUTER_API_KEY "${key}"
      current_model="$(get_env_var OPENROUTER_MODEL openrouter/auto)"
      read -r -p "OpenRouter model id [${current_model}]: " model
      set_env_var OPENROUTER_MODEL "${model:-${current_model}}"
    fi
    ok "Chat: hosted via OpenRouter."
    ;;
  *)
    set_env_var LLM_PROVIDER local
    LLM_PROVIDER=local
    NEED_OLLAMA=true
    CURRENT_LLM_MODEL="$(get_env_var LLM_MODEL "$(py 'from core_config import Config; print(Config.LLM_MODEL)')")"
    if [[ "${INTERACTIVE}" == true ]]; then
      read -r -p "Ollama model tag [${CURRENT_LLM_MODEL}]: " model
      LLM_MODEL="${model:-${CURRENT_LLM_MODEL}}"
    else
      LLM_MODEL="${CURRENT_LLM_MODEL}"
    fi
    set_env_var LLM_MODEL "${LLM_MODEL}"
    ok "Chat: local via Ollama (${LLM_MODEL})."
    ;;
esac

# --- Embedding provider ------------------------------------------------------

step "Embedding provider (rules search index)"
CURRENT_EMBED_PROVIDER="$(get_env_var EMBEDDING_PROVIDER local)"

if [[ "${INTERACTIVE}" == true ]]; then
  info "Local  -- Ollama, a real local model (mxbai-embed-large by"
  info "         default) regardless of the chat provider above."
  info "Hosted -- OpenRouter's embeddings endpoint (baai/bge-m3 by"
  info "         default). Independent of the chat provider -- useful on"
  info "         slower/low-core hardware where local embedding compute is"
  info "         the ingestion bottleneck."
  read -r -p "Use [L]ocal or [H]osted embeddings? [${CURRENT_EMBED_PROVIDER:0:1}]: " choice
  choice="${choice:-${CURRENT_EMBED_PROVIDER:0:1}}"
else
  choice="${CURRENT_EMBED_PROVIDER:0:1}"
fi

case "${choice,,}" in
  h)
    set_env_var EMBEDDING_PROVIDER hosted
    if [[ "${INTERACTIVE}" == true ]]; then
      current_key="$(get_env_var OPENROUTER_EMBEDDING_API_KEY "")"
      while true; do
        if [[ -n "${current_key}" ]]; then
          read -r -s -p "OpenRouter embedding API key [keep existing]: " key; echo
          key="${key:-${current_key}}"
        else
          read -r -s -p "OpenRouter embedding API key: " key; echo
        fi
        [[ -n "${key}" ]] && break
        warn "An API key is required for hosted embeddings."
      done
      set_env_var OPENROUTER_EMBEDDING_API_KEY "${key}"
      current_model="$(get_env_var OPENROUTER_EMBEDDING_MODEL baai/bge-m3)"
      read -r -p "OpenRouter embedding model id [${current_model}]: " model
      set_env_var OPENROUTER_EMBEDDING_MODEL "${model:-${current_model}}"
    fi
    ok "Embeddings: hosted via OpenRouter."
    ;;
  *)
    set_env_var EMBEDDING_PROVIDER local
    NEED_OLLAMA=true
    # Queried via rules_mcp.settings.Settings, not a hardcoded string -- that
    # module's own EMBEDDING_MODEL already does os.getenv("EMBEDDING_MODEL",
    # "mxbai-embed-large"), so this correctly picks up an EMBEDDING_MODEL
    # process env var (e.g. set by CI to override the default for a lighter
    # test run) the same way CURRENT_LLM_MODEL picks up LLM_MODEL above via
    # core_config.Config. A first version of this hardcoded the literal
    # string "mxbai-embed-large" here instead -- silently ignoring any
    # EMBEDDING_MODEL env var entirely, confirmed live: a CI job that set
    # EMBEDDING_MODEL=all-minilm to keep ingestion fast still pulled and
    # ingested with mxbai-embed-large (visible in the Ollama log: a ~700MB
    # download and "general.name ... = mxbai-embed-large-v1", not the ~46MB
    # all-minilm), pushing ingestion past run_bot.sh's own rules-mcp
    # readiness timeout.
    CURRENT_EMBED_MODEL="$(get_env_var EMBEDDING_MODEL "$(py 'from rules_mcp.settings import Settings; print(Settings.EMBEDDING_MODEL)' 2>/dev/null || echo mxbai-embed-large)")"
    if [[ "${INTERACTIVE}" == true ]]; then
      read -r -p "Ollama embedding model tag [${CURRENT_EMBED_MODEL}]: " model
      EMBED_MODEL="${model:-${CURRENT_EMBED_MODEL}}"
    else
      EMBED_MODEL="${CURRENT_EMBED_MODEL}"
    fi
    set_env_var EMBEDDING_MODEL "${EMBED_MODEL}"
    ok "Embeddings: local via Ollama (${EMBED_MODEL})."
    ;;
esac

# --- Ollama (only if something above actually needs it) ---------------------

if [[ "${NEED_OLLAMA}" == true ]]; then
  step "Ollama"
  if ! command -v ollama >/dev/null 2>&1; then
    err "'ollama' is not installed or not in PATH."
    info "Install it before continuing: curl -fsSL https://ollama.com/install.sh | sh"
    exit 1
  fi

  if curl -s "${OLLAMA_URL}/api/version" >/dev/null 2>&1; then
    ok "Already running on ${OLLAMA_URL}."
  else
    ./scripts/run_ollama.sh > ollama.log 2>&1 &
    printf '  Starting (pid %s), waiting for it to be ready...' "$!"
    ready=false
    for _ in $(seq 1 30); do
      if curl -s "${OLLAMA_URL}/api/version" >/dev/null 2>&1; then
        ready=true
        break
      fi
      sleep 1
    done
    if [[ "${ready}" == true ]]; then
      echo " ready."
    else
      echo ""
      err "Ollama failed to start on ${OLLAMA_URL}. Check ollama.log for details."
      exit 1
    fi
  fi

  pull_model() {
    local tag="$1"
    echo "  Pulling ${tag}..."
    OLLAMA_HOST="${OLLAMA_URL#http://}" ollama pull "${tag}"
    if [[ "${tag}" == *:cloud ]]; then
      warn "'${tag}' is an Ollama cloud model -- inference runs on Ollama's"
      info "  infrastructure, not this host. Sign in once if you haven't:"
      info "      OLLAMA_HOST=${OLLAMA_URL#http://} ollama signin"
    fi
  }

  [[ "${LLM_PROVIDER:-local}" == "local" ]] && pull_model "${LLM_MODEL}"
  [[ -n "${EMBED_MODEL:-}" ]] && pull_model "${EMBED_MODEL}"
  ok "Models ready."
else
  step "Ollama"
  info "Skipped -- both providers above are hosted, so no local Ollama"
  info "instance is needed for this configuration."
fi

step "Local data directories"
mkdir -p data/pdf_parser data/chroma data/conversations
ok "data/pdf_parser, data/chroma, data/conversations ready."

# --- Deployment shape ---------------------------------------------------

step "Deployment shape"
FULL_DEPLOYMENT=false
if [[ "${INTERACTIVE}" == true ]]; then
  info "Local dev only -- rules-mcp/scryfall-mcp/searxng in Docker, the"
  info "                  backend runs directly on this host (./run_bot.sh),"
  info "                  reachable at http://localhost:8000. No Caddy, no"
  info "                  webapp, no public exposure."
  info "Full deployment -- adds Caddy, which serves the built web app and"
  info "                  reverse-proxies the API on one public-facing"
  info "                  origin (needed for the PWA, a Cloudflare Tunnel,"
  info "                  or direct TLS). The webapp is baked into the same"
  info "                  image as Caddy, so the two ship together."
  read -r -p "Use [D]ev-only or [F]ull deployment? [D]: " choice
  choice="${choice:-d}"
  [[ "${choice,,}" == "f" ]] && FULL_DEPLOYMENT=true
fi

DISCORD_ENABLED=false
if [[ "${FULL_DEPLOYMENT}" == true && "${INTERACTIVE}" == true ]]; then
  step "Discord bot (optional)"
  info "Independent of Caddy/webapp -- it's a separate container that calls"
  info "the public API over HTTP and never needs to be publicly reachable"
  info "itself (Discord pushes it events over an outbound connection it"
  info "opens itself)."
  read -r -p "Enable the Discord bot? [y/N]: " choice
  if [[ "${choice,,}" == "y" ]]; then
    DISCORD_ENABLED=true
    while true; do
      read -r -s -p "Discord bot token: " token; echo
      [[ -n "${token}" ]] && break
      warn "A bot token is required to enable the Discord bot."
    done
    set_env_var DISCORD_BOT_TOKEN "${token}"

    current_discord_key="$(get_env_var DISCORD_API_KEY "")"
    if [[ -n "${current_discord_key}" ]]; then
      discord_key="${current_discord_key}"
      info "Reusing existing DISCORD_API_KEY."
    else
      discord_key="$("${VENV_DIR}/bin/python" -c 'import secrets; print(secrets.token_hex(24))')"
      info "Generated a dedicated DISCORD_API_KEY (tracks the bot's usage"
      info "separately from the keyless/anonymous tier)."
    fi
    set_env_var DISCORD_API_KEY "${discord_key}"
    append_env_csv_value API_KEYS "${discord_key}"

    read -r -p "Public API base URL the bot should call [https://azor.delta43.net]: " api_base
    set_env_var DISCORD_API_BASE_URL "${api_base:-https://azor.delta43.net}"
    ok "Discord bot configured. Restrict it to specific servers/channels"
    info "later via DISCORD_ALLOWED_GUILD_IDS/DISCORD_ALLOWED_CHANNEL_IDS in .env."
  fi
fi

# --- Summary --------------------------------------------------------------

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  COMPOSE="docker compose"
fi

step "Setup complete"
info "Chat:       ${LLM_PROVIDER:-local}$([[ "${LLM_PROVIDER:-local}" == local ]] && printf ' (%s)' "${LLM_MODEL:-}")"
info "Embeddings: $(get_env_var EMBEDDING_PROVIDER local)$([[ "$(get_env_var EMBEDDING_PROVIDER local)" == local ]] && printf ' (%s)' "${EMBED_MODEL:-}")"
info "Everything above lives in .env (not committed) -- to switch providers"
info "later, edit .env and restart the affected process(es). No code changes"
info "needed either way."
echo ""

if [[ "${FULL_DEPLOYMENT}" == true ]]; then
  echo "Next: bring up the full stack (rules-mcp/scryfall-mcp/searxng pull in"
  echo "automatically via depends_on):"
  echo ""
  if [[ "${DISCORD_ENABLED}" == true ]]; then
    echo "    ${COMPOSE} --profile discord up -d --build mtg-judge caddy discord-bot"
  else
    echo "    ${COMPOSE} up -d --build mtg-judge caddy"
  fi
  echo ""
  echo "Caddy will be reachable on :80/:443. For real public exposure without"
  echo "opening a port, see docs/DESCRIPTION.md's Cloudflare Tunnel section"
  echo "(--profile tunnel) -- not part of this installer."
else
  echo "Next:"
  echo ""
  echo "    ./run_bot.sh"
  echo ""
  echo "This starts rules-mcp/scryfall-mcp/searxng via ${COMPOSE}, then runs"
  echo "the backend directly on this host at http://localhost:8000."
fi
