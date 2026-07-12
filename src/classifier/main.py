"""FastAPI entry point."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI

from classifier.api.classify import router as classify_router
from classifier.api.health import router as health_router
from classifier.claude.client import ClaudeClient
from classifier.engine.factory import build_rules
from classifier.engine.fallback import ClaudeFallback
from classifier.engine.pipeline import RulePipeline
from classifier.obs.logging import configure_logging
from classifier.settings import Settings


def _build_pipeline(settings: Settings) -> RulePipeline:
    rules = build_rules(settings.rules.rules)
    fallback = None
    if settings.behavior.enable_claude_fallback:
        try:
            client = ClaudeClient(
                model=settings.behavior.claude_model,
                timeout_s=float(settings.behavior.claude_timeout_s),
            )
            fallback = ClaudeFallback(client=client)
        except Exception as e:  # noqa: BLE001
            logging.getLogger("classifier").warning(
                "could not build claude fallback: %s", e,
            )
    return RulePipeline(rules=rules, behavior=settings.behavior, fallback=fallback)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.logging)
    logging.getLogger("classifier").info(
        "classifier starting",
        extra={
            "host": settings.service.host,
            "port": settings.service.port,
            "rules": len(settings.rules.rules),
            "claude_fallback": settings.behavior.enable_claude_fallback,
        },
    )
    yield
    logging.getLogger("classifier").info("classifier stopping")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    app = FastAPI(
        title="Claude Code Classifier",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.pipeline = _build_pipeline(settings)
    app.include_router(health_router)
    app.include_router(classify_router)
    return app


# Module-level app for `uvicorn classifier.main:app`
app = create_app()


def run() -> None:
    """Console entry point."""
    s = Settings.load()
    log_path = s.logging.file
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    uvicorn.run(
        "classifier.main:app",
        host=s.service.host,
        port=s.service.port,
        log_level=s.logging.level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    run()