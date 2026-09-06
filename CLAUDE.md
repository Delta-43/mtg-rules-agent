# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An AI Magic: The Gathering rules judge. A LangChain 1.x tool-calling agent (not a
fixed classify-then-branch pipeline) decides for itself which tools to call — a
semantic rules index, live Scryfall card data, official rulings, or web search —
and is required by its system prompt to end every answer with a citation block
(rule numbers, rulings, source URLs). If it can't ground part of an answer in a
tool result, it's instructed to say so rather than guess.

`docs/DESCRIPTION.md` has the full architecture writeup; `README.md` has setup/usage.
This file is oriented toward things that aren't obvious from reading one file at
a time.

Each top-level module (`server/`, `discord_client/`, `webapp/`, `ops/`,
`shared/`) has a `STATUS.md` alongside its `README.md` — a short,
consistently-structured snapshot (project-wide summary, that module's
current status/features, what's left to do), meant for a developer who
wants "where does this stand right now" without reading `docs/PLAN.md`/
`docs/TODO.md`'s full history. **Update the relevant module's `STATUS.md`
whenever a change meaningfully shifts what's true there** (a feature
lands, something moves from planned to live, a new gap is found) — it's
easy for these to silently go stale the way `docs/PLAN.md`'s "Frontend
visual design pass" line once did (see git history), and they exist
specifically so that doesn't happen quietly.

## Commands

```bash
./setup.sh      # venv, deps, dedicated Ollama instance + model pulls
./run_bot.sh     # docker compose up rules-mcp/scryfall-mcp/searxng, then host uvicorn
```

There's no lint/test tooling in `rules_mcp` — verification there is functional,
by actually running the stack and hitting `/chat` (see README's API Endpoints
section). The main backend (`app_api`, `llm_agent`, `core_config`) does have a
small pytest suite now (`server/tests/`, `python -m pytest server/tests/`) covering
`server/app_api/main.py`'s routes -- still no substitute for hitting the real stack,
since it doesn't exercise the agent or either MCP server. `server/scryfall_mcp/` has
its own real vitest suite (`npm test` inside that directory) -- unlike before,
when it was unmodified third-party code not worth touching, it's now a local
fork this repo actively modifies (see the Scryfall section below), so new
tools added there should get a matching test.

**Both are wired into CI now** (`.github/workflows/server-ci.yml`,
`scryfall-mcp-ci.yml`), one workflow per module plus a package-wide one
(`compose-validate.yml`) -- see `docs/PUBLISHING_PLAN.md`'s Stage 0 for
the full list and what's still genuinely uncovered (`rules_mcp` still has
no fixture-based correctness test, only an import smoke test).

Full Docker deployment (all five services incl. Caddy):
```bash
docker-compose up --build
```

`server/rules_mcp/` is a separate, independently runnable service (no imports from the
rest of the repo) — see `server/rules_mcp/README.md` for running/testing it standalone
via `python -m rules_mcp.server`, or forcing a manual re-ingest via
`python -m rules_mcp.parser` + `python -m rules_mcp.ingestor` (run from inside
`server/`, the new parent of `rules_mcp/` after the repo reorganization — the module
invocation itself is unaffected, only its required working directory moved).

## Architecture

```text
Client -> Caddy -> FastAPI (server/app_api/main.py) -> tool-calling agent (server/llm_agent/agent.py)
                                                    |-- rules-mcp (MCP/HTTP): search_rules, get_rule_by_id
                                                    |-- scryfall-mcp (MCP/HTTP): 16 tools, incl. get_card_rulings
                                                    `-- web_search (in-process @tool: SearXNG + trafilatura)
