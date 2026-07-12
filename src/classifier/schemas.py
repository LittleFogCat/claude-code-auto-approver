"""Pydantic schemas for hook events and decisions.

We accept both legacy and new Claude Code hook protocols:
- Legacy: top-level ``decision`` ("approve" | "block") + exit code.
- New:    ``hookSpecificOutput.permissionDecision`` ("allow" | "deny" | "ask").

We always emit BOTH fields in the response so any Claude Code version is happy.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---- Decisions -----------------------------------------------------------

DecisionKind = Literal["allow", "deny", "ask"]
Severity = Literal["critical", "high", "medium", "low"]


class RuleHit(BaseModel):
    """A single rule that matched."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    priority: int
    severity: Severity
    reason: str | None = None


class Decision(BaseModel):
    """Decision returned to the hook.

    Both ``decision`` (legacy) and ``hookSpecificOutput.permissionDecision`` (new)
    are populated, so this works with any Claude Code version.
    """

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "block"]
    hookSpecificOutput: dict[str, Any] = Field(
        default_factory=lambda: {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    )
    matched_rule: RuleHit | None = None
    reason: str | None = None
    request_id: str | None = None


# ---- PreToolUse event ----------------------------------------------------


class ToolInput(BaseModel):
    """Best-effort tool input. We don't validate strictly -- unknown tools still pass."""

    model_config = ConfigDict(extra="allow")

    command: str | None = None
    file_path: str | None = None
    content: str | None = None
    new_string: str | None = None
    old_string: str | None = None
    replace_all: bool | None = None
    notebook_glob: str | None = None


class PreToolUseEvent(BaseModel):
    """The Claude Code PreToolUse event (subset of fields we care about)."""

    model_config = ConfigDict(extra="allow")

    session_id: str | None = None
    transcript_path: str | None = None
    cwd: str | None = None
    hook_event_name: Literal["PreToolUse"] = "PreToolUse"
    tool_name: str
    tool_input: ToolInput = Field(default_factory=ToolInput)


# ---- Pipeline context ----------------------------------------------------


class PipelineContext(BaseModel):
    """Normalized view passed to rules and the fallback."""

    model_config = ConfigDict(extra="allow")

    tool_name: str
    command: str | None = None
    file_path: str | None = None
    cwd: str | None = None
    session_id: str | None = None
    raw_event: dict[str, Any] = Field(default_factory=dict)