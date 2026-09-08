import pytest
from fastapi.testclient import TestClient

from app_api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_metrics_endpoint_exposes_prometheus_format(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")


def test_metrics_endpoint_not_in_openapi_schema(client: TestClient) -> None:
    """/metrics is internal (loopback/mtg-network only, see Caddyfile's @api
    matcher never including it) -- shouldn't show up in the public API docs."""
    schema = client.get("/openapi.json").json()
    assert "/metrics" not in schema["paths"]


def test_http_requests_total_increments_for_real_requests(client: TestClient) -> None:
    """Guards against the exact regression docs/OBSERVABILITY_PLAN_V2.md
    section 1.2 describes: an unanchored '/' in excluded_handlers matches
    every path (re.search, not an exact match), which would silently zero
    out http_requests_total for all real traffic while /metrics itself still
    looked fine on a superficial check. Uses /openapi.json, not /health --
    /health is deliberately in excluded_handlers (unaffected by the 1.2 bug,
    which was about the "/" entry, not the "/health" one) so it never
    increments this counter by design."""
    client.get("/openapi.json")
    body = client.get("/metrics").text
    assert 'handler="/openapi.json"' in body
    assert "http_requests_total" in body