```

**Rule citations are verified, not just requested.** The system prompt
tells the model to only cite a rule number it just looked up, but that's
not reliable alone (seen live: a rule number slipped through uncited even
with the instruction in place). `server/llm_agent/agent.py`'s
`_verify_unbacked_rule_citations()` is the actual enforcement: after the
model's final answer, it regex-extracts every rule-number-shaped mention,
and for any not already backed by a real tool call this turn, calls
`get_rule_by_id` — an **exact metadata-filtered lookup**
(`vector_store.get(where={"rule_id": ...})`), not semantic search — to
independently confirm it before adding it to `sources.rules`. This exists
specifically because `search_rules` (semantic search) is unreliable for
this: querying the literal string `"502.3"` with `section="502"` surfaced
`502.1`/`502.2`/`502.4` in the top results instead of `502.3` itself —
neighboring rules in the same section are often more semantically similar
to a bare rule number than the exact chunk is. Don't try to verify a
citation with `search_rules`; use `get_rule_by_id`.

That safety net only catches *under*-citation (a real rule used but not
listed). The opposite also happens: `search_rules` returns up to `k=5`
similar chunks per call, and the old `_extract_sources()` harvested every
`[rule_id]` from every `search_rules` call made this turn regardless of
whether the answer actually discussed it -- verified live, a
triggered-ability-ordering question came back with 4 extra, unrelated rule
numbers (unrelated combat-step boilerplate, an unrelated keyword mechanic)
alongside the one rule the answer explained. `_prune_unmentioned_rule_citations()`
now runs first, trimming `sources["rules"]` down to only ids that also
appear in the answer's own prose, before `_verify_unbacked_rule_citations()`
runs its under-citation check -- the two compose in that order without
undoing each other's work.

Three independent tool sources get merged into one agent in `server/llm_agent/agent.py`'s
`build_agent()`: `rules-mcp` and `scryfall-mcp` are loaded over MCP via
`langchain-mcp-adapters`' `MultiServerMCPClient`; `web_search` is the one
remaining plain in-process `@tool`. This mixed sourcing matters when touching
`_extract_sources()`: MCP tool messages carry `content` as a list of content
blocks (`[{"type": "text", "text": "..."}]`), not a plain string like the
in-process tool — `_content_to_text()` exists specifically to unwrap that before
the citation regexes run, since stringifying the list runs the regex against a
Python `repr()` instead of the actual text.

**Card data is delegated, via a locally-owned fork, not a live remote build.**
`server/scryfall_mcp/` holds the actual source of
[bmurdock/scryfall-mcp](https://github.com/bmurdock/scryfall-mcp) (MIT, vendored
at commit `fd585a0`), checked into this repo directly — not a git submodule
(that was the original approach; dropped because it couldn't be modified in
place) and not a Dockerfile that `git clone`s upstream at build time (the
approach immediately before this one; dropped for the same reason, plus it
meant every build depended on GitHub being reachable). `server/scryfall_mcp/Dockerfile`
now just `COPY`s local `package.json`/`src/` in and runs `npm install && npx tsc`
— if upstream's `package-lock.json` drifts from `package.json` again (it has
before), that's why the Dockerfile uses `npm install`, not `npm ci`.
`server/scryfall_mcp/UPSTREAM_README.md` is upstream's own README, kept for
attribution; `server/scryfall_mcp/README.md` is this repo's.

Because it's a real local fork now, not unmodified third-party code, it *has*
been modified: `get_card_rulings` (`src/tools/get-card-rulings.ts`) was added
as a 16th native tool, calling the real
[Scryfall Rulings API](https://scryfall.com/docs/api/rulings)
(`ScryfallClient.getCardRulings()` in `src/services/scryfall-client.ts` resolves
the card the same way `getCard()` does, then fetches its `rulings_uri`). This
used to be a Python gap-filler (`scryfall_agent/scryfall_tools.py`, now
deleted) hitting the same Scryfall endpoints directly as an in-process
`@tool`, kept separate specifically because upstream didn't expose rulings.
Moving it into the MCP server itself means `get_card_rulings` is now a normal
MCP tool like `get_card` -- `_extract_sources()` didn't need to change, since
it already ran `_content_to_text()` over every tool message regardless of
source; only the import and the `tools = [...]` list in `build_agent()`
needed updating. The output text format (`"Official rulings for {name}:\n-
(date) comment"`) was kept byte-for-byte identical to the old Python tool's,
since `_RULING_CARD_PATTERN` in `server/llm_agent/agent.py` regexes it back out --
see the comment on `formatCardRulings()` in `server/scryfall_mcp/src/utils/formatters.ts`
before changing that shape.

