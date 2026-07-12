"""Unit tests for the decision pipeline."""

from __future__ import annotations

import asyncio

import pytest

from classifier.engine.factory import build_rules
from classifier.engine.pipeline import RulePipeline
from classifier.schemas import PreToolUseEvent
from classifier.settings import BehaviorConfig, RuleSpec


def _evt(tool_name: str, **kwargs) -> PreToolUseEvent:
    ti: dict = {}
    if "command" in kwargs:
        ti["command"] = kwargs["command"]
    if "file_path" in kwargs:
        ti["file_path"] = kwargs["file_path"]
    return PreToolUseEvent(tool_name=tool_name, tool_input=ti)


@pytest.fixture
def rules():
    return build_rules([
        RuleSpec(id="R-001", type="denylist_cmd", priority=10, severity="critical"),
        RuleSpec(id="R-002", type="sensitive_path", priority=10, severity="high"),
        RuleSpec(id="R-003", type="branch_protect", priority=20, severity="high"),
    ])


def test_pipeline_deny_critical(rules):
    p = RulePipeline(rules=rules, behavior=BehaviorConfig(enable_claude_fallback=False), fallback=None)
    d = asyncio.run(p.run(_evt("Bash", command="rm -rf /")))
    assert d.decision == "block"
    assert d.hookSpecificOutput["permissionDecision"] == "deny"
    assert d.matched_rule is not None
    assert d.matched_rule.id == "R-001"


def test_pipeline_deny_main_push(rules):
    p = RulePipeline(rules=rules, behavior=BehaviorConfig(enable_claude_fallback=False), fallback=None)
    d = asyncio.run(p.run(_evt("Bash", command="git push origin main")))
    assert d.decision == "block"
    assert d.matched_rule is not None
    assert d.matched_rule.id == "R-003"


def test_pipeline_deny_env_write(rules):
    p = RulePipeline(rules=rules, behavior=BehaviorConfig(enable_claude_fallback=False), fallback=None)
    d = asyncio.run(p.run(_evt("Write", file_path="/repo/.env")))
    assert d.decision == "block"
    assert d.matched_rule.id == "R-002"


def test_pipeline_allow_safe(rules):
    p = RulePipeline(rules=rules, behavior=BehaviorConfig(enable_claude_fallback=False), fallback=None)
    d = asyncio.run(p.run(_evt("Bash", command="echo hi")))
    assert d.decision == "approve"
    assert d.hookSpecificOutput["permissionDecision"] == "allow"
    assert d.matched_rule is None


def test_pipeline_fail_open_default(rules):
    p = RulePipeline(
        rules=rules,
        behavior=BehaviorConfig(fail_open_on_error=True, enable_claude_fallback=False),
        fallback=None,
    )
    d = asyncio.run(p.run(_evt("Bash", command="something weird but safe")))
    assert d.decision == "approve"
    assert d.hookSpecificOutput["permissionDecision"] == "allow"


def test_pipeline_fail_closed_default(rules):
    p = RulePipeline(
        rules=rules,
        behavior=BehaviorConfig(fail_open_on_error=False, enable_claude_fallback=False),
        fallback=None,
    )
    d = asyncio.run(p.run(_evt("Bash", command="something weird but safe")))
    assert d.decision == "block"
    assert d.hookSpecificOutput["permissionDecision"] == "deny"


def test_pipeline_pick_most_severe(rules):
    p = RulePipeline(rules=rules, behavior=BehaviorConfig(enable_claude_fallback=False), fallback=None)
    d = asyncio.run(p.run(_evt("Bash", command="sudo rm -rf / && git push origin main")))
    assert d.matched_rule is not None
    assert d.matched_rule.id == "R-001"


def test_pipeline_tie_break_priority():
    specs = [
        RuleSpec(id="HIGH-A", type="denylist_cmd", priority=5, severity="high"),
        RuleSpec(id="HIGH-B", type="denylist_cmd", priority=50, severity="high"),
    ]
    rs = build_rules(specs)
    p = RulePipeline(rules=rs, behavior=BehaviorConfig(enable_claude_fallback=False), fallback=None)
    d = asyncio.run(p.run(_evt("Bash", command="sudo something")))
    assert d.matched_rule.id == "HIGH-A"


def test_pipeline_no_rules_no_fallback():
    p = RulePipeline(rules=[], behavior=BehaviorConfig(fail_open_on_error=True), fallback=None)
    d = asyncio.run(p.run(_evt("Bash", command="anything")))
    assert d.decision == "approve"