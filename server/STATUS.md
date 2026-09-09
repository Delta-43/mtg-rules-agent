# STATUS — server/

_A per-module snapshot for developers, not a replacement for the full
project docs. See "Related docs" at the bottom for where the deep detail
lives — this file summarizes, it doesn't duplicate._

## 🌍 Project-wide summary

**MTG Azor** is an AI Magic: The Gathering rules judge: a tool-calling
agent that grounds every answer in the Comprehensive Rules, live Scryfall
card data, official rulings, or web search — never from memory — and
cites what it used. It's live in production at `azor.delta43.net`, with
two real client surfaces: a web app (PWA) and a Discord bot
("Azor, High Arbiter"). The codebase is split into independent modules
(`server/`, `discord_client/`, `webapp/`, `ops/`, `shared/`) specifically
so a growing team — a dedicated monitoring/reliability owner plus two
developer/testers — can work on different surfaces without stepping on
each other; see `.github/CODEOWNERS` for who reviews what.

Overall project status: backend, web app, and Discord bot are all **live**.
Accounts/tiers/billing is **planned, not started**; CI/CD is now **live** (see `.github/workflows/`). Observability
(Prometheus metrics + SLO rules, opt-in `--profile monitoring`) is now **live** for the Crawl phase, per `docs/OBSERVABILITY_PLAN_V2.md`. The web
app's visual redesign **shipped 2026-09-09** (a light "paper lightbox" theme — see `webapp/STATUS.md`).

## 📦 This module: server/

The backend product — the FastAPI app, the tool-calling agent, and the
two MCP sub-services it talks to (`rules_mcp/`, `scryfall_mcp/`), plus
`core_config/`, `accounts_db/`, `searxng/` config, and `tests/`. See
[`README.md`](README.md) for setup/run instructions.

### Status: ✅ Live

Serving real production traffic through both the web app and the Discord
bot, 24/7, at `azor.delta43.net`. Currently running `LLM_PROVIDER=local`
(`gemma4:cloud`, the documented default) — a deployment-time `.env`
choice, not a hardcoded requirement.

**2026-09-06: a same-day round trip through both providers, driven by
real production symptoms, not speculation.** Sequence:
1. Switched to `hosted` (OpenRouter) per direct request. Found the
   previously-live `local` config (`LLM_MODEL=qwen3.5:0.8b`) was itself
   broken — not a real pulled Ollama model, silently failing against the
   Ollama Cloud account's session limit. Restored `gemma4:cloud` as the
   `local`-mode default regardless.
2. The first requested OpenRouter model (`google/gemma-4-31b-it:free`)
   was blocked by a BYOK Google AI Studio quota on the OpenRouter
   account; switched to `z-ai/glm-5.3-flash` (previously verified
   working), and the full request surface was re-verified end-to-end
   against it — citations/pruning, multi-turn memory, streaming, tiered
   auth, rate limits, both daily quotas, refusals, and the Discord bot's
   formatting pipeline.
3. **Real users then reported real symptoms**: the Discord bot replying
   very slowly with a formatting glitch, the web app failing outright
   with "Couldn't reach the judge." Investigated via actual production
   logs, not guesses: OpenRouter completions for `z-ai/glm-5.3-flash`
   were taking 10-11 seconds *each*, compounding to ~40s total for a
   multi-tool-call question — confirmed by timestamp gaps in
   `mtg-judge`'s own logs, not inferred. Caddy's logs separately showed
   one real webapp SSE connection aborted 48ms after being proxied
   (`"reading: context canceled"`) from a real visitor, right after that
   slow exchange — no application-level abort logic exists in `webapp`'s
   code to explain a self-cancel that fast, so this reads as a
   client/network-layer event, plausibly related to the backend being
   slow at the time, though not conclusively proven.
4. Checked whether Ollama Cloud's session limit (the reason for step 1)
   had cleared — it had. **Switched back to `local`/`gemma4:cloud`** and
   re-ran the exact same complex real question that was slow on
   OpenRouter: **6.1 seconds**, correct answer, correct citations — roughly
   6-7x faster than the ~40s seen on `z-ai/glm-5.3-flash` minutes earlier.

Net: production is back on the provider with the longest track record of
reliable, fast tool-calling in this project's history. The OpenRouter
path itself is proven to work correctly (verified thoroughly in step 2)
and remains available if `local`/Ollama Cloud ever becomes the
bottleneck again — just not faster today.