`server/scryfall_mcp/`'s own `tests/` (vitest) got two additions for the new tool:
a couple of mock-based checks in `tests/tools.test.ts` (name/description,
input validation -- the two things that don't touch card data and reject
before any client call happens, so they belong alongside every other tool's
mocked tests there) and a separate `tests/get-card-rulings.live.test.ts` for
everything that does touch real ruling data -- deliberately its own file,
since `tools.test.ts` mocks `scryfall-client.js` at module scope, which would
silently turn a real `new ScryfallClient()` into a mock too if it lived
there. The live file makes genuine HTTP calls to `api.scryfall.com`: no
mocked client, no fabricated ruling text, because a mock only proves the
formatter does what it's told with data invented for the test, not that the
real integration (identifier resolution -> `rulings_uri` -> rulings text)
works against Scryfall's actual responses. It caught a real surprise
immediately: the fuzzy-matched printing `/cards/named?fuzzy=Lightning+Bolt`
currently resolves to has an empty `rulings_uri` on the live API right now
(a recent promo printing, not the card lacking rulings generally) -- an
assumption-based mock would never have surfaced that. Doubling Season (5 real
rulings) and Grizzly Bears (0 rulings, genuinely vanilla) are used instead,
both verified directly against the live API before being hardcoded into the
test. Verified: `npx tsc --noEmit` compiles clean, `npx vitest run` passes
all 334 tests (329 upstream + 2 mocked + 3 live), and a live `/chat` call
("What are the official Scryfall rulings for Doubling Season?")
round-tripped through the real running stack with
`sources.rulings: ["Doubling Season"]` correctly populated.

**`server/rules_mcp/` is a self-contained, extractable project**, not a module of this
repo — it has its own `settings.py` (env-var-only, no YAML) and doesn't import
`core_config`. A few non-obvious things inside it:
- `ingestor.py`'s `recreate=True` path clears the persist directory's *contents*,
  never the directory itself — it's a Docker bind mount, and `rmtree`-ing a mount
  point raises "Device or resource busy".
- The boot-time "already ingested, skip re-embedding" check (`server.py`) is a
  plain file-existence check against an `.ingest_complete` marker file, not a
  Chroma query. chromadb caches system state per persist-directory path within a
  process; opening a throwaway `Chroma` client just to read a document count
  leaves the *next* client (the one `ingest()` itself opens, after a
  `recreate=True` wipe) stuck against stale state, failing writes with
  `"attempt to write a readonly database"`. Don't reach for `Chroma(...)` here —
  use the marker file.
- `ingest()` is incremental, not a full re-embed on every Comprehensive Rules
  update: each top-level rule gets a deterministic chunk id
  (`f"{rule_id}::{i}"`) and a content hash recorded in a
  `.ingest_manifest.json` file next to the Chroma persist dir. A later
  `ingest()` diffs against that manifest and only deletes+re-adds chunks for
  rules whose hash actually changed (plus deletes chunks for rules removed
  entirely) — unchanged rules aren't touched. **Migration gotcha**: a
  persist dir from before this existed has no manifest, so the first
  post-upgrade `ingest()` treats every rule as "new" and re-adds it under the
  new deterministic ids *without* deleting the old random-UUID-keyed chunks
  from before — the collection would silently double. Run one manual
  `python -m rules_mcp.ingestor` (its `recreate=True` default) after
  upgrading an existing deployment to establish a clean manifest baseline;
  server.py's own boot-time `_bootstrap()` never passes `recreate=True`
  itself, so this won't happen automatically on a container restart.
  **Learned the hard way**: run this via a single clean background
  mechanism, not nested (e.g. `&` inside an already-backgrounded shell) --
  an orphaned/killed process mid-`recreate=True` leaves the collection
  *partially wiped*. Back up `data/chroma` first on a live deployment.
- `parser.py`'s `flush_rule()` used to silently **drop an entire rule**
  (subrules included) whenever its own heading text didn't end in terminal
  punctuation (`.`, `)`, `"`) -- which is the normal shape for every
  keyword-ability rule (e.g. `"702.19. Trample"`, with all real content in
  `702.19a`-`702.19g` underneath). This silently dropped ~30% of the whole
  Comprehensive Rules (807 rules parsed instead of ~1172) without any
  visible error -- `search_rules` would just never find those rules, and
  the model would fall back to citing them from memory instead (see the
  citation-verification note above; this bug is a big part of why that
  safety net matters). Fixed: the rule is always kept, with an "odd ending"
  case now just logged, not silently discarded. If total rule counts ever
  regress toward ~807, this bug (or one shaped like it) is back.
