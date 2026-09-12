import sqlite3

import pytest
from fastapi.testclient import TestClient

from app_api.main import Config, _client_ip, app
from fastapi import Request


def _fake_request(headers: dict[str, str]) -> Request:
    """Builds a minimal real Request with a raw socket peer of 172.25.0.2
    (a real reverse proxy's bridge IP in a Docker Compose deployment, per
    `docker network inspect` -- see _client_ip's docstring) so a test that
    forgets to set any of the proxy headers exercises the exact same
    fallback path a real proxied deployment hits for non-proxied requests,
    not an arbitrary placeholder.
    """
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("172.25.0.2", 12345),
    }
    return Request(scope)


def test_client_ip_prefers_cf_connecting_ip() -> None:
    request = _fake_request({"CF-Connecting-IP": "203.0.113.42", "X-Forwarded-For": "1.2.3.4"})
    assert _client_ip(request) == "203.0.113.42"


def test_client_ip_falls_back_to_x_forwarded_for() -> None:
    request = _fake_request({"X-Forwarded-For": "198.51.100.7, 172.25.0.2"})
    assert _client_ip(request) == "198.51.100.7"


def test_client_ip_falls_back_to_socket_peer_with_no_proxy_headers() -> None:
    request = _fake_request({})
    assert _client_ip(request) == "172.25.0.2"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_anonymous_requests_bucket_by_real_client_ip_not_by_proxy_ip(client: TestClient) -> None:
    """Regression test for a real bug found in an early deployment: every
    anonymous request proxied through a reverse proxy has the same raw
    socket peer (the proxy's own bridge IP), so before _client_ip existed,
    every anonymous visitor -- combined -- shared one single rate-limit/quota
    bucket instead of one bucket each. Confirmed against a real Docker
    Compose deployment: 172.25.0.2 (the proxy's bridge IP) was the bucket
    key for every proxied request regardless of the real visitor's IP.

    Sends two requests carrying different CF-Connecting-IP headers (as a
    reverse proxy would forward from Cloudflare's edge) and asserts they
    land in two separate usage_counters rows, not one shared row.
    """
    client.post("/chat", json={"query": ""}, headers={"CF-Connecting-IP": "203.0.113.10"})
    client.post("/chat", json={"query": ""}, headers={"CF-Connecting-IP": "203.0.113.20"})

    with sqlite3.connect(Config.CONVERSATION_DB_PATH) as conn:
        rows = conn.execute(
            "SELECT bucket_key, count FROM usage_counters WHERE bucket_key IN (?, ?)",
            ("203.0.113.10", "203.0.113.20"),
        ).fetchall()

    bucket_counts = dict(rows)
    assert bucket_counts.get("203.0.113.10") == 1
    assert bucket_counts.get("203.0.113.20") == 1
