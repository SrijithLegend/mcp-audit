"""Renderings of one `Report`. Four formats, one source of truth.

Everything here treats server-supplied text as data: no markdown is generated from
it, no HTML, and anything a model wrote is truncated and masked by
`features.redact` long before it reaches these functions.
"""

from .json import to_json
from .markdown import to_markdown
from .sarif import to_sarif
from .terminal import render

__all__ = ["render", "to_json", "to_markdown", "to_sarif"]
