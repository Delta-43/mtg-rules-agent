import asyncio
import json
import logging
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from core_config import Config
from core_config.metrics import HTTP_STREAMING_TTFT_SECONDS
from llm_agent import MTGJudgeAgent, build_agent
from llm_agent.llm_provider import LLMConfigError

logging.basicConfig(level=getattr(logging, Config.LOG_LEVEL))
logger = logging.getLogger(__name__)

STATIC_DIR: Path = Path(__file__).resolve().parent / "static"
INDEX_FILE: Path = STATIC_DIR / "index.html"


def _client_ip(request: Request) -> str:
    """Best-effort real client IP behind the Caddy + Cloudflare Tunnel proxy
    chain this app is deployed behind in production.

    Without this, every anonymous request -- from every real visitor,
    combined -- collapses to the same bucket: Caddy's own container IP on
    `mtg-network`, since `get_remote_address()` just reads the raw ASGI
    socket peer, which for any proxied request is always the last hop
    (Caddy), never the actual visitor. That means the anonymous daily quota
    and per-minute rate limit were, in practice, one shared pool across
    every anonymous visitor at once rather than per-visitor as documented --
    confirmed live: `172.25.0.2` (Caddy's bridge IP, per `docker network
    inspect`) was the anonymous bucket key for every proxied request
    regardless of which real IP made it.

    `CF-Connecting-IP` is set by Cloudflare's own edge on every request that
    passes through it, and Cloudflare overwrites any client-supplied value
    of this specific header at their edge -- so for traffic that genuinely
    came through Cloudflare (the tunnel), it can be trusted. Caddy's
    `reverse_proxy` doesn't strip or rewrite it, so it reaches this app
    unmodified. Falls back to the first hop of `X-Forwarded-For` (which
    Caddy appends its own hop onto, without discarding whatever Cloudflare/
    cloudflared already set), then to the raw socket peer for requests that
    never go through Caddy at all (host-run dev via `run_bot.sh`, or a
    direct `docker run`/test client).

    Residual trust caveat, not fixed here: this only holds if Caddy is
    reachable *only* through Cloudflare. `docker-compose.yml`'s `caddy`
    service also publishes 80/443 directly -- if that mapping is bound to a
    public interface (not just loopback) and not blocked by a host firewall,
    a client hitting Caddy that way bypasses Cloudflare's edge entirely and
    could set an arbitrary `CF-Connecting-IP` themselves, since Caddy has no
    special handling for this header. Confirm your firewall actually
    restricts public access to whatever host port Caddy is bound to (check
    `docker port mtg-caddy`) if you rely on the tunnel as the sole ingress.
    """
    cf_connecting_ip = request.headers.get("CF-Connecting-IP")
    if cf_connecting_ip:
        return cf_connecting_ip
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return get_remote_address(request)


def _rate_limit_key(request: Request) -> str:
    api_key = request.headers.get("X-API-Key")
    return api_key or _client_ip(request)


limiter = Limiter(key_func=_rate_limit_key)


