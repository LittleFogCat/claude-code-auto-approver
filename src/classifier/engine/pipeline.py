"""Decision composition pipeline.

Order of operations per request:
1. Build a normalized ``PipelineContext``.
2. Fan out to all enabled rules concurrently (``asyncio.gather``).
3. If any rule hit -> pick the most severe (critical > high > medium > low),
   tie-broken by lower priority number (more important rule wins).
4. Else -> ask the Claude fallback (if enabled) to classify.
5. Else / on error -> apply ``fail_open_on_error`` default (allow or deny).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from classifier.engine.fallback import ClaudeFallback
from classifier.engine.rule import Rule
from classifier.schemas import Decision, PipelineContext, PreToolUseEvent, RuleHit, Severity
from classifier.settings import BehaviorConfig

logger = logging.getLogger("classifier.engine.pipeline")

_SEVERITY_RANK: dict[Severity, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


def _to_pipeline_context(event: PreToolUseEvent) -> PipelineContext:
    inp = event.tool_input
    return PipelineContext(
        tool_name=event.tool_name,
        command=inp.command,
        file_path=inp.file_path,
        cwd=event.cwd,
        session_id=event.session_id,
        raw_event=event.model_dump(),
    )


def _hit_to_decision(hit: RuleHit) -> Decision:
    """Map a rule hit to a final Decision."""
    sev = hit.severity
    if sev in ("critical", "high"):
        permission = "deny"
        legacy = "block"
    elif sev == "medium":
        permission = "ask"
        legacy = "block"  # 'ask' is a new protocol; legacy maps to block so the user is prompted
    else:  # low
        permission = "allow"
        legacy = "approve"
    return Decision(
        decision=legacy,
        hookSpecificOutput={
            "hookEventName": "PreToolUse",
            "permissionDecision": permission,
        },
        matched_rule=hit,
        reason=hit.reason,
    )


def _pick_best_hit(hits: list[RuleHit]) -> RuleHit:
    """Pick the most severe hit; tie-break by lower priority number."""
    return max(
        hits,
        key=lambda h: (_SEVERITY_RANK[h.severity], -h.priority),
    )


class RulePipeline:
    def __init__(
        self,
        rules: list[Rule],
        behavior: BehaviorConfig,
        fallback: ClaudeFallback | None = None,
    ) -> None:
        self.rules = rules
        self.behavior = behavior
        self.fallback = fallback

    async def run(self, event: PreToolUseEvent) -> Decision:
        ctx = _to_pipeline_context(event)

        # ---- Stage 1: rules (concurrent) -------------------------------
        hits: list[RuleHit] = []
        if self.rules:
            results = await asyncio.gather(
                *(r.evaluate(ctx) for r in self.rules),
                return_exceptions=True,
            )
            for r, res in zip(self.rules, results):
                if isinstance(res, Exception):
                    logger.warning(
                        "rule raised; skipping",
                        extra={"rule_id": r.spec_id, "err": str(res)},
                    )
                    continue
                if res is not None:
                    hits.append(res)

        if hits:
            best = _pick_best_hit(hits)
            logger.info(
                "rule match",
                extra={
                    "rule_id": best.id,
                    "severity": best.severity,
                    "priority": best.priority,
                    "hits": len(hits),
                },
            )
            return _hit_to_decision(best)

        # ---- Stage 2: Claude fallback ---------------------------------
        if self.behavior.enable_claude_fallback and self.fallback is not None:
            try:
                decision = await self.fallback.classify(ctx)
                if decision is not None:
                    return decision
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "claude fallback failed; applying default",
                    extra={"err": str(e)},
                )
        elif not self.behavior.enable_claude_fallback:
            logger.debug("claude fallback disabled; using default")

        # ---- Stage 3: default behavior --------------------------------
        return _default_decision(self.behavior.fail_open_on_error, "no rule matched")


def _default_decision(fail_open: bool, reason: str) -> Decision:
    if fail_open:
        return Decision(
            decision="approve",
            hookSpecificOutput={
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            },
            reason=reason,
        )
    return Decision(
        decision="block",
        hookSpecificOutput={
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
        },
        reason=reason,
    )