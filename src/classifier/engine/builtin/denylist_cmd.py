"""R-001: Denylist of dangerous shell commands.

Patterns target whole commands or piped chains, e.g.:
- ``rm -rf /``
- ``sudo ...``
- ``curl ... | sh``
- ``chmod -R 777 ...``
- ``mkfs ...``
- ``dd if=/dev/... of=...``
"""

from __future__ import annotations

import re

from classifier.engine.rule import Rule, compile_pattern, pattern_hits
from classifier.schemas import PipelineContext, RuleHit
from classifier.settings import RuleSpec


# Sensible default patterns. Severity: critical (block on sight).
DEFAULT_PATTERNS: list[str] = [
    r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*f[a-zA-Z]*\b\s+/",
    r"\brm\s+-[a-zA-Z]*[fF][a-zA-Z]*[rR][a-zA-Z]*\b",
    r"\bsudo\b",
    r"\bcurl\b[^|;\n]*\|\s*(sh|bash)\b",
    r"\bwget\b[^|;\n]*\|\s*(sh|bash)\b",
    r"\bchmod\s+(-R\s+)?777\b",
    r"\bmkfs(\.[a-z0-9]+)?\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{.*\};:",  # fork bomb
    r"\beval\b\s*\\?\$\(.*curl",  # eval $curl
    r"\bnc\s+-e\b",  # netcat exec
    r"\b(sh|bash|sh5?)\s+<\s*\(curl|wget\)",
]


class DenylistCmdRule(Rule):
    def __init__(
        self,
        spec_id: str,
        patterns: list[str],
        priority: int = 10,
        severity: str = "critical",
        enabled: bool = True,
        reason: str | None = None,
    ) -> None:
        super().__init__(
            spec_id=spec_id,
            type="denylist_cmd",
            priority=priority,
            severity=severity,  # type: ignore[arg-type]
            enabled=enabled,
        )
        self.reason = reason or "command matches denylist pattern"
        self.compiled = [compile_pattern(p, re.IGNORECASE) for p in patterns]

    @classmethod
    def from_spec(cls, spec: RuleSpec) -> "DenylistCmdRule":
        patterns = DEFAULT_PATTERNS if spec.pattern == "*DEFAULT*" else [spec.pattern] if spec.pattern else DEFAULT_PATTERNS
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