def _init_usage_counters_db() -> None:
    Path(Config.CONVERSATION_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(Config.CONVERSATION_DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS usage_counters ("
            "bucket_key TEXT NOT NULL, day TEXT NOT NULL, count INTEGER NOT NULL, "
            "PRIMARY KEY (bucket_key, day))"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global judge_agent
    logger.info("Initializing MTG Judge Agent (provider=%s)...", Config.LLM_PROVIDER)

    if Config.LLM_PROVIDER == "hosted" and not Config.OPENROUTER_API_KEY:
        raise LLMConfigError("LLM_PROVIDER=hosted but OPENROUTER_API_KEY is not set.")

    Path(Config.CONVERSATION_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    _init_usage_counters_db()
    async with AsyncSqliteSaver.from_conn_string(Config.CONVERSATION_DB_PATH) as saver:
        judge_agent = await build_agent(checkpointer=saver)
        logger.info("MTG Judge Agent initialized successfully.")
        yield
    logger.info("Shutting down MTG Judge Chatbot.")


app = FastAPI(
    title="MTG Judge Chatbot",
    description="AI-powered Magic: The Gathering rules judge",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

if Config.CORS_ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=Config.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

instrumentator = Instrumentator(
    should_group_status_codes=False,
    # "^/$" anchors to the literal root path only. Instrumentator matches
    # excluded_handlers with re.search, not an exact-path match -- an
    # unanchored "/" matches every handler string, since every FastAPI path
    # contains "/" ("/chat", "/chat/stream", ...), which would silently
    # exclude everything from instrumentation, not just root. See
    # docs/OBSERVABILITY_PLAN_V2.md section 1.2.
    excluded_handlers=["/metrics", "/health", "^/$"],
)
instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


class ChatRequest(BaseModel):
    query: str = Field(..., max_length=2000)
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sources: dict[str, list[str]] = {
        "rules": [], "rulings": [], "web_links": [], "images": [], "citations": [],
    }
    conversation_id: str


judge_agent: MTGJudgeAgent | None = None


def _authenticate(request: Request) -> bool:
    """True if the request carries a valid API key (authenticated tier: e.g. the
    Discord bot). False for keyless callers (anonymous tier: the public PWA,
    which can't keep a client-side key secret) -- allowed through, not rejected,
    but subject to a stricter daily quota. Only raises when a key IS present but
    doesn't match -- a caller that tries and fails a key is rejected outright,
    not silently downgraded to anonymous."""
    api_key = request.headers.get("X-API-Key")
    if api_key is None:
        return False
    if Config.API_KEYS and api_key not in Config.API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return bool(Config.API_KEYS)


def _check_and_increment_quota(bucket_key: str, authenticated: bool) -> None:
    limit = Config.DAILY_QUOTA_AUTHENTICATED if authenticated else Config.DAILY_QUOTA_ANONYMOUS
    day = datetime.now(timezone.utc).date().isoformat()
    with sqlite3.connect(Config.CONVERSATION_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO usage_counters (bucket_key, day, count) VALUES (?, ?, 1) "
            "ON CONFLICT(bucket_key, day) DO UPDATE SET count = count + 1",
            (bucket_key, day),
        )
        count = conn.execute(
            "SELECT count FROM usage_counters WHERE bucket_key = ? AND day = ?",
            (bucket_key, day),
        ).fetchone()[0]
    if count > limit:
        raise HTTPException(status_code=429, detail="Daily request quota exceeded.")


async def _validate_chat_request(request: Request, chat_request: ChatRequest) -> tuple[str, bool]:
    """Shared pre-checks for /chat and /chat/stream. Returns (thread_id, authenticated)."""
    authenticated = _authenticate(request)
    # sqlite3 is sync -- run off the event loop, mirroring _check_mcp_health below.
    await asyncio.to_thread(_check_and_increment_quota, _rate_limit_key(request), authenticated)
    if not chat_request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    if judge_agent is None:
        raise HTTPException(
            status_code=503, detail="Service not ready. Please wait for initialization."
        )
    thread_id = chat_request.conversation_id or uuid.uuid4().hex
    return thread_id, authenticated


@app.get("/", response_class=FileResponse, include_in_schema=False)
async def serve_index() -> FileResponse:
    """Serves a zero-build browser test harness for developers to interact with the MTG Judge Chatbot.

    Serving this lightweight single-page interface directly from FastAPI eliminates external CDN
    dependencies, avoids separate build pipelines, and allows manual testing in both host and
    containerized deployment environments. This is a developer tool, not the public frontend --
    see `webapp/` for the deployed PWA.
    """
    if not INDEX_FILE.is_file():
        raise HTTPException(status_code=404, detail="Frontend test UI not found")
    return FileResponse(
        INDEX_FILE,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.post("/chat", response_model=ChatResponse)
@limiter.limit(f"{Config.RATE_LIMIT_PER_MINUTE}/minute")
async def chat(request: Request, chat_request: ChatRequest):
    thread_id, _authenticated = await _validate_chat_request(request, chat_request)
    result = await judge_agent.query(chat_request.query, thread_id=thread_id)
    return ChatResponse(**result, conversation_id=thread_id)


async def _sse_chat_events(user_query: str, thread_id: str):
    start_time = time.perf_counter()
    first_token_recorded = False
    try:
        async for kind, payload in judge_agent.stream_tokens(user_query, thread_id=thread_id):
            if kind == "token":
                if not first_token_recorded:
                    HTTP_STREAMING_TTFT_SECONDS.observe(time.perf_counter() - start_time)
                    first_token_recorded = True
                yield f"event: token\ndata: {json.dumps({'text': payload})}\n\n"
            elif kind == "error":
                yield f"event: error\ndata: {json.dumps({'message': payload})}\n\n"
                return
            elif kind == "sources":
                yield f"event: sources\ndata: {json.dumps(payload)}\n\n"
    except Exception:
        logger.exception("Streaming agent run failed for query: %r", user_query)
        yield f"event: error\ndata: {json.dumps({'message': 'I ran into an error processing your question. Please try again.'})}\n\n"
        return
    yield f"event: done\ndata: {json.dumps({'conversation_id': thread_id})}\n\n"


@app.post("/chat/stream")
@limiter.limit(f"{Config.RATE_LIMIT_PER_MINUTE}/minute")
async def chat_stream(request: Request, chat_request: ChatRequest):
    thread_id, _authenticated = await _validate_chat_request(request, chat_request)
    return StreamingResponse(
        _sse_chat_events(chat_request.query, thread_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _mcp_health_url(mcp_url: str) -> str:
    base = mcp_url.rsplit("/mcp", 1)[0]
    return f"{base}/health"


def _check_mcp_health(url: str) -> bool:
    try:
        response = requests.get(_mcp_health_url(url), timeout=2)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


@app.get("/health")
async def health_check():
    names = ("rules_mcp", "scryfall_mcp")
    urls = (Config.RULES_MCP_URL, Config.SCRYFALL_MCP_URL)
    # requests is sync -- run the checks off the event loop rather than blocking it.
    results = await asyncio.gather(*(asyncio.to_thread(_check_mcp_health, url) for url in urls))
    mcp_status = dict(zip(names, results))

    return {
        "status": "healthy",
        "provider": Config.LLM_PROVIDER,
        "ready": judge_agent is not None,
        "mcp_servers": mcp_status,
    }
