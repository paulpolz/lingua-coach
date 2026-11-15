"""Loads skills/*.md. Pedagogy stays in those files; tools return them to the model."""

from __future__ import annotations

import functools
from pathlib import Path

from app.config import settings


@functools.cache
def load_skill(name: str) -> str:
    return (Path(settings.skills_dir) / f"{name}.md").read_text(encoding="utf-8")
