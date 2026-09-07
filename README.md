<h1 align="center">
  <img src="shared/assets/MTG-Azor-Icon.png" height="90" alt="MTG Azor icon">
  <img src="shared/assets/MTG-Azor-Logo.png" height="90" alt="MTG Azor">
</h1>

<p align="center">
  <i>An AI Magic: The Gathering rules judge — grounded, cited, and never guessing.</i>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL%203.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python 3.11">
  <img src="https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white" alt="TypeScript">
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" alt="Docker Compose">
  <a href="https://github.com/Delta-43/mtg_local_chatbot/graphs/contributors"><img src="https://img.shields.io/github/contributors-anon/Delta-43/mtg_local_chatbot?color=yellow" alt="Contributors"></a>
  <img src="https://img.shields.io/github/last-commit/Delta-43/mtg_local_chatbot" alt="Last commit">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Backend-Live-brightgreen" alt="Backend: Live">
  <img src="https://img.shields.io/badge/Discord%20Bot-Live-brightgreen" alt="Discord Bot: Live">
  <img src="https://img.shields.io/badge/Web%20App-Live-brightgreen" alt="Web App: Live">
  <img src="https://img.shields.io/badge/Accounts%20%26%20Billing-Planned-lightgrey" alt="Accounts & Billing: Planned">
</p>

<p align="center">
  <a href="https://github.com/Delta-43/mtg_local_chatbot/actions/workflows/server-ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Delta-43/mtg_local_chatbot/server-ci.yml?branch=main&label=server" alt="server CI"></a>
  <a href="https://github.com/Delta-43/mtg_local_chatbot/actions/workflows/scryfall-mcp-ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Delta-43/mtg_local_chatbot/scryfall-mcp-ci.yml?branch=main&label=scryfall-mcp" alt="scryfall-mcp CI"></a>
  <a href="https://github.com/Delta-43/mtg_local_chatbot/actions/workflows/discord-ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Delta-43/mtg_local_chatbot/discord-ci.yml?branch=main&label=discord" alt="discord CI"></a>
  <a href="https://github.com/Delta-43/mtg_local_chatbot/actions/workflows/webapp-ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Delta-43/mtg_local_chatbot/webapp-ci.yml?branch=main&label=webapp" alt="webapp CI"></a>
  <a href="https://github.com/Delta-43/mtg_local_chatbot/actions/workflows/ops-ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Delta-43/mtg_local_chatbot/ops-ci.yml?branch=main&label=ops" alt="ops CI"></a>
  <a href="https://github.com/Delta-43/mtg_local_chatbot/actions/workflows/compose-validate.yml"><img src="https://img.shields.io/github/actions/workflow/status/Delta-43/mtg_local_chatbot/compose-validate.yml?branch=main&label=package" alt="package CI"></a>
</p>

<p align="center">
  <a href="#-what-it-does">What it does</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-project-status">Status</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-tech-stack">Tech Stack</a> •
  <a href="#-documentation">Documentation</a>
</p>

---

## 🧠 What it does

MTG Azor answers Magic: The Gathering rules questions the way a real judge
would: by looking things up, not guessing from memory. A tool-calling
agent (not a fixed if/elif pipeline) decides for itself which of the
Comprehensive Rules, live Scryfall card data, official rulings, or the
open web it needs to check — then **every answer ends in a citation
block**, verified against the real tool results it just fetched, not just
requested by prompt.

- ⚖️ **Grounded answers** — rule numbers, official rulings, and source
  links are added only after being independently verified; nothing is
  cited from the model's memory.
- 🃏 **Live card data** — oracle text, legality, pricing, and rulings via
  a native Scryfall integration, always current.
- 🔍 **Falls back to the open web** — only for genuinely contested or
  ambiguous interactions the rules/rulings can't resolve on their own.
- 💬 **Two real surfaces** — a streaming web app and a Discord bot
  (`/judge`), both talking to the same public API.
- 🏠 **Self-hosted or public** — runs entirely on your own hardware with
  local models, or points at hosted LLM/embedding providers for a public
  deployment. One codebase, either way.

## 🏗️ Architecture

```mermaid
%%{init: {"themeVariables": {"fontSize": "12px"}, "flowchart": {"useMaxWidth": true, "padding": 10, "nodeSpacing": 15, "rankSpacing": 30}}}%%
flowchart LR
    PWA["🖥️ Web App"] --> Caddy["🔀 Caddy"]
    Bot["🤖 Discord Bot"] --> Caddy
    Caddy --> API["⚡ FastAPI"]
    API --> Agent["🧭 Tool-Calling Agent"]
    Agent --> LLM[("🧠 LLM")]
    Agent --> Rules["📖 rules-mcp"]
    Agent --> Scryfall["🃏 scryfall-mcp"]
    Agent --> Search["🌐 web_search"]
```

