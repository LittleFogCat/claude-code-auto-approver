"""R-002: Sensitive file paths.

Used by Edit / Write / NotebookEdit -- if the target path matches, deny.
Also applied to Bash commands that touch sensitive paths via heuristic (simple
``cat <sensitive>`` style), but the strong signal is from the file_path field.
"""

from __future__ import annotations

from classifier.engine.rule import Rule, glob_match
from classifier.schemas import PipelineContext, RuleHit
from classifier.settings import RuleSpec

DEFAULT_PATHS: list[str] = [
    "**/.env",
    "**/.env.*",
    "**/.envrc",
    "**/id_rsa",
    "**/id_ed25519",
    "**/id_dsa",
    "**/id_ecdsa",
    "**/.ssh/id_*",
    "**/.aws/credentials",
    "**/.aws/config",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.pfx",
    "**/secrets.yaml",
    "**/secrets.yml",
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    # Windows-friendly
    "C:/Users/*/.ssh/id_*",
    "C:/Users/*/.aws/credentials",
    "**/.npmrc",
    "**/.pypirc",
    "**/.netrc",
]

# Edit/Write/NotebookEdit tools should match by file_path.
_PATH_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit", "read_file", "write_file"}


class SensitivePathRule(Rule):
    def __init__(
        self,
        spec_id: str,
        paths: list[str],
        priority: int = 10,
        severity: str = "high",
        enabled: bool = True,
        reason: str | None = None,
    ) -> None:
        super().__init__(
            spec_id=spec_id,
            type="sensitive_path",
            priority=priority,
            severity=severity,  # type: ignore[arg-type]
            enabled=enabled,
        )
        self.reason = reason or "target path is in sensitive list"
        self.paths = paths

    @classmethod
    def from_spec(cls, spec: RuleSpec) -> "SensitivePathRule":
        paths = spec.paths if spec.paths else DEFAULT_PATHS
        return cls(
            spec_id=spec.id,
            paths=paths,
            priority=spec.priority,
            severity=spec.severity,
            enabled=spec.enabled,
            reason=spec.reason,
        )

    async def evaluate(self, ctx: PipelineContext) -> RuleHit | None:
        if not self.enabled:
            return None
        # File-tool signal: target file_path
        if ctx.tool_name in _PATH_TOOLS and ctx.file_path:
            for p in self.paths:
                if glob_match(ctx.file_path, p):
                    return RuleHit(
                        id=self.spec_id,
                        type=self.type,
                        priority=self.priority,
                        severity=self.severity,
                        reason=self.reason,
                    )
        # Bash signal: scan command for any sensitive path string
        if ctx.tool_name in {"Bash", "bash", "shell", "Shell"} and ctx.command:
            for p in self.paths:
                if glob_match(ctx.command, p):
                    return RuleHit(
                        id=self.spec_id,
                        type=self.type,
                        priority=self.priority,
                        severity=self.severity,
                        reason=self.reason,
                    )
        return None