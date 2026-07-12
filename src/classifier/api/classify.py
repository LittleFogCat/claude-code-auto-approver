"""POST /classify - the main hook endpoint.

Accepts a Claude Code PreToolUse event, runs the pipeline, returns a Decision.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from classifier.engine.pipeline import RulePipeline
from classifier.schemas import Decision, PreToolUseEvent

logger = logging.getLogger("classifier.api")

router = APIRouter()


def _pipeline(request: Request) -> RulePipeline:
    # built once per app, stored in app.state by build_pipeline()
    return request.app.state.pipeline


@router.post("/classify", response_model=Decision)
async def classify(
    payload: dict[str, Any],
    request: Request,
    x_bridge_token: str | None = Header(default=None),
) -> Decision:
    started = time.perf_counter()
    request_id = uuid.uuid4().hex[:12]
    settings = request.app.state.settings

    # Token auth (if configured)
    if settings.auth.bridge_token:
        if x_bridge_token != settings.auth.bridge_token:
            raise HTTPException(status_code=401, detail="invalid bridge token")

    # Validate the event (lenient: extra fields allowed)
    try:
        event = PreToolUseEvent.model_validate(payload)
    except Exception as e:
        # Bad input from the hook - fail-open so we don't block the user
        logger.warning(
            "invalid event payload; failing open",
            extra={"request_id": request_id, "err": str(e)},
        )
        return Decision(
            decision="approve",
            hookSpecificOutput={
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            },
            reason=f"invalid event payload: {e}",
            request_id=request_id,
        )

    pipeline = _pipeline(request)
    decision = await pipeline.run(event)

    took_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "decision",
        extra={
            "request_id": request_id,
            "tool": event.tool_name,
            "decision": decision.decision,
            "permission_decision": decision.hookSpecificOutput.get("permissionDecision"),
            "matched_rule": decision.matched_rule.id if decision.matched_rule else None,
            "took_ms": took_ms,
            # Tool input (full Claude Code payload, e.g. Bash command, Edit file_path,
            # new_string/old_string). Captured so observer_gui.py can show the user
            # exactly what was requested, not just the decision. Pydantic model_dump
            # with extra=allow preserves any tool-specific fields Claude adds in
            # the future (description, timeout, run_in_background, etc.).
            "tool_input": event.tool_input.model_dump(exclude_none=True),
        }
    )
    return decision