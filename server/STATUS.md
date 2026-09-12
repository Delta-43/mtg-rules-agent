# STATUS — server/

_A snapshot for developers, not a replacement for the full docs. See
"Related docs" at the bottom for where the deep detail lives — this file
summarizes, it doesn't duplicate._

**MTG Azor** is an AI Magic: The Gathering rules judge: a tool-calling
agent that grounds every answer in the Comprehensive Rules, live Scryfall
card data, official rulings, or web search — never from memory — and
cites what it used. This repo is the reply server only, exposed over
HTTP (`/chat`, `/chat/stream`) — no bundled frontend; bring your own
client. `server/` (this directory) is the whole product: the FastAPI app,
the tool-calling agent, and the two MCP sub-services it talks to
(`rules_mcp/`, `scryfall_mcp/`), plus `core_config/`, `searxng/` config,
and `tests/`. See [`README.md`](README.md) for setup/run instructions.

### Status: ✅ Live

The agent, both MCP servers, and tiered auth/rate-limiting have all been
verified end-to-end against a real running deployment — real rules
questions, real card lookups, real citations, streaming and non-streaming,
both LLM providers. Defaults to `LLM_PROVIDER=local` (`gemma4:cloud`) — a
deployment-time `.env` choice, not a hardcoded requirement; `hosted`
(OpenRouter) is an equally supported, independently verified path, not a
fallback.

In practice `local`/`gemma4:cloud` has been the more consistently fast,
reliable tool-calling option across the models tried so far — a genuinely
slow OpenRouter model can turn a multi-tool-call question into a ~40s
round trip where the same question resolves in ~6s on `gemma4:cloud`. If
you switch to `hosted`, pick a model known for reliable tool-calling and
measure it against your own workload rather than assuming parity.

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
- **Framework-chapter pre-fetch, not just semantic search** — discovered
  during development: some rulings (e.g. "does Doubling Season double a
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
  be grown from real chat-log volume once a deployment has some, not
  guessed at further ahead of data.
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
  preferring Cloudflare's `CF-Connecting-IP`), not the raw socket peer —
  necessary the moment anything sits in front of this service as a
  reverse proxy, since every request otherwise arrives from the proxy's
  own IP; see `CLAUDE.md` for the full incident this fixed.
- **Several real hardening fixes** found via live multi-client usage, all
  in the shared agent so every caller benefits: off-topic-question
  refusal, duplicate-citation-block stripping, cross-turn citation
  leakage fix (isolating sources to the current turn when a client shares
  one thread_id across multiple users), LaTeX/markdown-heading cleanup,
  degenerate-repetition truncation, mid-answer self-correction
  suppression, and a bounded `recursion_limit` on the agent's tool-calling
  loop (found live: an unbounded run made 700+ real LLM calls over ~8
  minutes before being killed by hand; now fails in ~20s instead). Full
  detail in `CLAUDE.md`.
- **`docker-compose.yml` health-gates `mtg-judge` on `rules-mcp`/
  `scryfall-mcp`/`searxng` actually being healthy, not just started** (and
  `caddy` on `mtg-judge`) — found live: on a fresh install, `mtg-judge`
  raced ahead of rules-mcp's first-boot ingestion (which can take 8-10
  minutes and doesn't bind its port until it's done) and crash-looped with
  confusing tracebacks the whole time. `condition: service_healthy` plus a
  generous `start_period` on rules-mcp's healthcheck fixes this: `docker
  compose up` now blocks until every dependency is genuinely ready instead
  of just running.
- **CI** (`.github/workflows/server-ci.yml`) — `pytest` on every PR
  touching this module, plus Docker builds and import smoke tests for
  the `mtg-judge` and `rules-mcp` images.
- **`GET /metrics`** (`prometheus-fastapi-instrumentator` + a purpose-built
  `http_streaming_ttft_seconds` histogram in `core_config/metrics.py`) —
  a standard Prometheus-format endpoint; point your own Prometheus (or
  compatible scraper) at it. Per-tool-call metrics
  (`agent_tool_calls_total`) are NOT part of this yet — scoped as separate
  follow-up work; see `CLAUDE.md`.

### Remaining work

- **`rules_mcp` has no fixture-based regression test for the parser
  itself yet** — today's CI checks that `rules_mcp` imports cleanly, not
  that it parses real rules content correctly. A small-sample-PDF test
  asserting a sane rule count would have caught the historical
  807-vs-1172 silent parsing bug automatically (see `CLAUDE.md`); not yet
  written.
- **Branch protection on `main`** requiring CI to pass before merge isn't
  turned on yet — a GitHub repo setting, not something committable.
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
- [`rules_mcp/README.md`](rules_mcp/README.md), [`scryfall_mcp/README.md`](scryfall_mcp/README.md) — sub-service detail.
- [`../CLAUDE.md`](../CLAUDE.md) — deep implementation notes, the non-obvious "why."
- [`../docs/DESCRIPTION.md`](../docs/DESCRIPTION.md) — full architecture, configuration, deployment, API reference.
