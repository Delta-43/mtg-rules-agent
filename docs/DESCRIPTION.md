# MTG Azor — Full Project Description

This is the comprehensive technical reference: architecture, configuration,
deployment, and operations, all in one place. `README.md` (repo root) is the
short, visual introduction; `docs/FEATURES.md` is the feature-by-feature
verification catalog; `docs/PLAN.md`/`docs/TODO.md` track what's done and
what's next; `docs/PUBLISHING_PLAN.md` covers the dual-product (self-hosted
+ hosted) publishing strategy. Each module (`server/`, `discord_client/`,
`webapp/`, `ops/`, `shared/`, and `server/rules_mcp/`/`server/scryfall_mcp/`/
`server/accounts_db/` within it) has its own README for day-to-day work
inside that piece — this file is the cross-cutting picture that ties them
together, not a duplicate of any of them.

---

## 1. What the project does

MTG Azor is an AI assistant for **Magic: The Gathering** rules questions,
available as a web app, a Discord bot, or directly over HTTP. At answer
time, a tool-calling agent decides for itself which of the following to
consult, in what order:

1. Official Comprehensive Rules content, retrieved semantically from a
   local ChromaDB index (via `rules-mcp`).
2. Live Scryfall card data — oracle text, legality, pricing, sets,
   deckbuilding helpers — via the `scryfall-mcp` server.
3. Official Scryfall rulings for a specific card, via `scryfall-mcp`'s
   `get_card_rulings` tool (added locally — the one gap in upstream's tool
   set; see §5.4).
4. Public web search (self-hosted SearXNG + content extraction), used only
   for interactions that are ambiguous, contested, or not resolved by 1–3.
5. A pluggable LLM (Ollama — local weights or an Ollama cloud model — or a
   hosted model via OpenRouter) that reasons over the tool results and
   produces the final, cited answer.

