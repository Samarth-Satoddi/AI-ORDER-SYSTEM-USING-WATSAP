from typing import Literal

from pydantic import BaseModel, Field


IntentType = Literal["GREETING", "ORDER", "MENU_QUERY", "BAD_MESSAGE", "GOODBYE", "UNKNOWN"]


class ExtractedItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    quantity: int | None = Field(default=None, ge=1, le=99)


class OrderExtraction(BaseModel):
    intent: IntentType = "ORDER"
    items: list[ExtractedItem] = Field(default_factory=list)
    reply: str | None = None