Every box above is a real, independently-runnable module — `webapp/`,
`discord_client/`, `server/app_api/`, `server/llm_agent/`,
`server/rules_mcp/`, `server/scryfall_mcp/`, respectively. See
[Project Structure](#-project-structure) and
[`docs/DESCRIPTION.md`](docs/DESCRIPTION.md) for the full picture.

## 📊 Project Status

| Component | Status | Detail |
|---|:---:|---|
| Backend (agent, API, rules & card search) | ![Live](https://img.shields.io/badge/-Live-brightgreen) | [`server/`](server/README.md) · [status](server/STATUS.md) |
| Web App (PWA) | ![Live](https://img.shields.io/badge/-Live-brightgreen) | [`webapp/`](webapp/README.md) · [status](webapp/STATUS.md) · [redesign plan](docs/WEBAPP_PLAN.md) |
| Discord Bot ("Azor, High Arbiter") | ![Live](https://img.shields.io/badge/-Live-brightgreen) | [`discord_client/`](discord_client/README.md) · [status](discord_client/STATUS.md) |
| Ops (backup/restore, monitoring) | ![Live](https://img.shields.io/badge/-Live-brightgreen) | [`ops/`](ops/README.md) · [status](ops/STATUS.md) |
| Public Hosted Instance | ![Live](https://img.shields.io/badge/-Live-brightgreen) | `azor.delta43.net` |
| Accounts, Tiers & Billing | ![Planned](https://img.shields.io/badge/-Planned-lightgrey) | [plan](docs/PLAN.md) |
| CI/CD | ![Live](https://img.shields.io/badge/-Live-brightgreen) | [`.github/workflows/`](.github/workflows/) · [Actions](https://github.com/Delta-43/mtg_local_chatbot/actions) |

Full feature-by-feature verification status lives in
[`docs/FEATURES.md`](docs/FEATURES.md); what's actively being worked on is
in [`docs/TODO.md`](docs/TODO.md).

## 🚀 Quick Start

```bash
git clone https://github.com/Delta-43/mtg_local_chatbot.git
cd mtg_local_chatbot
./setup.sh      # interactive: pick chat/embedding provider, deployment shape
./run_bot.sh    # (dev-only shape) docker compose up rules-mcp/scryfall-mcp/searxng, then host uvicorn
```

`./setup.sh` asks a few questions the first time you run it — local Ollama or
hosted OpenRouter for chat, same for embeddings, and whether you want a local
dev setup only or the full Caddy-fronted deployment (webapp + optionally the
Discord bot) — then writes the answers to a local `.env` file (never to a
file this repo tracks). Run it non-interactively with `./setup.sh --yes` to
skip the prompts and keep whatever's already configured (defaults to fully
local on a first run). Switching providers later is just editing `.env` and
restarting; see `docs/DESCRIPTION.md`'s environment variable reference for
every setting.

```bash
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"query": "What happens during the untap step?"}'
```

Want everything in Docker but still no `webapp/`/Node involved? `caddy`
only pulls in `webapp/` to build the PWA into its image — skip both:
`docker compose up -d --build mtg-judge rules-mcp scryfall-mcp searxng`,
then hit `http://localhost:8000` directly (its own dev test UI at `/`,
plus `/chat`, `/chat/stream`, `/health`, `/metrics`). See
`docs/DESCRIPTION.md`'s "Local, webapp-free" section for a proxy-fronted
(`caddy-local`) variant of this too.

For the full Docker deployment (public-facing, incl. Cloudflare Tunnel, R2
backup, and the Discord bot), environment variables, troubleshooting, and
the complete API reference, see **[`docs/DESCRIPTION.md`](docs/DESCRIPTION.md)**.

## 🧰 Tech Stack

<table>
<tr>
<td><strong>Backend</strong></td>
<td>
<img src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
<img src="https://img.shields.io/badge/LangChain-1C3C3C?logo=langchain&logoColor=white" alt="LangChain">
<img src="https://img.shields.io/badge/LangGraph-1C3C3C" alt="LangGraph">
<img src="https://img.shields.io/badge/ChromaDB-FF6F61" alt="ChromaDB">
<img src="https://img.shields.io/badge/Ollama-000000?logo=ollama&logoColor=white" alt="Ollama">
</td>
</tr>
<tr>
<td><strong>Web App</strong></td>
<td>
<img src="https://img.shields.io/badge/React-61DAFB?logo=react&logoColor=black" alt="React">
<img src="https://img.shields.io/badge/Vite-646CFF?logo=vite&logoColor=white" alt="Vite">
<img src="https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white" alt="TypeScript">
<img src="https://img.shields.io/badge/PWA-5A0FC8?logo=pwa&logoColor=white" alt="PWA">
</td>
</tr>
<tr>
<td><strong>Discord Bot</strong></td>
<td>
<img src="https://img.shields.io/badge/discord.py-5865F2?logo=discord&logoColor=white" alt="discord.py">
<img src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white" alt="Python">
</td>
</tr>
<tr>
<td><strong>Data Sources</strong></td>
<td>
<img src="https://img.shields.io/badge/Scryfall%20API-000000" alt="Scryfall API">
<img src="https://img.shields.io/badge/MTG%20Comprehensive%20Rules-000000" alt="MTG Comprehensive Rules">
<img src="https://img.shields.io/badge/SearXNG-3050FF" alt="SearXNG">
</td>
</tr>
<tr>
<td><strong>Infra & Deployment</strong></td>
<td>
<img src="https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white" alt="Docker">
<img src="https://img.shields.io/badge/Caddy-1F88C0?logo=caddy&logoColor=white" alt="Caddy">
<img src="https://img.shields.io/badge/Cloudflare%20Tunnel-F38020?logo=cloudflare&logoColor=white" alt="Cloudflare Tunnel">
<img src="https://img.shields.io/badge/Cloudflare%20R2-F38020?logo=cloudflare&logoColor=white" alt="Cloudflare R2">
</td>
</tr>
</table>

## 📁 Project Structure

```
mtg_local_chatbot/
├── server/            # Backend: FastAPI, the agent, rules-mcp, scryfall-mcp
├── discord_client/    # Discord bot ("Azor, High Arbiter")
├── webapp/            # React + Vite PWA
├── ops/               # R2 backup/restore, Prometheus monitoring (--profile monitoring)
├── shared/            # Cross-module brand assets & design reference
├── docs/              # Everything below — architecture, features, plans
└── docker-compose.yml # Full stack + optional profiles (tunnel/backup/discord/accounts/monitoring)
```

Every module has its own `README.md` (setup/run detail) and `STATUS.md`
(current status, features, what's left) — start there when working on a
particular surface; start with
[`docs/DESCRIPTION.md`](docs/DESCRIPTION.md) for the full cross-cutting
picture.

## 📚 Documentation

| Document | What's in it |
|---|---|
| [`docs/DESCRIPTION.md`](docs/DESCRIPTION.md) | Full architecture, configuration, deployment, API reference, troubleshooting |
| [`docs/FEATURES.md`](docs/FEATURES.md) | Feature-by-feature requirement + verification catalog |
| [`docs/PLAN.md`](docs/PLAN.md) | What's done, and why, at the project level |
| [`docs/TODO.md`](docs/TODO.md) | The working next-steps list |
| [`docs/PUBLISHING_PLAN.md`](docs/PUBLISHING_PLAN.md) | Self-hosted OSS + hosted SaaS publishing strategy |
| [`docs/WEBAPP_PLAN.md`](docs/WEBAPP_PLAN.md) | In-progress PWA visual redesign |
| [`CLAUDE.md`](CLAUDE.md) | Deep implementation notes — the non-obvious "why" behind the code |
| `server/`, `discord_client/`, `webapp/`, `ops/`, `shared/` — `README.md` | Per-module setup & run instructions |
| `server/`, `discord_client/`, `webapp/`, `ops/`, `shared/` — `STATUS.md` | Per-module current status, features, and what's left — see [`server/STATUS.md`](server/STATUS.md) for the pattern |

## 🤝 Contributing

The codebase is split into independent modules
(`server/`/`discord_client/`/`webapp/`/`ops/`) specifically so multiple
people can work on different surfaces without stepping on each other —
see [`.github/CODEOWNERS`](.github/CODEOWNERS) for who reviews what.
Start with the README of the module you're touching, then
[`docs/DESCRIPTION.md`](docs/DESCRIPTION.md) for how it fits into the
whole.

## 📄 License

[GNU AGPL v3.0](LICENSE)