- Embedding batches in `ingest()` run concurrently
  (`Config.INGEST_CONCURRENCY`, default `min(cpu_count, 8)`) instead of a
  fixed serial loop -- but whether this actually helps depends on where the
  real bottleneck is. Measured on a 4-core, CPU-only, no-GPU host: **zero
  speedup**, with or without also raising `OLLAMA_NUM_PARALLEL` on the
  Ollama side (`scripts/run_ollama.sh`) -- the bottleneck there is raw CPU
  compute for the embedding model, not request queueing. It's correct and
  harmless regardless, and should genuinely help on hardware where
  queueing/latency is the limiting factor instead (more cores, GPU-backed
  embeddings, a remote/high-latency Ollama) -- don't assume it speeds up
  ingestion on every deployment without measuring that deployment.

**Config is YAML-first with env-var overrides**, resolved once at import time by
`server/core_config/settings.py` (`_resolve()` checks the env var, then the YAML path,
then a hardcoded fallback). There's no intermediate export-to-shell step — the
Docker entrypoint just asks `Config` for `HOST`/`PORT` and execs uvicorn directly.
`server/rules_mcp/settings.py` is a separate, parallel settings module by design (see
above). **`docker-compose.yml`'s `mtg-judge` service only forwards env vars
explicitly listed in its `environment:` block** — a var being documented as
"env-overridable" in README.md doesn't mean `.env` actually reaches the
container under docker-compose; it has to be listed there too, or only
`server/project_config.yml`'s value ever applies (found and fixed for
`RATE_LIMIT_PER_MINUTE`/`DAILY_QUOTA_ANONYMOUS`/`DAILY_QUOTA_AUTHENTICATED` —
they were documented as overridable but silently weren't, under
docker-compose specifically). When adding one of these, don't default it to
an empty string in the compose interpolation if `core_config` casts it with
`int` — `_coerce("", int)` raises `ValueError` and crashes config loading at
import time; give it the same real numeric default `core_config` itself
uses (`${VAR:-20}`, not `${VAR:-}`). String/list-typed vars (`_parse_csv_list`,
plain string) don't have this problem — empty is a valid value for them.

**LLM provider is pluggable**: `llm_provider.build_chat_model()` returns either
`ChatOllama` (`LLM_PROVIDER=local`) or `ChatOpenAI` pointed at OpenRouter
(`LLM_PROVIDER=hosted`). The default model, `gemma4:cloud`, is an **Ollama cloud
model** — inference runs on Ollama's infrastructure, but the client still talks to
a local Ollama instance, which just proxies the request. This requires a one-time
`ollama signin` per machine (see README) before the first real chat request, or
you get a `401 Unauthorized` that only surfaces at inference time — pulling the
model tag itself succeeds either way, since that only fetches a small manifest.
`rules-mcp`'s embeddings are independently pluggable via a *separate*
`EMBEDDING_PROVIDER` (local/hosted), unrelated to `LLM_PROVIDER` -- see
`server/rules_mcp/embeddings.py`. Also deliberately a **separate OpenRouter key**
(`OPENROUTER_EMBEDDING_API_KEY`, not `OPENROUTER_API_KEY`): different
container, different model, tracked independently on OpenRouter's side.
Hosted embeddings (`baai/bge-m3` by default) exist specifically for
slower/low-core hardware where local embedding compute -- not request
queueing -- is the ingestion bottleneck (see the `INGEST_CONCURRENCY` note
above: raising concurrency alone doesn't fix that; moving the compute off
the host entirely does). **Switching providers mid-collection is guarded,
not silently wrong**: `bge-m3` happens to produce the same 1024-dimension
vectors as `mxbai-embed-large`, but same dimension is not the same vector
space -- two different embedding models don't place similar text at
comparable coordinates. `ingest()` records which provider+model produced
the current collection in a `.embedding_signature` file and forces a full
re-embed (not an incremental diff) whenever that changes, so a provider
switch can never silently leave old-provider and new-provider vectors
mixed in the same collection. Verified live: hosted → local switch on the
same collection correctly triggered and completed a full re-embed; a
same-provider re-run afterward stayed a true no-op.

