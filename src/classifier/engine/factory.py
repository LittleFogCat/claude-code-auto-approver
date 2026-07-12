"""Build concrete Rule instances from YAML specs."""

from __future__ import annotations

import logging
import re
from typing import Any

from classifier.engine.rule import Rule
from classifier.engine.builtin.denylist_cmd import DenylistCmdRule
from classifier.engine.builtin.sensitive_path import SensitivePathRule
from classifier.engine.builtin.branch_protect import BranchProtectRule
from classifier.settings import RuleSpec

logger = logging.getLogger("classifier.engine.factory")

# Map rule type -> rule class
_REGISTRY: dict[str, type[Rule]] = {
    "denylist_cmd": DenylistCmdRule,
    "sensitive_path": SensitivePathRule,
    "branch_protect": BranchProtectRule,
}


def build_rules(specs: list[RuleSpec]) -> list[Rule]:
    rules: list[Rule] = []
    for spec in specs:
        if not spec.enabled:
            continue
        cls = _REGISTRY.get(spec.type)
        if cls is None:
            logger.warning("unknown rule type, skipping", extra={"id": spec.id, "type": spec.type})
            continue
        try:
            rules.append(cls.from_spec(spec))
        except Exception as e:  # noqa: BLE001 - log and skip bad rule
            logger.warning(
                "failed to build rule, skipping",
                extra={"id": spec.id, "type": spec.type, "err": str(e)},
            )
    return rules