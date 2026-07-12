"""Data-driven tests: load hook_samples.json and assert each scenario."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from classifier.engine.factory import build_rules
from classifier.engine.pipeline import RulePipeline
from classifier.schemas import PreToolUseEvent
from classifier.settings import BehaviorConfig, RuleSpec


SAMPLES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "hook_samples.json"


@pytest.fixture(scope="module")
def pipeline() -> RulePipeline:
    rules = build_rules([
        RuleSpec(id="R-001", type="denylist_cmd", priority=10, severity="critical"),
        RuleSpec(id="R-002", type="sensitive_path", priority=10, severity="high"),
        RuleSpec(id="R-003", type="branch_protect", priority=20, severity="high"),
    ])
    return RulePipeline(rules=rules, behavior=BehaviorConfig(enable_claude_fallback=False), fallback=None)


def _load_samples() -> list[dict]:
    with SAMPLES_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _build_event(sample: dict) -> PreToolUseEvent:
    ti: dict = {}
    if "command" in sample:
        ti["command"] = sample["command"]
    if "file_path" in sample:
        ti["file_path"] = sample["file_path"]
    return PreToolUseEvent(tool_name=sample["tool_name"], tool_input=ti)


def _names() -> list[str]:
    return [s["name"] for s in _load_samples()]


@pytest.mark.parametrize("sample", _load_samples(), ids=_names())
def test_sample(pipeline, sample):
    d = asyncio.run(pipeline.run(_build_event(sample)))
    assert d.decision == sample["expected_decision"], sample["name"]
    assert d.hookSpecificOutput["permissionDecision"] == sample["expected_permission"], sample["name"]
    if sample["expected_rule"] is None:
        assert d.matched_rule is None, sample["name"]
    else:
        assert d.matched_rule is not None, sample["name"]
        assert d.matched_rule.id == sample["expected_rule"], sample["name"]