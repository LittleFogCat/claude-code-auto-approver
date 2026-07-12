"""Async Anthropic client with retry + timeout.

We isolate SDK calls so tests can mock them easily (via respx at the HTTP layer
or by monkeypatching the AsyncAnthropic class).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from anthropic import AsyncAnthropic
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger("classifier.claude")


class ClaudeClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5",
        timeout_s: float = 8.0,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._client: AsyncAnthropic | None = None

    @property
    def client(self) -> AsyncAnthropic:
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("ANTHROPIC_API_KEY not set")
            self._client = AsyncAnthropic(
                api_key=self.api_key,
                timeout=self.timeout_s,
                max_retries=0,  # we handle retries via tenacity
            )
        return self._client

    async def messages_create(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 256,
        system: str | None = None,
    ) -> Any:
        """Call ``messages.create`` with retries on transient errors."""
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=0.4, min=0.4, max=2),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                kwargs: dict[str, Any] = dict(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=messages,
                    tools=tools,
                )
                if system:
                    kwargs["system"] = system
                return await self.client.messages.create(**kwargs)
        raise RuntimeError("unreachable: tenacity exhausted without returning")