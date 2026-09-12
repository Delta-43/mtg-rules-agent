# server/

The whole product: the FastAPI app, the tool-calling agent, and the two
MCP sub-services it talks to. See the root `CLAUDE.md` for full
architecture detail and the non-obvious "why" behind things; this file is
just the orientation a new contributor to *this* module needs, and
doesn't duplicate that.

**Current status and what's left to do:** see [`STATUS.md`](STATUS.md).

## Layout

- `app_api/` — FastAPI app, HTTP routes (`/chat`, `/chat/stream`,
  `/health`, `/metrics`), CORS, API-key auth, rate limiting.
- `llm_agent/` — the tool-calling agent (`agent.py`), the pluggable LLM
  factory (`llm_provider.py`), the in-process `web_search` tool.
- `core_config/` — this module's own config loader (YAML-first,
  env-override) — reads `project_config.yml` in this same directory.
  `metrics.py` holds shared Prometheus metric definitions.
- `rules_mcp/` — standalone MCP server (semantic search over the MTG
  Comprehensive Rules). **Self-contained by design** — no imports from
  anywhere else in this repo, own `settings.py`/`requirements.txt`/
  `Dockerfile`, so it can be lifted into its own repository unchanged. See
  `rules_mcp/README.md`.
- `scryfall_mcp/` — a local fork of
  [bmurdock/scryfall-mcp](https://github.com/bmurdock/scryfall-mcp) (card
  data, rulings). Also self-contained; own `README.md`/`Dockerfile`/test
  suite (`npm test`).
- `searxng/` — config only (`settings.yml`) for the self-hosted metasearch
  instance backing `web_search`; no code of its own.
- `tests/` — pytest suite covering `app_api`'s routes (`TestClient`, no
  live network calls). Does **not** exercise the agent or either MCP
  server — see the root `CLAUDE.md`'s Commands section for what actually
  verifies those (running the real stack).
- `Dockerfile`, `requirements.txt`, `project_config.yml` — the main
  backend's own build/deps/config, independent of `rules_mcp`'s and
  `scryfall_mcp`'s (each has its own).

## Running

**Full stack (Docker):** from the repo root,
`docker compose up -d --build mtg-judge rules-mcp scryfall-mcp searxng`
(add `caddy` for a reverse-proxy front door — see root `README.md`).
`docker-compose.yml` builds this directory as `mtg-judge`'s image
(`build: ./server`) and `rules_mcp`/`scryfall_mcp` each as their own image
(`build: ./server/rules_mcp`, `build: ./server/scryfall_mcp`).

**Hybrid dev (host-run backend, Dockerized MCP servers):** `./run_bot.sh`
from the repo root — brings up `rules-mcp`/`scryfall-mcp`/`searxng` via
Docker, then runs this module's FastAPI app directly on the host via a
shared `.venv` at the repo root. It sets `PYTHONPATH=server` rather than
`cd`-ing into this directory, specifically so `core_config`'s cwd-relative
defaults (e.g. `CONVERSATION_DB_PATH`'s `data/conversations/...`) still
resolve against the real `data/` directory, which lives at the repo root,
not inside `server/`. If you're invoking `uvicorn`/`pytest`/one-off
`python -c` commands against this module by hand outside those scripts,
set `PYTHONPATH=server` (and keep your cwd at the repo root) rather than
`cd`-ing in, for the same reason.

**Tests:** `python -m pytest server/tests/` from the repo root (or
`cd server && python -m pytest tests/` — either works; see above for why
cwd matters for the *app*, not for pytest itself here since these tests
don't touch `data/`).

**`rules_mcp`/`scryfall_mcp` standalone:** each is genuinely independent —
see their own READMEs. `rules_mcp`'s `python -m rules_mcp.server` needs
its cwd to be `server/` (its parent directory) since `rules_mcp` resolves
as a Python package from there, same reasoning as the `PYTHONPATH=server`
note above.
