# MTG Azor — Full Project Description

This is the comprehensive technical reference: architecture, configuration,
deployment, and operations, all in one place. `README.md` (repo root) is
the short, visual introduction. `server/` (and `server/rules_mcp/`/
`server/scryfall_mcp/` within it) has its own README for day-to-day work
inside that piece — this file is the cross-cutting picture that ties them
together, not a duplicate of it. `server/` also has a `STATUS.md` alongside
its README — a short, consistently-structured snapshot (current
status/features, what's left to do) for a developer who just wants
"where does this stand right now."

This repo is the reply server only: the agent, the API, and the rules/card
data tools. It ships no fixed client — build your own (web, Discord,
Telegram, CLI, anything) against the HTTP API described in §7.

---

## 1. What the project does

MTG Azor is an AI assistant for **Magic: The Gathering** rules questions,
served directly over HTTP. At answer time, a tool-calling agent decides
for itself which of the following to consult, in what order:

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
limiting) so any client can talk to it — the API itself is the product.

### Design goals

| Goal | How it is met |
|---|---|
| Grounded, cited answers | Agent's system prompt requires a citation block; code-level safety nets both add missing-but-real citations and prune ones the answer never actually discusses — never answer from memory alone |
| Runs local-first or public | Pluggable LLM provider (Ollama, local or cloud, vs. hosted OpenRouter); no code path assumes local-only |
| Don't duplicate existing OSS | Card data delegated to a local fork of an actively maintained Scryfall MCP server instead of a bespoke wrapper; only the one gap in its tool set (rulings) was added locally |
| Rules retrieval is a reusable asset | `server/rules_mcp/` is self-contained (no imports from the rest of this repo) so it can be lifted into its own repo |
| Reproducible, self-hosted deployment | docker-compose with an optional Caddy reverse proxy for TLS |
| Client-agnostic | The product is the API; a frontend is a choice left to whoever deploys it |

---

## 2. Architecture

Two operational phases:

1. **Offline preparation** (owned entirely by `rules-mcp`, runs
   automatically on container boot): download and parse the MTG rules PDF
   into hierarchical JSON, then chunk and embed it into ChromaDB.
2. **Online serving**: accept a chat query; the agent decides which
   tool(s) to call — `search_rules`, `get_rules_chapter` (a deterministic
   full-chapter fetch pre-seeded for questions matching
   `FRAMEWORK_CHAPTER_TRIGGERS`, e.g. counters/replacement effects/state-
   based actions — see `CLAUDE.md`/`server/STATUS.md`), one or more of
   `scryfall-mcp`'s 16 tools (including `get_card_rulings`), and/or
   `web_search` — calling more than one in sequence based on what earlier
   results return; produce a final answer with a required citation block
   built from the tool calls actually made, not a hand-set flag.

```text
Client (yours) -> [Caddy, optional] -> FastAPI (server/app_api/main.py)
                                     -> tool-calling agent (server/llm_agent/agent.py)
                                        |-- rules-mcp (MCP, HTTP): search_rules, get_rule_by_id, get_rules_chapter
                                        |-- scryfall-mcp (MCP, HTTP): search_cards, get_card, get_card_rulings, ...
                                        `-- web_search (in-process @tool: SearXNG + trafilatura)
