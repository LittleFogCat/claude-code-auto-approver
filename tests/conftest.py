"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from classifier.engine.factory import build_rules
from classifier.engine.pipeline import RulePipeline
from classifier.settings import (
    AuthConfig,
    BehaviorConfig,
    LoggingConfig,
    RuleSpec,
    RulesConfig,
    ServiceConfig,
    Settings,
)


@pytest.fixture
def default_behavior() -> BehaviorConfig:
    return BehaviorConfig()


@pytest.fixture
def strict_behavior() -> BehaviorConfig:
    return BehaviorConfig(fail_open_on_error=False)


@pytest.fixture
def no_fallback_behavior() -> BehaviorConfig:
    return BehaviorConfig(enable_claude_fallback=False)


@pytest.fixture
def all_rules_specs() -> list[RuleSpec]:
    return [
        RuleSpec(id="R-001", type="denylist_cmd", priority=10, severity="critical"),
        RuleSpec(id="R-002", type="sensitive_path", priority=10, severity="high"),
        RuleSpec(id="R-003", type="branch_protect", priority=20, severity="high"),
    ]


@pytest.fixture
def rules(all_rules_specs):
    return build_rules(all_rules_specs)


@pytest.fixture
def pipeline(rules, default_behavior) -> RulePipeline:
    return RulePipeline(rules=rules, behavior=default_behavior, fallback=None)


@pytest.fixture
def strict_pipeline(rules, strict_behavior) -> RulePipeline:
    return RulePipeline(rules=rules, behavior=strict_behavior, fallback=None)


@pytest.fixture
def settings_with_rules(all_rules_specs) -> Settings:
    return Settings(
        service=ServiceConfig(),
        auth=AuthConfig(),
        behavior=BehaviorConfig(enable_claude_fallback=False),
        logging=LoggingConfig(),
        rules=RulesConfig(rules=all_rules_specs),
    )