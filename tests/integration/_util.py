"""Small helpers shared by the integration test files."""

from __future__ import annotations

import json
from typing import Any


def tool_text(result: Any) -> str:
    """Extract a tool call's textual payload across FastMCP result shapes.

    Tools in this server return strings (JSON or TOON-encoded), exposed either as
    ``result.data`` or as text content blocks.
    """
    data = getattr(result, "data", None)
    if isinstance(data, str):
        return data
    content = getattr(result, "content", None) or []
    return "".join(getattr(block, "text", "") for block in content)


def resource_json(contents: Any) -> Any:
    """Parse a JSON resource read (list of contents) into a Python object."""
    return json.loads(contents[0].text)


def resource_text(contents: Any) -> str:
    """Return the raw text of a resource read (list of contents)."""
    return str(contents[0].text)
