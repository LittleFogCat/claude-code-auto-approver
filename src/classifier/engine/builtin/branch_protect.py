"""R-003: Branch protection -- block pushes to main/master."""

from __future__ import annotations

import re

from classifier.engine.rule import Rule, compile_pattern, pattern_hits
from classifier.schemas import PipelineContext, RuleHit
from classifier.settings import RuleSpec


DEFAULT_PATTERNS: list[str] = [
    r"\bgit\s+push\b[^\n]*?\b(main|master)\b",
    r"\bgit\s+push\b[^\n]*?\s+--force\b",
    r"\bgit\s+push\b[^\n]*?\s+-f\b",
    r"\bgit\s+push\b[^\n]*?\s+--force-with-lease\b",
]


class BranchProtectRule(Rule):
    def __init__(
        self,
        spec_id: str,
        patterns: list[str],
        priority: int = 20,
        severity: str = "high",
        enabled: bool = True,
        reason: str | None = None,
    ) -> None:
        super().__init__(
            spec_id=spec_id,
            type="branch_protect",
            priority=priority,
            severity=severity,  # type: ignore[arg-type]
            enabled=enabled,
        )
        self.reason = reason or "push to protected branch"
        self.compiled = [compile_pattern(p, re.IGNORECASE) for p in patterns]

    @classmethod
    def from_spec(cls, spec: RuleSpec) -> "BranchProtectRule":
        patterns = (
            DEFAULT_PATTERNS if spec.pattern == "*DEFAULT*" else [spec.pattern] if spec.pattern else DEFAULT_PATTERNS
        )
        return cls(
            spec_id=spec.id,
            patterns=patterns,
            priority=spec.priority,
            severity=spec.severity,
            enabled=spec.enabled,
            reason=spec.reason,
        )

    async def evaluate(self, ctx: PipelineContext) -> RuleHit | None:
        if not self.enabled or ctx.tool_name not in {"Bash", "bash", "shell", "Shell"}:
            return None
        cmd = ctx.command or ""
        if not cmd:
            return None
        for pat in self.compiled:
            if pattern_hits(cmd, pat):
                return RuleHit(
                    id=self.spec_id,
                    type=self.type,
                    priority=self.priority,
                    severity=self.severity,
                    reason=self.reason,
                )
        return None