**Ollama runs as a dedicated instance on its own port (`11435`, not the usual
`11434`)**, started by `scripts/run_ollama.sh` and bound to `0.0.0.0`. Both
choices are load-bearing, not arbitrary:
- Its own port lets it coexist with any system-wide Ollama already running
  instead of fighting it for the port.
- `0.0.0.0`, not `127.0.0.1`: `rules-mcp` and `mtg-judge` reach it from inside
  Docker via `host.docker.internal`, which resolves to the host's bridge-gateway
  address, not loopback — a loopback-bound service is unreachable from a
  container even though it works fine from the host shell. (On a host with a
  restrictive firewall, e.g. `ufw`, the bridge subnet also needs an explicit
  allow rule for this port — the container-to-host hop looks like external
  traffic to the firewall.)

GPU vs. CPU is *not* a project-level concern anymore — hardware detection is left
to Ollama's own defaults. If a GPU driver misbehaves (e.g. hangs on Vulkan
offload), that's addressed via Ollama's own env vars (`OLLAMA_VULKAN=0` etc.),
not project-specific scripting. This used to be a bigger axis of complexity
(separate CPU/GPU launcher scripts) before the default model moved to a cloud
model that doesn't need local GPU/CPU inference for chat at all.

**`discord_client/` is an independent, self-contained client** — a single
`/judge` slash command that calls the public backend's `POST /chat` (never
`/chat/stream`; coalescing streamed tokens into Discord message edits fights
Discord's own edit rate limits) and posts the answer back. Like `server/rules_mcp/`,
it deliberately doesn't import `llm_agent`/`app_api` — it's a thin REST
client hitting the same public URL any other caller would use
(`DISCORD_API_BASE_URL`, e.g. `https://azor.delta43.net`), authenticated with
its own dedicated entry in the backend's `API_KEYS` so its usage is tracked
independently of the PWA's keyless traffic. Full setup/deployment detail
lives in `discord_client/README.md`; this is just what isn't obvious from
reading `bot.py` alone.

Branding is split across two genuinely different things, easy to conflate:
the Discord **Application** (name "MTG Azor", icon, and the Terms of
Service/Privacy Policy URLs required for public listing — all set manually
in the Developer Portal's General Information tab, not reachable via the bot
token API) versus the bot **account** (username "Azor, High Arbiter" +
avatar, set via `discord_client/set_branding.py`, a one-off script using
`client.login()` only — no gateway connection needed for a REST-only profile
edit, and Discord rate-limits username changes to a couple per hour so this
is never run on every boot).

**Mana symbols render as real icons, not `{W}`/`{T}` text**, via Discord
**application emojis** (not guild emojis — the set is 88 icons, matching
every file in `shared/assets/mana_symbols/` one-for-one, which would blow past a
single guild's emoji slot limit; application emojis have no such cap and
work across every server the bot is in). `bot.py`'s `JudgeBot.setup_hook()`
calls `fetch_application_emojis()` once at startup and caches a `name -> id`
map on the client (`self.mana_emojis`); `_render_mana_symbols()` then
rewrites every `{X}` in the answer into `<:name:id>` markup. The name
mapping needs no hardcoded per-symbol table: it's just `"mana" +
X.replace("/", "").lower()`, which happens to exactly match how the emoji
set was named after `shared/assets/mana_symbols/mana-*.png` (dashes stripped, since
Discord emoji names can't contain them) — e.g. `{T}` -> `manat`, `{2/W}` ->
`mana2w`, `{B/G/P}` -> `manabgp`. `{100}`/`{1000000}` are the one exception
(aliased to their first font variant; no plain `mana100` file exists). Any
symbol not in the map (fetch failed, or a genuinely obscure one) falls back
to the literal `{X}` text rather than breaking the reply. Skips text inside
a ``` fenced code block entirely, since Discord never renders custom emoji
there anyway.

