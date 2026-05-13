from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class HotelOut(BaseModel):
    id: int
    name: str
    slug: str
    telegram_label: str | None = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class MenuItemOut(BaseModel):
    id: int
    hotel_id: int
    name: str
    category: str | None = None
    description: str | None = None
    price: Decimal
    is_available: bool

    model_config = ConfigDict(from_attributes=True)


class MenuSearchResult(BaseModel):
    item: MenuItemOut
    score: float
    extracted_name: str

