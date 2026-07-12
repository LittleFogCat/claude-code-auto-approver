"""Unit tests for the Claude fallback adapter."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from classifier.engine.fallback import ClaudeFallback
from classifier.schemas import PipelineContext


class _FakeBlock:
    def __init__(self, type_: str, name: str = "", input_: dict | None = None):
        self.type = type_
        self.name = name
        self.input = input_ or {}


class _FakeResponse:
    def __init__(self, blocks: list):
        self.content = blocks


def _make_fallback(blocks, api_key="fake", raise_exc=None):
    fb = ClaudeFallback()
    fb.client = MagicMock()
    fb.client.api_key = api_key
    if raise_exc is not None:
        fb.client.messages_create = AsyncMock(side_effect=raise_exc)
    else:
        fb.client.messages_create = AsyncMock(return_value=_FakeResponse(blocks))
    return fb


def test_fallback_deny():
    block = _FakeBlock("tool_use", name="classify_tool_call", input_={"decision": "deny", "reason": "danger", "risk_level": "high"})
    fb = _make_fallback([block])
    ctx = PipelineContext(tool_name="Bash", command="rm -rf /", cwd="/tmp")
    d = asyncio.run(fb.classify(ctx))
    assert d is not None
    assert d.decision == "block"
    assert d.hookSpecificOutput["permissionDecision"] == "deny"
    assert d.reason == "danger"


def test_fallback_allow():
    block = _FakeBlock("tool_use", name="classify_tool_call", input_={"decision": "allow", "reason": "ok", "risk_level": "low"})
    fb = _make_fallback([block])
    ctx = PipelineContext(tool_name="Read", file_path="/repo/README.md")
    d = asyncio.run(fb.classify(ctx))
    assert d is not None
    assert d.decision == "approve"
    assert d.hookSpecificOutput["permissionDecision"] == "allow"


def test_fallback_no_api_key_returns_none():
    fb = _make_fallback([], api_key=None)
    ctx = PipelineContext(tool_name="Bash", command="x")
    assert asyncio.run(fb.classify(ctx)) is None


def test_fallback_no_tool_use_returns_none():
    fb = _make_fallback([_FakeBlock("text")])
    ctx = PipelineContext(tool_name="Bash", command="x")
    assert asyncio.run(fb.classify(ctx)) is None


def test_fallback_invalid_decision_returns_none():
    block = _FakeBlock("tool_use", name="classify_tool_call", input_={"decision": "maybe", "reason": "x", "risk_level": "low"})
    fb = _make_fallback([block])
    ctx = PipelineContext(tool_name="Bash", command="x")
    assert asyncio.run(fb.classify(ctx)) is None


def test_fallback_call_failure_propagates():
    fb = _make_fallback([], raise_exc=RuntimeError("boom"))
    ctx = PipelineContext(tool_name="Bash", command="x")
    with pytest.raises(RuntimeError):
        asyncio.run(fb.classify(ctx))