Every final answer is required (by the agent's system prompt, and verified
in code — see `CLAUDE.md`'s citation-verification section) to end with a
citation block: rule numbers used, official rulings used, and source URLs
if web search was used. If the agent can't ground part of an answer in a
tool result, it's instructed to say so rather than guess.

The service is exposed over HTTP with FastAPI (CORS, API-key auth, rate
limiting), and currently sits behind two real client surfaces — a React
PWA and a Discord bot — with the API itself reusable by any other client.

### Design goals

| Goal | How it is met |
|---|---|
| Grounded, cited answers | Agent's system prompt requires a citation block; code-level safety nets both add missing-but-real citations and prune ones the answer never actually discusses — never answer from memory alone |
| Runs local-first or public | Pluggable LLM provider (Ollama, local or cloud, vs. hosted OpenRouter); no code path assumes local-only |
| Don't duplicate existing OSS | Card data delegated to a local fork of an actively maintained Scryfall MCP server instead of a bespoke wrapper; only the one gap in its tool set (rulings) was added locally |
| Rules retrieval is a reusable asset | `server/rules_mcp/` is self-contained (no imports from the rest of this repo) so it can be lifted into its own repo |
| Reproducible, self-hosted deployment | docker-compose with a Caddy reverse proxy for TLS |
| Modular for a growing team | `server/`, `discord_client/`, `webapp/`, `ops/` split with per-module READMEs and `.github/CODEOWNERS` |

---

## 2. Architecture

Two operational phases:

1. **Offline preparation** (owned entirely by `rules-mcp`, runs
   automatically on container boot): download and parse the MTG rules PDF
   into hierarchical JSON, then chunk and embed it into ChromaDB.
2. **Online serving**: accept a chat query; the agent decides which
   tool(s) to call — `search_rules`, one or more of `scryfall-mcp`'s 16
   tools (including `get_card_rulings`), and/or `web_search` — calling
   more than one in sequence based on what earlier results return; produce
   a final answer with a required citation block built from the tool
   calls actually made, not a hand-set flag.

```text
Client (webapp/ PWA, discord_client/ bot) -> Caddy -> FastAPI (server/app_api/main.py)
                                                    -> tool-calling agent (server/llm_agent/agent.py)
                                                       |-- rules-mcp (MCP, HTTP): search_rules, get_rule_by_id
                                                       |-- scryfall-mcp (MCP, HTTP): search_cards, get_card, get_card_rulings, ...
                                                       `-- web_search (in-process @tool: SearXNG + trafilatura)
```

See the root `README.md` for the same picture as a Mermaid diagram.

---

## 3. Component layout

Reorganized (September 2026) into four top-level modules plus `shared/` —
see `docs/PUBLISHING_PLAN.md` for the reasoning behind the split.

- **`server/`** — the backend product:
  - `app_api/` — FastAPI app lifecycle, HTTP endpoints, CORS, API-key
    auth, rate limiting, aggregate health check across the MCP servers.
  - `llm_agent/` — the tool-calling agent (`agent.py`), the pluggable LLM
    factory (`llm_provider.py`), and the `web_search` tool
    (`web_search_tool.py`).
  - `core_config/` — canonical configuration loader for the main backend
    (YAML-first, env-override).
  - `accounts_db/` — SQLAlchemy models + Alembic migration for the future
    accounts/tiers/billing pivot (Phase 0 scaffolding, not wired in yet —
    see `docs/PLAN.md`).
  - `rules_mcp/` — standalone MCP server: rules PDF acquisition,
    hierarchical parsing, ChromaDB ingestion, `search_rules`/
    `get_rule_by_id` tools. Self-contained; own
    [README](../server/rules_mcp/README.md).
  - `scryfall_mcp/` — a local fork of
    [bmurdock/scryfall-mcp](https://github.com/bmurdock/scryfall-mcp)
    (MIT), vendored directly into this repo so it can be modified — which
    it has been, to add `get_card_rulings` as a 16th native tool (§5.4).
  - `searxng/` — config for the self-hosted metasearch instance backing
    `web_search`.
  - `tests/` — pytest suite covering `app_api`'s routes.
- **`discord_client/`** — thin `discord.py` client calling the public
  `/chat` API. Named `discord_client`, not `discord`, deliberately — a
  bare `discord/` directory at the repo root would shadow the real
  `discord.py` library on any host-run invocation.
- **`webapp/`** — React + Vite PWA, built into the `caddy` image and
  served same-origin with the API.
- **`ops/`** — R2 backup/restore scripts with their own lightweight image
  (no LangChain dependency); future home for monitoring/alerting config.
- **`shared/`** — cross-module committed source assets (brand art, design
  reference) — deliberately not inside `data/`, which is gitignored
  runtime state with nothing in common with these.

Runtime data lives under `data/` (gitignored, at the repo root, not inside
`server/`), owned by `rules-mcp` and the conversation memory layer:

- `data/pdf_parser` — rules PDF + parsed JSON artifacts.
- `data/chroma` — persisted vector index.
- `data/conversations` — SQLite conversation memory + usage counters.

---

## 4. Configuration model

Configuration is **YAML-first** using `server/project_config.yml` for the
main backend, with environment variables overriding YAML values.

- `llm_provider`: `provider` (`local`/`hosted`), `openrouter_model`,
  `openrouter_base_url` (key itself is env-only: `OPENROUTER_API_KEY`).
- `mcp`: `rules_url`, `scryfall_url`.
- `web_search`: `searxng_url`, `max_results`, `fetch_top_n`.
- `server`: `host`/`port`, `cors_allowed_origins`, `api_keys`,
  `rate_limit_per_minute`.

`rules_mcp` is configured entirely via its own environment variables (no
YAML) — see its README — since it's meant to be extractable as an
independent project.

Key implementation files:

- `server/core_config/settings.py` — main backend's config resolution and
  typed coercion (reads `server/project_config.yml` directly, with env
  vars overriding YAML values — no separate export step, in or out of
  Docker).
- `server/rules_mcp/settings.py` — rules-mcp's independent, env-var-only
  settings.
- `server/scripts/docker_entrypoint.sh` — main backend's container
  startup bootstrap: resolves `HOST`/`PORT` via `core_config.Config` and
  execs uvicorn.

### Full environment variable reference

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11435` | Dedicated Ollama instance endpoint |
| `LLM_MODEL` | `gemma4:cloud` | Chat model (when `LLM_PROVIDER=local`); an Ollama cloud model tag or a local weights tag |
| `EMBEDDING_MODEL` | `mxbai-embed-large` | Local embedding model (used by `rules-mcp` when `EMBEDDING_PROVIDER=local`) |
| `EMBEDDING_PROVIDER` | `local` | `rules-mcp`'s embedding provider: `local` (Ollama) or `hosted` (OpenRouter) — see `server/rules_mcp/README.md`'s "Embedding provider" section |
| `OPENROUTER_EMBEDDING_API_KEY` | *(none)* | Required when `EMBEDDING_PROVIDER=hosted` — a separate key from `OPENROUTER_API_KEY` below on purpose |
| `OPENROUTER_EMBEDDING_MODEL` | `baai/bge-m3` | Hosted embedding model id |
| `LLM_REASONING` | `false` | Disable model "thinking" traces |
| `LLM_NUM_PREDICT` | `2048` | Max answer tokens |
| `LLM_NUM_CTX` | `8192` | Context window |
| `LLM_PROVIDER` | `local` | `local` (Ollama, incl. cloud models) or `hosted` (OpenRouter) |
| `OPENROUTER_API_KEY` | *(none)* | Required when `LLM_PROVIDER=hosted` |
| `OPENROUTER_MODEL` | `openrouter/auto` | Hosted model id |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Shared by both the chat and embedding hosted providers |
| `RULES_MCP_URL` | `http://localhost:8100/mcp` | rules-mcp endpoint |
| `SCRYFALL_MCP_URL` | `http://localhost:3000/mcp` | scryfall-mcp endpoint |
| `SEARXNG_URL` | `http://localhost:8080` | SearXNG endpoint for `web_search` |
| `SCRYFALL_USER_AGENT` | `MTG-Judge-Chatbot/1.0 (+https://github.com/mtg-judge)` | Sent to Scryfall by scryfall-mcp |
| `CORS_ALLOWED_ORIGINS` | *(empty = disabled)* | Comma-separated origin allowlist |
| `API_KEYS` | *(empty = disabled)* | Comma-separated valid `X-API-Key` values. A request with no key at all is still allowed (anonymous tier) — this list only validates keys that ARE presented |
| `RATE_LIMIT_PER_MINUTE` | `20` | Per API-key/IP rate limit on `/chat`, `/chat/stream` |
| `DAILY_QUOTA_ANONYMOUS` | `30` | Daily request cap for keyless (anonymous-tier) callers |
| `DAILY_QUOTA_AUTHENTICATED` | `500` | Daily request cap for callers with a valid `X-API-Key` |
| `CONVERSATION_DB_PATH` | `data/conversations/conversations.db` | SQLite file backing multi-turn conversation memory |
| `VITE_API_BASE_URL` | *(empty)* | Build-time only, read by `webapp/Dockerfile`. Empty = same-origin deploy; set only if the frontend is built to call a backend on a different origin |
| `CLOUDFLARE_TUNNEL_TOKEN` | *(none)* | `cloudflared`'s connector token — only read under `docker-compose --profile tunnel` |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | *(none)* | R2 credentials for `ops/backup_to_r2.py`/`ops/restore_from_r2.py` — only read under `--profile backup` or a manual `docker compose run` |
| `R2_BACKUP_INTERVAL_SECONDS` | `3600` | How often the `backup` profile snapshots `data/` to R2 |
| `DISCORD_BOT_TOKEN` | *(none)* | Bot token from the Discord Developer Portal — only read under `--profile discord` |
| `DISCORD_API_KEY` | *(none)* | Dedicated `API_KEYS` entry for the bot's own calls |
| `DISCORD_API_BASE_URL` | `https://azor.delta43.net` | Public backend URL the bot calls — deliberately not an internal Docker service name |
| `DISCORD_ALLOWED_GUILD_IDS` | *(empty = any server)* | Comma-separated guild IDs to restrict `/judge` to |
| `DISCORD_ALLOWED_CHANNEL_IDS` | *(empty = any channel)* | Comma-separated channel IDs to restrict `/judge` to within an allowed guild |
| `DISCORD_COOLDOWN_SECONDS` | `10` | Per-user cooldown on `/judge` |

---

## 5. Main modules

### 5.1 API surface (`server/app_api/main.py`)

- `GET /health` — reports LLM provider, agent readiness, and whether
  `rules-mcp`/`scryfall-mcp` are reachable.
- `POST /chat` — judge response endpoint, async end-to-end, rate-limited,
  gated by `X-API-Key` when `API_KEYS` is configured (tiered: anonymous
  vs. authenticated, see §7).
- `POST /chat/stream` — same request body, Server-Sent Events response
  (`event: token` repeated, one `event: sources`, then `event: done` or
  `event: error`).
- Lifespan startup builds the agent once (constructs the MCP client,
  loads tools, builds the chat model) and fails fast if
  `LLM_PROVIDER=hosted` without an API key.

### 5.2 Tool-calling agent (`server/llm_agent/agent.py`)

- Builds the LLM via `llm_provider.build_chat_model()`.
- Loads MCP tools from `rules-mcp` and `scryfall-mcp` via
  `langchain-mcp-adapters`'s `MultiServerMCPClient`, and adds
  `get_card_rulings` and `web_search` in-process.
- Wires everything into a `langchain.agents.create_agent` tool-calling
  graph with a system prompt that requires tool-grounded answers and a
  citation block.
- Parses the agent's tool-call history back into a structured `sources`
  object (`rules`, `rulings`, `web_links`, `images`) instead of hand-set
  flags — see `CLAUDE.md` for the citation-verification/pruning safety
  nets and the several formatting-hardening fixes (off-topic refusal,
  citation-block dedup, cross-turn leakage, LaTeX/heading artifacts,
  repetition, self-correction) found via real Discord/PWA usage.

### 5.3 Rules MCP server (`server/rules_mcp/`)

- `parser.py` — finds/downloads the latest rules PDF, parses the
  chapter/section/rule/subrule hierarchy into JSON.
- `ingestor.py` — chunks and embeds the parsed rules into ChromaDB,
  incrementally (only re-embeds rules whose content hash changed).
- `server.py` — exposes `search_rules`/`get_rule_by_id` as MCP tools over
  Streamable HTTP, plus a `/health` route; re-ingests automatically on
  boot only when the rules PDF changed or a marker file is missing.

Full detail (embedding provider switching, ingestion concurrency,
migration gotchas) in [`server/rules_mcp/README.md`](../server/rules_mcp/README.md)
and `CLAUDE.md`.

### 5.4 Scryfall tools (`server/scryfall_mcp/`)

A local fork of upstream's server — search, card lookup, pricing, sets,
deckbuilding, synergy, format-staples, and more (15 tools, unmodified from
upstream) plus `get_card_rulings` (`src/tools/get-card-rulings.ts`), added
locally to call the real
[Scryfall Rulings API](https://scryfall.com/docs/api/rulings) — the one
gap in upstream's tool set. See
[`server/scryfall_mcp/README.md`](../server/scryfall_mcp/README.md).

### 5.5 Web search (`server/llm_agent/web_search_tool.py`)

Queries a self-hosted SearXNG instance's JSON API, fetches and extracts
(`trafilatura`) the top few result pages for real content instead of thin
snippets, falling back to the snippet if extraction fails. Used by the
agent only when rules/rulings tools don't resolve the question.

### 5.6 Discord bot (`discord_client/`)

"Azor, High Arbiter" — a single `/judge` slash command calling the public
`/chat` API (never `/chat/stream`; coalescing streamed tokens into
Discord message edits fights Discord's own edit rate limits). Renders
mana symbols as real Discord application emojis and tables as branded
embeds. Full detail in
[`discord_client/README.md`](../discord_client/README.md) and `CLAUDE.md`'s
Discord bot section.

### 5.7 Web app (`webapp/`)

React + Vite PWA, SSE streaming chat UI, `conversation_id` persisted
client-side for multi-turn continuity. Same-origin deploy by default (no
CORS needed). Full detail in
[`webapp/README.md`](../webapp/README.md); the in-progress visual redesign
is tracked in `docs/WEBAPP_PLAN.md`.

---

## 6. Deployment

### Local (hybrid dev)

```bash
./setup.sh   # venv, deps, dedicated Ollama instance + model pulls
./run_bot.sh # docker compose up rules-mcp/scryfall-mcp/searxng, then host uvicorn
```

`run_bot.sh` runs the FastAPI backend directly on the host (`PYTHONPATH=server`,
not `cd server` — see `server/README.md` for why cwd matters for
`data/`-relative config defaults) for fast iteration, while `rules-mcp`,
`scryfall-mcp`, and `searxng` run in Docker with loopback-only ports.

### Full stack (Docker)

```bash
docker-compose up --build
```

Starts `mtg-judge`, `rules-mcp`, `scryfall-mcp`, `searxng`, and `caddy`.
`caddy` serves the built PWA (`webapp/`) as static assets and
reverse-proxies `/chat*`/`/health` to `mtg-judge` — one origin, no CORS
configuration needed for the primary deploy. Only `caddy` publishes a
public port; everything else is internal to the `mtg-network` Docker
network (though `rules-mcp`/`scryfall-mcp`/`searxng` are also bound to
`127.0.0.1` for the hybrid-dev workflow above).

For a real domain with automatic TLS *and* a directly exposed port
80/443, edit `Caddyfile` and replace the `:80` block with your domain. For
a Cloudflare Tunnel instead (no port needs to be open at all), see below
and leave `Caddyfile` on plain `:80`, since TLS terminates at Cloudflare's
edge in that case.

### Cloudflare Tunnel (opt-in: `--profile tunnel`)

Exposes the stack at a real domain with TLS terminated at Cloudflare's
edge, without opening any port on the host:

1. In the Cloudflare Zero Trust dashboard, create a tunnel and add a
   public hostname pointing at `http://localhost:80` (or wherever
   `caddy`'s port is actually mapped on this host — check
   `docker port mtg-caddy` if a local `docker-compose.override.yml`
   remaps it, e.g. because something else already owns 80/443).
2. Copy the tunnel's **connector token** (the long `eyJ...` string, not
   the tunnel UUID) into `CLOUDFLARE_TUNNEL_TOKEN` in `.env`.
3. `docker-compose --profile tunnel up -d --build`

### R2 backup (opt-in: `--profile backup`)

Periodically snapshots conversation memory and the rules index to a
Cloudflare R2 bucket, so state survives a VPS rebuild:

1. Create an R2 bucket and API token (Cloudflare dashboard → R2 → Manage
   API Tokens).
2. Set `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
   `R2_BUCKET` in `.env`.
3. `docker-compose --profile backup up -d`

Writes a single overwritten "latest" snapshot (`ops/backup_to_r2.py`) —
enable R2 bucket versioning if you want point-in-time history instead.
To restore (**stop `mtg-judge`/`rules-mcp` first**):

```bash
docker compose stop mtg-judge rules-mcp
docker compose run --rm r2-backup python restore_from_r2.py       # dry run
docker compose run --rm r2-backup python restore_from_r2.py --yes # actually restores
docker compose up -d mtg-judge rules-mcp
```

Profiles combine: `docker-compose --profile tunnel --profile backup up -d --build`.

### Discord bot (opt-in: `--profile discord`)

1. Register an application in the
   [Discord Developer Portal](https://discord.com/developers/applications),
   add the `applications.commands` OAuth2 scope, copy its bot token.
2. Set `DISCORD_BOT_TOKEN` and a dedicated `DISCORD_API_KEY` in `.env`.
3. `docker-compose --profile discord up -d --build discord-bot`

Not attached to `mtg-network` — it only needs outbound access to
Discord's gateway and to the backend's public URL, same as any other
external client. Full setup/branding detail in
[`discord_client/README.md`](../discord_client/README.md).

---

## 7. API reference

**Health check:**
```bash
curl http://localhost:8000/health
```

**Chat:**
```bash
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"query": "What happens during the untap step?"}'
```

Response: `{"answer": "...", "sources": {"rules": [...], "rulings": [...], "web_links": [...], "images": [...]}, "conversation_id": "..."}`.
`sources` is built from the tools the agent actually called; `images`
comes from `get_card`'s default image URL, populated whenever the agent
looks up a specific card. Pass `conversation_id` back on the next request
to continue that thread; omit it to start fresh — conversations persist
in SQLite (`CONVERSATION_DB_PATH`) via a LangGraph checkpointer.

**Streaming chat** (SSE, token-by-token):
```bash
curl -N -X POST http://localhost:8000/chat/stream -H "Content-Type: application/json" \
  -d '{"query": "What happens during the untap step?"}'
```

**Auth is tiered, not all-or-nothing.** No `X-API-Key` = anonymous tier
(lower daily quota, keyed by IP — for a public frontend that can't keep a
key secret). A presented key must be valid (`401` if not) = authenticated
tier (higher daily quota, keyed by the key). Each tier has its own daily
quota on top of the existing per-minute rate limit. `query` is capped at
2000 characters (`422` if exceeded).

---

## 8. Project structure

```
mtg_local_chatbot/
├── server/                   # Backend product -- see server/README.md
│   ├── app_api/ llm_agent/ core_config/ accounts_db/
│   ├── rules_mcp/ scryfall_mcp/ searxng/ tests/
│   └── Dockerfile requirements.txt project_config.yml
├── discord_client/           # discord.py bot client -- see discord_client/README.md
├── webapp/                   # React + Vite PWA -- see webapp/README.md
├── ops/                       # R2 backup/restore + future monitoring -- see ops/README.md
├── shared/                    # Cross-module source assets -- see shared/README.md
├── docs/                      # This file, FEATURES.md, PLAN.md, TODO.md, PUBLISHING_PLAN.md, WEBAPP_PLAN.md
├── data/                      # Runtime state only (gitignored)
├── setup.sh run_bot.sh stop_bot.sh
├── docker-compose.yml Caddyfile
├── scripts/run_ollama.sh
└── .github/CODEOWNERS
```

---

## 9. Troubleshooting

**`./run_bot.sh` exits with `127`** — usually a broken venv executable
path (often after renaming `venv` to `.venv`):
```bash
rm -rf .venv && python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r server/requirements.txt
```

**API starts but requests fail or hang:**
```bash
curl -s http://localhost:8000/health          # aggregate health
curl -s http://localhost:11435/api/version    # Ollama
curl -s http://localhost:8100/health          # rules-mcp
curl -s http://localhost:3000/health          # scryfall-mcp
curl -s http://localhost:8080/                # searxng
```
If using an Ollama cloud model (`*:cloud`), confirm sign-in
(`OLLAMA_HOST=localhost:11435 ollama signin`) — an unsigned-in instance
returns `401` on the first real chat request even though the model
*pulled* successfully (pulling only fetches a manifest, not weights).

**Answers are slow or truncated** — lower `llm.num_predict`/`llm.num_ctx`
in `server/project_config.yml`; keep `llm.reasoning: false` unless you
want longer reasoning traces; for a local (non-cloud) model, tool-calling
reliability varies a lot by model size — prefer `hosted` mode or an
Ollama cloud model for consistency.

**Docker cannot reach Ollama** — confirm the dedicated Ollama instance is
bound to `0.0.0.0`, not `127.0.0.1` (see `scripts/run_ollama.sh`); a
loopback-only bind is unreachable from a container even if it works fine
from the host shell.

**GPU driver hangs on Ollama's automatic offload detection** — a
driver-level `ollama serve` concern independent of this project; see
[Ollama's troubleshooting docs](https://docs.ollama.com) for disabling GPU
offload (e.g. `OLLAMA_VULKAN=0` for the Vulkan backend).

---

## 10. Performance notes

- `rules-mcp`'s first-boot rules ingestion (~1300 chunks) takes roughly
  8–10 minutes on a mid-range CPU. This only runs the embedding model
  locally — chat inference with the default `gemma4:cloud` model doesn't
  touch local compute at all. Ingestion is incremental after that first
  pass — a later Comprehensive Rules update only re-embeds the rules that
  actually changed.
- A chat query typically involves multiple tool round-trips, so response
  time depends more on how many tools the model decides to call than on
  raw model speed.
- Tool-calling reliability varies significantly by model. The default,
  `gemma4:cloud`, calls tools reliably; small local models are more prone
  to skipping tools they should use or answering from memory instead.

---

## 11. Known limitations (current, not historical)

- No CI/CD yet — verification is functional (running the real stack), not
  automated on every PR. Scoped as Stage 0 in `docs/PUBLISHING_PLAN.md`.
- Tool-calling reliability with smaller/local (non-cloud) models is a
  known tradeoff of model choice, not something a code fix addresses.
- SearXNG's outbound IP can get rate-limited by upstream search engines
  under sustained traffic — best-effort, no mitigation in place.
- Accounts/tiers/billing (Phase 1 onward) hasn't started beyond Phase 0
  scaffolding — see `docs/PLAN.md`.
- The web app's visual redesign (Bun + `mana-font`) is paused pending a
  design direction — see `docs/WEBAPP_PLAN.md`.
- Anonymous-tier abuse mitigation (CAPTCHA/Turnstile) is deferred by
  design until it's actually needed.
