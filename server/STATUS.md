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
Accounts/tiers/billing is **planned, not started**; CI/CD is now **live** (see `.github/workflows/`). The web
app's visual redesign is **paused** pending a design direction.

## 📦 This module: server/

The backend product — the FastAPI app, the tool-calling agent, and the
two MCP sub-services it talks to (`rules_mcp/`, `scryfall_mcp/`), plus
`core_config/`, `accounts_db/`, `searxng/` config, and `tests/`. See
[`README.md`](README.md) for setup/run instructions.

### Status: ✅ Live

Serving real production traffic through both the web app and the Discord
bot, 24/7, at `azor.delta43.net`. Currently running `LLM_PROVIDER=hosted`
(OpenRouter, `z-ai/glm-5.3-flash`) — a deployment-time `.env` choice, not
a code default (the code default stays `local`/`gemma4:cloud` for
self-hosters). Switched 2026-09-06 after finding the previously-configured
`local` setup was itself broken (see the note below) — re-verified the
full request surface end-to-end afterward: citations/pruning, multi-turn
memory, streaming, tiered auth, rate limits, both daily quotas, off-topic
and jailbreak refusal, and the Discord bot's own formatting pipeline
(mana symbols, table→embed) all confirmed working against the new
provider, not just the happy path.

**Found and fixed while switching providers**: the previously-live
`local` config (`LLM_MODEL=qwen3.5:0.8b`) was not actually a valid local
Ollama model on the dedicated instance, and real requests were silently
falling back into failures against the Ollama Cloud account's own session
usage limit — meaning `/chat` may have been unreliable under the old
config independent of anything in this switch. Restored to the
documented default (`gemma4:cloud`) as the `local`-mode fallback config
even though production itself now runs `hosted`.

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
  SQLite checkpointer. Anonymous buckets by real client IP (`_client_ip()`,
  preferring Cloudflare's `CF-Connecting-IP`), not the proxy's — fixed
  2026-09-06 after finding every anonymous visitor previously shared one
  bucket (Caddy's own bridge IP); see `docs/FEATURES.md`'s H4 entry.
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

### Remaining work

- **Firewall verification for the `_client_ip()` fix's trust assumption** —
  it trusts `CF-Connecting-IP`, which only holds if Caddy is reachable
  *exclusively* through the Cloudflare Tunnel. On this host, Caddy's
  80/tcp maps to `0.0.0.0:8880` (all interfaces, not loopback-only) —
  `sudo ufw status` couldn't be checked non-interactively during this
  session, so whether a host firewall actually blocks public access to
  that port is unconfirmed. Needs a firewall rule, not a code change.
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
