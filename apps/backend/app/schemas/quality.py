"""Request shapes for `POST /api/v1/quality/events`.

Locked contract for the frontend: thumbs `{thumb: 1|-1}` and CSAT `{csat: 1..5}`.
Judge kinds (`judge`, `judge_candidate`) are server-written only.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, model_validator

QualityKind = Literal["thumbs", "lesson_csat"]
QualitySurface = Literal["onboarding", "lesson", "lesson_generation"]


class QualityEventCreate(BaseModel):
    kind: QualityKind
    surface: QualitySurface
    session_id: UUID | None = None
    message_id: UUID | None = None
    lesson_id: UUID | None = None
    value: dict[str, Any]

    @model_validator(mode="after")
    def validate_value_and_ids(self) -> QualityEventCreate:
        if self.kind == "thumbs":
            thumb = self.value.get("thumb")
            if thumb not in (1, -1):
                raise ValueError("value.thumb must be 1 or -1")
            if self.session_id is None and self.message_id is None and self.lesson_id is None:
                raise ValueError("session_id, message_id, or lesson_id is required for thumbs")
        elif self.kind == "lesson_csat":
            csat = self.value.get("csat")
            if not isinstance(csat, int) or isinstance(csat, bool) or not 1 <= csat <= 5:
                raise ValueError("value.csat must be an integer 1–5")
            if self.lesson_id is None:
                raise ValueError("lesson_id is required for lesson_csat")
        return self
