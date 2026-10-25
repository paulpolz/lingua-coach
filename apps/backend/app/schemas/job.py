from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class JobResponse(BaseModel):
    id: str
    status: Literal["pending", "running", "done", "failed"]
    type: str
    result_ref: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
