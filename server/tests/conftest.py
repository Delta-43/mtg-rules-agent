from pathlib import Path

import pytest

from app_api import main


@pytest.fixture(autouse=True)
def isolated_conversation_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirects Config.CONVERSATION_DB_PATH to a per-test temp file, autoused across
    every test in this directory.

    Without this, any test that exercises a /chat(-adjacent) code path silently reads
    and writes the real production conversations.db at the default, unoverridden
    Config.CONVERSATION_DB_PATH -- _check_and_increment_quota() (main.py) runs on
    every /chat and /chat/stream request, before query validation, so even a request
    a test expects to be rejected as invalid still touches that file first. On a
    deployment where that file is root-owned (as it is here, written by the live
    container), a host-run pytest hits "attempt to write a readonly database" instead
    of the test's actual assertion -- and on a deployment where it's *not*
    permission-locked, tests would instead silently read/write real user data.

    TestClient(app) (the `client` fixture in this directory) is never used as a
    context manager, so FastAPI's lifespan (and its own _init_usage_counters_db()
    call) never runs -- calling it here explicitly is what actually creates the
    usage_counters table in the fresh temp file, without triggering the rest of
    lifespan's real agent/MCP-client construction, which needs live external
    services this suite is deliberately not exercising (see CLAUDE.md's Commands
    section).
    """
    db_path = tmp_path / "test_conversations.db"
    monkeypatch.setattr(main.Config, "CONVERSATION_DB_PATH", str(db_path))
    main._init_usage_counters_db()
