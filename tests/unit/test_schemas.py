"""Unit tests for schemas."""

from __future__ import annotations

from classifier.schemas import Decision, PreToolUseEvent, RuleHit


def test_pretooluse_basic():
    e = PreToolUseEvent(
        tool_name="Bash",
        tool_input={"command": "rm -rf /"},
    )
    assert e.tool_name == "Bash"
    assert e.tool_input.command == "rm -rf /"


def test_pretooluse_extra_fields_allowed():
    e = PreToolUseEvent.model_validate({
        "tool_name": "Bash",
        "tool_input": {"command": "x"},
        "session_id": "abc",
        "unknown_future_field": 123,
    })
    assert e.session_id == "abc"


def test_decision_dual_protocol():
    d = Decision(
        decision="block",
        hookSpecificOutput={"hookEventName": "PreToolUse", "permissionDecision": "deny"},
        matched_rule=RuleHit(id="R-001", type="denylist_cmd", priority=10, severity="critical"),
    )
    assert d.decision == "block"
    assert d.hookSpecificOutput["permissionDecision"] == "deny"
    assert d.matched_rule.id == "R-001"