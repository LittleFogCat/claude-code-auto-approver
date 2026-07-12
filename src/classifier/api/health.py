"""GET /health - lightweight liveness probe used by hook_bridge auto-start."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    s = request.app.state.settings
    return {
        "status": "ok",
        "rules": len(s.rules.rules),
        "claude_fallback": s.behavior.enable_claude_fallback,
    }