**Tables render as Discord embeds, not a fenced monospace grid.** Discord
has no GFM pipe-table rendering at all — an unhandled table shows up as a
jumbled run of `|`/`-` characters. The first fix (since replaced) reflowed a
table into column-aligned plain text inside a ``` fence; that looked
visually flat, broke `**bold**`/mana-emoji rendering inside cells (neither
renders inside a code fence), and was explicitly disliked once compared
side-by-side against an embed. `_build_table_embed()` now turns each table
into a `discord.Embed` (bordered card, accent color `0xE94560` matching the
PWA's `--accent`), one field per data row: the first column becomes the
field name (with `->` normalized to a real `→` arrow), the remaining
columns become a bulleted list in the field value — a deliberate "flowchart
node" look, confirmed live against a real example before being wired in.
`_send_answer()` (not a single `_chunk_message()` call anymore) is what
makes this possible: it walks the answer via `_split_text_and_tables()` and
sends prose and embeds as separate, correctly-ordered `followup.send()`
calls, since an embed can't be inlined into the middle of a text message. A
table that doesn't fit an embed's limits (25 fields, 256/1024 char caps)
falls back to the old fenced grid (`_render_table()`, kept only for this)
rather than silently dropping content.

**Real Discord testing surfaced several `server/llm_agent/agent.py` hardening
fixes that benefit every caller, not just Discord** (the PWA gets them too,
since they live in the shared agent, not `discord_client/`):
- The model would answer questions with nothing to do with Magic (bare
  arithmetic, algebra, "how much is 1+1") instead of declining — the
  generic "decline off-topic questions" instruction was one buried sentence
  at the end of a long prompt. Fixed with a dedicated "Stay strictly in
  scope" section moved to the very top of `JUDGE_SYSTEM_PROMPT`, naming
  concrete out-of-scope categories and explicitly closing the "just this
  once" / retry-after-refusal loophole.
- The model would append its own free-text `Citations:`/`Rulings:` block
  despite being told not to (prompt-only compliance isn't reliable — same
  lesson as the rule-citation verification above) —
  `_strip_model_citation_block()` now detects and removes any trailing
  heading line that reduces to "citations"/"rulings"/"sources"/"references"
  after stripping markdown punctuation, regardless of how the model
  formatted it, so the app's own standardized citation display (built from
  `sources`, not from the model's prose) is never duplicated.
- `MTGJudgeAgent.query()` (the non-streaming path `/chat` uses — i.e. every
  Discord reply) used to extract `sources` from a checkpointed thread's
  *entire* message history, not just the current turn's tool calls — since
  Discord scopes conversation memory per-channel (`discord-channel-<id>`,
  everyone in a channel shares one thread), an unrelated later question in
  the same channel would come back citing an earlier question's card
  rulings. Fixed by scoping to `messages[pre_len:]` (`pre_len` = message
  count before this turn's `ainvoke()`), the same technique `stream_tokens()`
  already used.
- The model sometimes wrote real LaTeX (`$2 \times 3$`, `\frac{12}{5}`) for
  plain arithmetic, and sometimes used markdown `### headings` — neither
  renders in Discord (shows as literal garbled text) or the web frontend
  (`MessageBubble.tsx` renders `message.text` as a raw string with no
  markdown parser at all, so both already show as literal characters
  there — meaning demoting headings to `**bold**` is a pure win with no
  frontend downside). `_delatex()` and the heading-to-bold substitution in
  `_clean_answer()` fix both deterministically; the system prompt also asks
  the model not to do either, but isn't trusted alone for the same reason
  citations and the trailing block aren't.
- A model occasionally degenerates into repeating the same text fragment
  until it hits `LLM_NUM_PREDICT` instead of terminating (seen live on a
  "combos with X" card-interaction question). `_truncate_repetition()` is a
  deterministic backstop, not a prevention: any run of the same 12+ char
  substring repeated 3+ times gets cut at the first occurrence.
- The model would sometimes state an answer, then visibly second-guess and
  correct itself mid-response ("Wait, I must correct my initial
  summary..."), roughly doubling the answer's length for no benefit. The
  prompt now explicitly asks it to work through multi-step calculations
  completely before writing anything down and present one final answer,
  never a visible correction.
