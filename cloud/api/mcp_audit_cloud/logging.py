"""structlog, JSON, with a redaction processor that runs on every event (§4).

The redactor is not optional and not per-call: a log line is written by whoever is in a
hurry, and "remember not to log the token" is not a control.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

SENSITIVE_KEY = re.compile(r"(?i)authorization|cookie|token|secret|password|api[-_]?key|credential")
SENSITIVE_VALUE = re.compile(r"(mcpa_[A-Za-z0-9_\-]{8,}|sk-ant-[A-Za-z0-9_\-]{8,}|whsec_[A-Za-z0-9+/=]{8,})")
MASK = "[redacted]"


def redact(_logger: Any, _name: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    return {k: (MASK if SENSITIVE_KEY.search(k) else _scrub(v)) for k, v in event.items()}


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return SENSITIVE_VALUE.sub(MASK, value)
    if isinstance(value, dict):
        return {k: (MASK if SENSITIVE_KEY.search(str(k)) else _scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
            if json_output
            else structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        cache_logger_on_first_use=True,
    )
