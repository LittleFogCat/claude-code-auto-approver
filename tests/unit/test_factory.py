"""Unit tests for rule factory and built-in rules."""

from __future__ import annotations

import asyncio

import pytest

from classifier.engine.factory import build_rules
from classifier.schemas import PipelineContext
from classifier.settings import RuleSpec


def test_denylist_cmd_blocks_rm_rf():
    spec = RuleSpec(id="R-001", type="denylist_cmd", priority=10, severity="critical")
    rule = build_rules([spec])[0]
    ctx = PipelineContext(tool_name="Bash", command="rm -rf /")
    hit = asyncio.run(rule.evaluate(ctx))
    assert hit is not None
    assert hit.id == "R-001"
    assert hit.severity == "critical"


def test_denylist_cmd_allows_echo():
    spec = RuleSpec(id="R-001", type="denylist_cmd", priority=10, severity="critical")
    rule = build_rules([spec])[0]
    ctx = PipelineContext(tool_name="Bash", command="echo hello")
    assert asyncio.run(rule.evaluate(ctx)) is None


def test_denylist_cmd_only_bash_tool():
    spec = RuleSpec(id="R-001", type="denylist_cmd", priority=10, severity="critical")
    rule = build_rules([spec])[0]
    ctx = PipelineContext(tool_name="Read", command="rm -rf /")
    assert asyncio.run(rule.evaluate(ctx)) is None


def test_sensitive_path_blocks_env():
    spec = RuleSpec(id="R-002", type="sensitive_path", priority=10, severity="high")
    rule = build_rules([spec])[0]
    ctx = PipelineContext(tool_name="Write", file_path="/repo/.env")
    hit = asyncio.run(rule.evaluate(ctx))
    assert hit is not None
    assert hit.severity == "high"


def test_sensitive_path_windows_id_rsa():
    spec = RuleSpec(id="R-002", type="sensitive_path", priority=10, severity="high")
    rule = build_rules([spec])[0]
    ctx = PipelineContext(tool_name="Edit", file_path="C:\\Users\\alice\\.ssh\\id_rsa")
    hit = asyncio.run(rule.evaluate(ctx))
    assert hit is not None


def test_sensitive_path_allows_safe():
    spec = RuleSpec(id="R-002", type="sensitive_path", priority=10, severity="high")
    rule = build_rules([spec])[0]
    ctx = PipelineContext(tool_name="Edit", file_path="/repo/README.md")
    assert asyncio.run(rule.evaluate(ctx)) is None


def test_branch_protect_blocks_main_push():
    spec = RuleSpec(id="R-003", type="branch_protect", priority=20, severity="high")
    rule = build_rules([spec])[0]
    ctx = PipelineContext(tool_name="Bash", command="git push origin main")
    hit = asyncio.run(rule.evaluate(ctx))
    assert hit is not None
    assert hit.id == "R-003"


def test_branch_protect_allows_feature_push():
    spec = RuleSpec(id="R-003", type="branch_protect", priority=20, severity="high")
    rule = build_rules([spec])[0]
    ctx = PipelineContext(tool_name="Bash", command="git push origin feature-branch")
    assert asyncio.run(rule.evaluate(ctx)) is None


def test_factory_skips_disabled_rules():
    specs = [
        RuleSpec(id="R-001", type="denylist_cmd", priority=10, severity="critical", enabled=False),
    ]
    assert build_rules(specs) == []


def test_factory_skips_unknown_type():
    specs = [
        RuleSpec(id="R-XXX", type="nonexistent", priority=10, severity="high"),
    ]
    assert build_rules(specs) == []