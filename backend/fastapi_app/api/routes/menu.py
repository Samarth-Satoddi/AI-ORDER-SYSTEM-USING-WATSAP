from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from fastapi_app.ai.extractor import extractor
from fastapi_app.db.session import get_db
from fastapi_app.schemas.common import MenuSearchResult
from fastapi_app.services.menu_matcher import match_extracted_items, search_menu

router = APIRouter()


@router.get("/search", response_model=list[MenuSearchResult])
def search_menu_items(
    hotel_id: int = Query(..., gt=0),
    q: str = Query(..., min_length=1, max_length=200),
    db: Session = Depends(get_db),
) -> list[MenuSearchResult]:
    return search_menu(db, hotel_id=hotel_id, query=q)


@router.get("/match-message", response_model=list[MenuSearchResult])
async def match_message_to_menu(
    hotel_id: int = Query(..., gt=0),
    message: str = Query(..., min_length=1, max_length=2000),
    db: Session = Depends(get_db),
) -> list[MenuSearchResult]:
    extraction = await extractor.extract(message)
    return match_extracted_items(db, hotel_id=hotel_id, extracted_items=extraction.items)

