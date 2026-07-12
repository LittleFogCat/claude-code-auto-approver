"""Rule abstractions.

A rule takes a ``PipelineContext`` and returns either:
- ``None`` (no match)
- a ``RuleHit`` describing what matched and how severe it is.

Rules are evaluated concurrently via ``asyncio.gather`` in ``RulePipeline``.
"""

from __future__ import annotations

import abc
import re
from pathlib import Path
from typing import Any, Literal

from classifier.schemas import DecisionKind, PipelineContext, RuleHit

Severity = Literal["critical", "high", "medium", "low"]


class Rule(abc.ABC):
    """Base class for all rules."""

    spec_id: str
    type: str
    priority: int
    severity: Severity
    enabled: bool

    def __init__(
        self,
        spec_id: str,
        type: str,
        priority: int,
        severity: Severity,
        enabled: bool = True,
    ) -> None:
        self.spec_id = spec_id
        self.type = type
        self.priority = priority
        self.severity = severity
        self.enabled = enabled

    @abc.abstractmethod
    async def evaluate(self, ctx: PipelineContext) -> RuleHit | None:
        """Return a RuleHit if this rule matches, else None."""


# ---- Helpers -----------------------------------------------------------------


def _expand_user(path: str) -> str:
    """Cross-platform home expansion (~ -> home). Windows-friendly."""
    return str(Path(path).expanduser())


def _normalize_separators(path: str) -> str:
    """Normalize path separators for matching.

    We accept either backslashes or forward slashes -- both work on Windows
    for most filesystem APIs and glob libraries.
    """
    return path.replace("\\", "/")


def _glob_to_regex(pat: str) -> re.Pattern[str]:
    """Convert a glob-ish pattern (``**``, ``*``, ``?``) to a regex.

    Supported wildcards:
    - ``**``   matches any number of path segments (including zero)
    - ``*``    matches any number of characters except ``/``
    - ``?``    matches a single character except ``/``
    - ``[abc]`` character class
    """
    i = 0
    out: list[str] = []
    while i < len(pat):
        c = pat[i]
        if c == "*":
            # Detect ``**`` (and ``**/`` / ``/**``)
            if i + 1 < len(pat) and pat[i + 1] == "*":
                # Greedy any-segments matcher: zero or more segments (including slashes)
                # We'll use ``.*`` for ``**`` not adjacent to ``/``,
                # and ``(?:.*/)?`` for ``**/`` and ``/**`` (and ``/**/``).
                # Easiest robust approach: emit ``[^/]*(?:/[^/]*)*`` for "zero+ segments".
                out.append(".*")
                i += 2
                # Eat a trailing ``/`` so ``**/`` doesn't also try to match a slash.
                if i < len(pat) and pat[i] == "/":
                    i += 1
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c in r".^$+()[]{}|\\":
            out.append("\\" + c)
            i += 1
        else:
            out.append(c)
            i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def glob_match(path: str, pattern: str) -> bool:
    """Tiny fnmatch-style glob match that handles ``**``.

    ``**`` matches any number of directories (including zero).
    Paths are compared case-insensitively.
    """
    p = _normalize_separators(_expand_user(path))
    pat = _normalize_separators(_expand_user(pattern))
    return _glob_to_regex(pat).match(p) is not None


def compile_pattern(pattern: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(pattern, flags)


def pattern_hits(text: str, compiled: re.Pattern[str]) -> bool:
    if text is None:
        return False
    return compiled.search(text) is not None