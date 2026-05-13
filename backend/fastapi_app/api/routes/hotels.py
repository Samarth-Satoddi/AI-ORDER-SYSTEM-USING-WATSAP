from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi_app.db.session import get_db
from fastapi_app.models.hotel import Hotel
from fastapi_app.schemas.common import HotelOut

router = APIRouter()


@router.get("", response_model=list[HotelOut])
def list_hotels(db: Session = Depends(get_db)) -> list[Hotel]:
    return list(db.scalars(select(Hotel).where(Hotel.is_active.is_(True)).order_by(Hotel.name.asc())).all())

