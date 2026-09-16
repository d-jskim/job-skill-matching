from typing import Any

from pydantic import BaseModel


class GraphResponse(BaseModel):
    curriculum_code: str
    curriculum_name: str
    days: int
    elements: list[dict[str, Any]]
