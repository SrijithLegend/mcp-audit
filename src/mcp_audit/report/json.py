"""The machine-readable report. Versioned, because other people's CI parses it."""

from __future__ import annotations

import json as _json

from ..models import Report


def to_json(report: Report, indent: int | None = 2) -> str:
    return _json.dumps(report.model_dump(mode="json"), indent=indent, ensure_ascii=False)
