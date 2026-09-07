"""Prometheus metric definitions shared across app_api's request handlers.

Deliberately does NOT include per-tool-call metrics (agent_tool_calls_total /
agent_tool_duration_seconds) -- that instrumentation touches
llm_agent/agent.py's ToolNode callback wiring and is scoped as separate
follow-up work, not part of this endpoint-level pass. See
docs/OBSERVABILITY_PLAN_V2.md section 4.A.3.
"""

from prometheus_client import Histogram

# /chat/stream's perceived-responsiveness SLI (SLO 2 in
# docs/OBSERVABILITY_PLAN_V2.md): time from request start to the first
# streamed token, not the full connection lifetime -- the default
# http_request_duration_seconds histogram Instrumentator adds times the
# entire SSE connection for a streaming route, which isn't the same thing
# (see that doc's section 1.5).
HTTP_STREAMING_TTFT_SECONDS = Histogram(
    "http_streaming_ttft_seconds",
    "Time to first streamed token on /chat/stream",
    buckets=[0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 8.0],
)
