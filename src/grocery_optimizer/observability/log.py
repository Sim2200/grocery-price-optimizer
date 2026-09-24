"""Structured (JSON) logging with request IDs, using only the standard library.

Every log line is one JSON object, e.g.

    {"ts": "2026-09-24T18:00:00.123Z", "level": "INFO", "logger": "grocery_optimizer.api",
     "message": "request", "request_id": "3f2a...", "method": "GET", "path": "/api/prices",
     "status": 200, "duration_ms": 12.4}

so a log system (CloudWatch, Loki, Elasticsearch...) can filter on any field.
The request ID lives in a ContextVar: set once per request by the middleware,
then every log call made while handling that request picks it up automatically.

Environment: LOG_LEVEL (default INFO), LOG_FORMAT=json|text (default json).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from contextvars import ContextVar

from opentelemetry import trace

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else was passed with `extra={...}`.
# (uvicorn adds "color_message", a copy of the message with terminal colours.)
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "color_message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if (request_id := request_id_var.get()) is not None:
            entry["request_id"] = request_id
        span = trace.get_current_span().get_span_context()
        if span.is_valid:  # lets you jump from a log line to its trace
            entry["trace_id"] = format(span.trace_id, "032x")
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class _OurHandler(logging.StreamHandler):
    """Marker class so configure_logging can replace its own handler without touching others."""


def configure_logging(level: str | None = None, fmt: str | None = None) -> None:
    """Send all logs (ours and uvicorn's) to stderr in one format. Safe to call repeatedly."""
    level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    fmt = fmt or os.environ.get("LOG_FORMAT", "json")
    handler = _OurHandler()
    handler.setFormatter(JsonFormatter() if fmt == "json" else
                         logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not isinstance(h, _OurHandler)] + [handler]
    root.setLevel(level)
    # uvicorn installs its own plain-text handlers; route its logs through ours instead.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