### Features

- **Tool-calling agent** (`llm_agent/agent.py`) — decides for itself
  which tools to call, not a fixed if/elif router. Pluggable LLM provider
  (local/cloud Ollama or hosted OpenRouter).
- **Citation verification, not just prompting** — `_verify_unbacked_rule_citations()`
  independently confirms any rule number the model cites via an exact
  lookup tool before it's added to the response; `_prune_unmentioned_rule_citations()`
  removes citations the answer never actually discusses. Both are real
  code-level safety nets, verified against the live model, not just
  requested by the system prompt.
- **Rules retrieval** (`rules_mcp/`) — self-contained MCP server, semantic
  search over the Comprehensive Rules via a local ChromaDB index that
  self-refreshes from wizards.com on boot, with incremental (not
  full-rebuild) re-ingestion.
- **Framework-chapter pre-fetch, not just semantic search** — found live
  during beta: some rulings (e.g. "does Doubling Season double a
  planeswalker's ETB loyalty?") flipped between correct and incorrect
  answers across separate runs of the identical question. Root cause,
  confirmed by direct measurement against the live index: the governing
  rule (122.6) is worded too abstractly (no card/keyword vocabulary) for
  `search_rules` to ever surface it -- it ranked 974th of 1172 rules by
  embedding similarity, and still missed even a re-ranked top-4 within its
  own 9-rule chapter. An LLM-based "is this enough context?" verifier step
  was prototyped and measured, but rejected: it taxes every single query
  (not just the ones that need it) and, being an LLM call itself, wasn't
  even reliable -- it named a different, less-useful chapter across
  repeated runs of the same question. The shipped fix
  (`FRAMEWORK_CHAPTER_TRIGGERS`/`_framework_chapters_for()` in
  `llm_agent/agent.py`, `get_rules_chapter` in `rules_mcp/server.py`) is
  fully deterministic instead: a small static keyword→chapter map checked
  against the raw question (zero tokens, zero latency); on a match, the
  entire chapter is pre-seeded into the conversation as a completed tool
  call before the model's own reasoning starts, so there's no risk of a
  ranked top-k cutoff dropping the one rule that matters -- and no extra
  LLM round-trip, since the model's normal single generation just
  continues from there. Unrelated questions pay nothing extra. Verified
  live against the real `/chat` and `/chat/stream` endpoints, 5/5 runs
  correct with the right citation, no change to unrelated queries. Ships
  with a small, deliberately conservative chapter set (122 Counters, 614
  Replacement Effects, 615 Prevention Effects, 616 Interaction of
  Replacement/Prevention Effects, 613 Interaction of Continuous Effects/
  layers, 704 State-Based Actions, 604 Static Abilities, 117 Timing and
  Priority, 101 Golden Rules) -- a citation-frequency analysis over the
  whole rules corpus surfaced further candidates (603 Triggered Abilities,
  707 Copying Objects, 608 Resolving Spells/Abilities, 601 Casting Spells,
  113 Abilities, 400 Zones) deliberately left out of this pass since
  they're large enough (~3-5.5k tokens each) that adding them without
  evidence of a real gap would raise cost for no proven benefit -- meant to
  be grown from real beta chat-log volume once that's set up, not guessed
  at further ahead of data.
- **Card data** (`scryfall_mcp/`) — a local fork of upstream's Scryfall
  MCP server (16 tools total, including a locally-added `get_card_rulings`
  closing the one gap in upstream's tool set).
- **Web search fallback** (`llm_agent/web_search_tool.py`) — self-hosted
  SearXNG + content extraction, used only when rules/rulings tools can't
  resolve a question.
- **API** (`app_api/`) — `/chat`, `/chat/stream` (SSE), `/health`; tiered
  auth (anonymous vs. authenticated `X-API-Key`), per-minute rate limiting
  plus daily quotas, multi-turn conversation memory via a LangGraph
  SQLite checkpointer. Anonymous buckets by real client IP (`_client_ip()`,
  preferring Cloudflare's `CF-Connecting-IP`), not the proxy's — fixed
  2026-09-06 after finding every anonymous visitor previously shared one
  bucket (Caddy's own bridge IP); see `docs/FEATURES.md`'s H4 entry. The
  fix's own trust assumption (Caddy reachable only through the tunnel) is
  also closed — Caddy's host port binding was narrowed to
  `127.0.0.1`-only (see `docs/TODO.md`), not left as an open firewall
  question.
- **Several real hardening fixes** found via live Discord/PWA usage, all
  in the shared agent so every caller benefits: off-topic-question
  refusal, duplicate-citation-block stripping, cross-turn citation
  leakage fix (Discord's per-channel memory scoping), LaTeX/markdown-heading
  cleanup, degenerate-repetition truncation, mid-answer self-correction
  suppression. Full detail in `CLAUDE.md`.
- **`accounts_db/`** — SQLAlchemy models + Alembic migration for the
  future accounts/tiers/billing pivot. Phase 0 scaffolding only, verified
  live (tables create/drop correctly against a real Postgres instance)
  but **not imported by `app_api` yet** — no live request path touches it.
- **CI** (`.github/workflows/server-ci.yml`) — `pytest` on every PR
  touching this module, plus Docker builds and import smoke tests for
  the `mtg-judge` and `rules-mcp` images.
- **`GET /metrics`** (`prometheus-fastapi-instrumentator` + a purpose-built
  `http_streaming_ttft_seconds` histogram in `core_config/metrics.py`) —
  Crawl-phase observability per `docs/OBSERVABILITY_PLAN_V2.md`, scraped
  by the opt-in `ops/monitoring/` Prometheus service. Per-tool-call
  metrics (`agent_tool_calls_total`) are NOT part of this yet — scoped as
  separate follow-up work; see `CLAUDE.md`.
- **Reachable without `webapp/`** — `mtg-judge` now publishes
  `127.0.0.1:8000` directly in `docker-compose.yml`, and a new
  `caddy-local` service (bare `caddy:2`, no build) gives a proxy front
  door with no dependency on `webapp/`'s Node build at all. `caddy`
  (the main service, PWA baked in) is unchanged — this is additive, not a
  replacement. See `docs/DESCRIPTION.md`'s "Local, webapp-free" section.
  Verified live: `docker compose up -d --build mtg-judge rules-mcp
  scryfall-mcp searxng [caddy-local]`, `/`, `/health`, `/metrics`, and
  `/chat` all responded correctly both directly on `:8000` and proxied
  through `caddy-local`.

### Remaining work

- **`rules_mcp` has no fixture-based regression test for the parser
  itself yet** — today's CI checks that `rules_mcp` imports cleanly, not
  that it parses real rules content correctly. A small-sample-PDF test
  asserting a sane rule count would have caught the historical
  807-vs-1172 silent parsing bug automatically; not yet written (see
  `docs/PUBLISHING_PLAN.md` Stage 0).
- **Branch protection on `main`** requiring CI to pass before merge isn't
  turned on yet — a GitHub repo setting, not something committable.
- **Accounts/tiers/billing Phases 1–5** — OAuth login, quota enforcement,
  Stripe billing, history UI, retention sweep. Phase 1 is blocked on
  vendoring Supabase's GoTrue role/schema bootstrap SQL (see
  `accounts_db/README.md`).
- **Tool-calling reliability with smaller/local (non-cloud) models** is a
  known tradeoff of model choice — no fix planned, documented as-is.
- **SearXNG rate-limiting** under sustained traffic — best-effort, no
  mitigation in place.
- **Full jailbreak-proofing** — the prompt-injection hardening in place is
  mitigation, not a guarantee; not solvable via system prompt alone.
- **CAPTCHA/Turnstile / WAF** for the anonymous tier — deliberately
  deferred until anonymous-tier abuse actually materializes.

## Related docs

- [`README.md`](README.md) — setup/run instructions for this module.
- [`rules_mcp/README.md`](rules_mcp/README.md), [`scryfall_mcp/README.md`](scryfall_mcp/README.md), [`accounts_db/README.md`](accounts_db/README.md) — sub-service detail.
- [`../CLAUDE.md`](../CLAUDE.md) — deep implementation notes, the non-obvious "why."
- [`../docs/FEATURES.md`](../docs/FEATURES.md) — feature-by-feature verification catalog.
- [`../docs/PLAN.md`](../docs/PLAN.md) — what's done, project-wide, and why.
- [`../docs/TODO.md`](../docs/TODO.md) — the working next-steps list.
- [`../docs/PUBLISHING_PLAN.md`](../docs/PUBLISHING_PLAN.md) — CI/CD, monitoring, and scaling roadmap.
