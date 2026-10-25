"""Hidden ```json:<name>``` fences the model appends to chat replies."""

from __future__ import annotations

import json
import re

_BLOCK = re.compile(r"```json:(\w+)\s*\n(.*?)```", re.DOTALL)


def extract(text: str, name: str) -> dict | None:
    """Last parseable JSON object in a `json:<name>` fence, else None."""
    for kind, raw in reversed(_BLOCK.findall(text)):
        if kind != name:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def strip_blocks(text: str) -> str:
    return _BLOCK.sub("", text).strip()
