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
Accounts/tiers/billing and CI/CD are **planned, not started**. The web
app's visual redesign is **paused** pending a design direction.

## 📦 This module: server/

The backend product — the FastAPI app, the tool-calling agent, and the
two MCP sub-services it talks to (`rules_mcp/`, `scryfall_mcp/`), plus
`core_config/`, `accounts_db/`, `searxng/` config, and `tests/`. See
[`README.md`](README.md) for setup/run instructions.

### Status: ✅ Live

Serving real production traffic through both the web app and the Discord
bot, 24/7, at `azor.delta43.net`.

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
- **Card data** (`scryfall_mcp/`) — a local fork of upstream's Scryfall
  MCP server (16 tools total, including a locally-added `get_card_rulings`
  closing the one gap in upstream's tool set).
- **Web search fallback** (`llm_agent/web_search_tool.py`) — self-hosted
  SearXNG + content extraction, used only when rules/rulings tools can't
  resolve a question.
- **API** (`app_api/`) — `/chat`, `/chat/stream` (SSE), `/health`; tiered
  auth (anonymous vs. authenticated `X-API-Key`), per-minute rate limiting
  plus daily quotas, multi-turn conversation memory via a LangGraph
  SQLite checkpointer.
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

### Remaining work

- **CI/CD** — no automated tests on PR yet; `pytest`/`vitest`/`docker compose config`
  checks are scoped but not built (`docs/PUBLISHING_PLAN.md` Stage 0).
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
