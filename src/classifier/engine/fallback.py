"""Claude fallback adapter.

Takes a ``PipelineContext``, calls Claude with the classify tool, and maps the
tool_use response back to a ``Decision``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from classifier.claude.classify_tool import CLASSIFY_TOOL
from classifier.claude.client import ClaudeClient
from classifier.claude.prompt import SYSTEM_PROMPT, USER_TEMPLATE
from classifier.schemas import Decision, PipelineContext

logger = logging.getLogger("classifier.engine.fallback")

_CONTENT_TRUNCATE = 1000


def _build_user_message(ctx: PipelineContext) -> str:
    content = ""
    if ctx.raw_event.get("tool_input", {}).get("content"):
        content = str(ctx.raw_event["tool_input"]["content"])[:_CONTENT_TRUNCATE]
    elif ctx.raw_event.get("tool_input", {}).get("new_string"):
        content = str(ctx.raw_event["tool_input"]["new_string"])[:_CONTENT_TRUNCATE]

    return USER_TEMPLATE.format(
        tool_name=ctx.tool_name,
        cwd=ctx.cwd or "(unknown)",
        file_path=ctx.file_path or "(none)",
        command=ctx.command or "(none)",
        content=content or "(none)",
        content_chars=_CONTENT_TRUNCATE,
    )


def _decision_from_tool_input(inp: dict[str, Any]) -> Decision | None:
    decision = inp.get("decision")
    if decision not in {"allow", "deny", "ask"}:
        logger.warning("claude returned unexpected decision value: %r", decision)
        return None

    legacy = "approve" if decision == "allow" else "block"
    return Decision(
        decision=legacy,
        hookSpecificOutput={
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
        },
        matched_rule=None,
        reason=inp.get("reason") or "claude fallback",
    )


class ClaudeFallback:
    def __init__(self, client: ClaudeClient | None = None) -> None:
        self.client = client or ClaudeClient()

    async def classify(self, ctx: PipelineContext) -> Decision | None:
        """Return a Decision, or None if Claude gave an unusable response."""
        if not self.client.api_key:
            logger.debug("no anthropic api key; skipping fallback")
            return None

        user_msg = _build_user_message(ctx)

        try:
            resp = await self.client.messages_create(
                messages=[{"role": "user", "content": user_msg}],
                tools=[CLASSIFY_TOOL],
                system=SYSTEM_PROMPT,
                max_tokens=256,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("claude call failed: %s", e)
            raise

        # Look for a tool_use block
        for block in getattr(resp, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "classify_tool_call":
                raw = getattr(block, "input", None)
                inp = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                return _decision_from_tool_input(inp)

        logger.warning("claude response had no classify tool_use; falling back")
        return None