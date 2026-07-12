"""FastAPI integration tests using TestClient (no real uvicorn needed)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from classifier.engine.pipeline import RulePipeline
from classifier.main import create_app
from classifier.settings import (
    AuthConfig,
    BehaviorConfig,
    LoggingConfig,
    RuleSpec,
    RulesConfig,
    ServiceConfig,
    Settings,
)


def _make_app(behavior: BehaviorConfig | None = None) -> TestClient:
    settings = Settings(
        service=ServiceConfig(),
        auth=AuthConfig(),
        behavior=behavior or BehaviorConfig(enable_claude_fallback=False),
        logging=LoggingConfig(file=""),  # disable file logging
        rules=RulesConfig(rules=[
            RuleSpec(id="R-001", type="denylist_cmd", priority=10, severity="critical"),
            RuleSpec(id="R-002", type="sensitive_path", priority=10, severity="high"),
            RuleSpec(id="R-003", type="branch_protect", priority=20, severity="high"),
        ]),
    )
    app = create_app(settings=settings)
    return TestClient(app)


def test_health():
    c = _make_app()
    r = c.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["rules"] == 3


def test_classify_denies_dangerous_command():
    c = _make_app()
    r = c.post("/classify", json={"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "block"
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert body["matched_rule"]["id"].startswith("R-001")


def test_classify_denies_env_write():
    c = _make_app()
    r = c.post("/classify", json={"tool_name": "Write", "tool_input": {"file_path": "/repo/.env"}})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "block"
    assert body["matched_rule"]["id"] == "R-002"


def test_classify_allows_echo():
    c = _make_app()
    r = c.post("/classify", json={"tool_name": "Bash", "tool_input": {"command": "echo hi"}})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "approve"
    assert body["matched_rule"] is None


def test_classify_invalid_payload_fails_open():
    c = _make_app(BehaviorConfig(fail_open_on_error=True, enable_claude_fallback=False))
    r = c.post("/classify", json={"totally": "wrong"})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "approve"
    assert "invalid" in (body.get("reason") or "").lower()


def test_classify_auth_required_when_token_set():
    settings = Settings(
        service=ServiceConfig(),
        auth=AuthConfig(bridge_token="secret"),
        behavior=BehaviorConfig(enable_claude_fallback=False),
        logging=LoggingConfig(file=""),
        rules=RulesConfig(rules=[]),
    )
    c = TestClient(create_app(settings=settings))
    r = c.post("/classify", json={"tool_name": "Bash", "tool_input": {"command": "x"}})
    assert r.status_code == 401

    r = c.post(
        "/classify",
        json={"tool_name": "Bash", "tool_input": {"command": "x"}},
        headers={"X-Bridge-Token": "secret"},
    )
    assert r.status_code == 200