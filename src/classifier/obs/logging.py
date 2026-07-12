"""JSON-line audit logging configuration.

This module deliberately uses only the Python standard library so it works in
any environment, even if ``structlog`` is not installed. The output format is a
newline-delimited JSON document per log record (``logs/decisions.jsonl``),
which downstream tools can ``jq`` over.

Wire-up:

    from classifier.obs.logging import configure_logging
    configure_logging(settings.logging)
"""

from __future__ import annotations

import json
import logging
import logging.config
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from classifier.settings import LoggingConfig


class _JsonFormatter(logging.Formatter):
    """Render every record as a single JSON line.

    We pull any ``extra={...}`` keys and merge them into the top-level object
    so callers can do ``logger.info("decision", extra={"tool": "Bash"})`` and
    have ``tool`` appear as a top-level field.
    """

    # Standard LogRecord attributes we do NOT want to copy from ``extra``.
    _RESERVED = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge any custom extras
        for k, v in record.__dict__.items():
            if k in self._RESERVED or k.startswith("_"):
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except TypeError:
                payload[k] = repr(v)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(cfg: LoggingConfig) -> None:
    """Configure stdlib logging to emit JSON lines to both stdout and a file.

    * stdout  -> JSON line (machine-friendly, easy to ``tee``).
    * file    -> same JSON line, append mode. Parent dir is created if missing.
    """
    level = getattr(logging, cfg.level.upper(), logging.INFO)

    log_path = Path(cfg.file) if cfg.file else None
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = _JsonFormatter()

    handlers: dict[str, dict[str, Any]] = {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "json",
            "level": level,
        },
    }
    if log_path:
        handlers["audit"] = {
            "class": "logging.FileHandler",
            "filename": str(log_path),
            "encoding": "utf-8",
            "mode": "a",
            "formatter": "json",
            "level": level,
        }

    handler_list = ["stdout"] + (["audit"] if log_path else [])

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": "classifier.obs.logging._JsonFormatter"}},
            "handlers": handlers,
            "loggers": {
                "classifier": {
                    "handlers": handler_list,
                    "level": level,
                    "propagate": False,
                },
                "uvicorn": {"handlers": ["stdout"], "level": level, "propagate": False},
                "uvicorn.error": {"handlers": ["stdout"], "level": level, "propagate": False},
            },
            "root": {"handlers": ["stdout"], "level": level},
        }
    )