```

See the root `README.md` for the same picture as a Mermaid diagram.

---

## 3. Component layout

- **`server/`** — the whole product (status: [`server/STATUS.md`](../server/STATUS.md)):
  - `app_api/` — FastAPI app lifecycle, HTTP endpoints, CORS, API-key
    auth, rate limiting, aggregate health check across the MCP servers.
  - `llm_agent/` — the tool-calling agent (`agent.py`), the pluggable LLM
    factory (`llm_provider.py`), and the `web_search` tool
    (`web_search_tool.py`).
  - `core_config/` — canonical configuration loader for the main backend
    (YAML-first, env-override).
  - `rules_mcp/` — standalone MCP server: rules PDF acquisition,
    hierarchical parsing, ChromaDB ingestion, `search_rules`/
    `get_rule_by_id`/`get_rules_chapter` tools. Self-contained; own
    [README](../server/rules_mcp/README.md).
  - `scryfall_mcp/` — a local fork of
    [bmurdock/scryfall-mcp](https://github.com/bmurdock/scryfall-mcp)
    (MIT), vendored directly into this repo so it can be modified — which
    it has been, to add `get_card_rulings` as a 16th native tool (§5.4).
  - `searxng/` — config for the self-hosted metasearch instance backing
    `web_search`.
  - `tests/` — pytest suite covering `app_api`'s routes.

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
| `LLM_MODEL` | `gemma4:cloud` | Chat model (when `LLM_PROVIDER=local`); an Ollama cloud model tag (needs internet + `ollama signin`) or a local weights tag (genuinely offline). Read by the main backend (`core_config`); forwarded to the `mtg-judge` container by `docker-compose.yml` |
| `EMBEDDING_MODEL` | `mxbai-embed-large` | Local embedding model (used by `rules-mcp` when `EMBEDDING_PROVIDER=local`). Read independently by `rules_mcp/settings.py` (a separate env read from `LLM_MODEL` above -- `rules_mcp` doesn't import `core_config`, see its README); forwarded to the `rules-mcp` container by `docker-compose.yml` |
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
| `SCRYFALL_USER_AGENT` | `MTG-Judge-Chatbot/1.0 (+https://github.com/mtg-judge)` | Sent to Scryfall by scryfall-mcp — identify your own deployment here |
| `CORS_ALLOWED_ORIGINS` | *(empty = disabled)* | Comma-separated origin allowlist |
| `API_KEYS` | *(empty = disabled)* | Comma-separated valid `X-API-Key` values. A request with no key at all is still allowed (anonymous tier) — this list only validates keys that ARE presented |
| `RATE_LIMIT_PER_MINUTE` | `20` | Per API-key/IP rate limit on `/chat`, `/chat/stream` |
| `DAILY_QUOTA_ANONYMOUS` | `30` | Daily request cap for keyless (anonymous-tier) callers |
| `DAILY_QUOTA_AUTHENTICATED` | `500` | Daily request cap for callers with a valid `X-API-Key` |
| `CONVERSATION_DB_PATH` | `data/conversations/conversations.db` | SQLite file backing multi-turn conversation memory |

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
- `GET /metrics` — Prometheus-format metrics (`prometheus-fastapi-instrumentator`
  plus a purpose-built `http_streaming_ttft_seconds` histogram for
  `/chat/stream`'s time-to-first-token); not exposed through the optional
  Caddy path (`Caddyfile`'s matcher never lists it), loopback/
  `mtg-network` only.
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
  repetition, self-correction) found via real client usage.

### 5.3 Rules MCP server (`server/rules_mcp/`)

- `parser.py` — finds/downloads the latest rules PDF, parses the
  chapter/section/rule/subrule hierarchy into JSON.
- `ingestor.py` — chunks and embeds the parsed rules into ChromaDB,
  incrementally (only re-embeds rules whose content hash changed).
- `server.py` — exposes `search_rules`/`get_rule_by_id`/`get_rules_chapter`
  as MCP tools over Streamable HTTP, plus a `/health` route; re-ingests
  automatically on boot only when the rules PDF changed or a marker file
  is missing. `get_rules_chapter` is a deterministic full-chapter fetch
  (no similarity ranking) used both directly by the model and pre-seeded
  automatically for questions matching `agent.py`'s
  `FRAMEWORK_CHAPTER_TRIGGERS` — see `CLAUDE.md` for why `search_rules`
  alone can't reliably answer questions that hinge on abstractly-worded
  framework rules (counters, replacement effects, state-based actions).

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
docker compose up -d --build mtg-judge rules-mcp scryfall-mcp searxng
curl http://127.0.0.1:8000/health
```

`mtg-judge` already serves its own zero-build dev test UI at `/` (the same
one `run_bot.sh`'s hybrid workflow uses), plus `/chat`, `/chat/stream`,
`/health`, and `/metrics` — that's the entire product surface; nothing else
to stand up for local use.

If you want a reverse-proxy front door (a real domain/TLS), add `caddy` to
that service list — it's a bare `caddy:2` image (no build step, no
frontend baked in) configured by `Caddyfile`, reachable on
`127.0.0.1:8877` by default:

```bash
docker compose up -d --build mtg-judge rules-mcp scryfall-mcp searxng caddy
```

Edit `Caddyfile` for a real domain and automatic TLS, or put your
own tunnel/reverse-proxy of choice in front of `mtg-judge`/`caddy` instead
— nothing here assumes a particular public-exposure mechanism.

### Monitoring

`GET /metrics` is a standard Prometheus-format endpoint on `mtg-judge` —
point any Prometheus (or compatible scraper) at it; no bundled monitoring
stack ships with this repo.

---

## 7. API reference

Everything below also works from a terminal without curl via
`./scripts/chat_cli.py` — a small interactive reference client (streams
tokens, keeps `conversation_id` across turns, prints citations) meant for
trying a self-hosted deployment before writing a real client against this
API. `--no-stream` uses `/chat` instead of `/chat/stream`; `--url`/
`--api-key` (or `$MTG_AZOR_URL`/`$MTG_AZOR_API_KEY`) point it at a
non-default deployment.

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
mtg-rules-agent/
├── server/                   # The whole product -- see server/README.md + STATUS.md
│   ├── app_api/ llm_agent/ core_config/
│   ├── rules_mcp/ scryfall_mcp/ searxng/ tests/
│   └── Dockerfile requirements.txt project_config.yml
├── docs/                      # This file
├── assets/                    # Brand images used by the root README
├── data/                      # Runtime state only (gitignored)
├── setup.sh run_bot.sh stop_bot.sh
├── docker-compose.yml Caddyfile
├── scripts/run_ollama.sh chat_cli.py
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

- Tool-calling reliability with smaller/local (non-cloud) models is a
  known tradeoff of model choice, not something a code fix addresses.
- SearXNG's outbound IP can get rate-limited by upstream search engines
  under sustained traffic — best-effort, no mitigation in place.
- Anonymous-tier abuse mitigation (CAPTCHA/Turnstile) is deferred by
  design until it's actually needed.
