import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi_app.models.menu_item import MenuItem
from fastapi_app.schemas.ai import ExtractedItem
from fastapi_app.schemas.common import MenuSearchResult

MINIMUM_MENU_MATCH_SCORE = 0.35


def search_menu(
    db: Session,
    hotel_id: int,
    query: str,
    limit: int = 5,
    min_score: float = MINIMUM_MENU_MATCH_SCORE,
) -> list[MenuSearchResult]:
    items = db.scalars(
        select(MenuItem)
        .where(MenuItem.hotel_id == hotel_id, MenuItem.is_available.is_(True))
        .order_by(MenuItem.name.asc())
    ).all()
    return _rank_items(items, query, limit, min_score=min_score)


def match_extracted_items(
    db: Session,
    hotel_id: int,
    extracted_items: list[ExtractedItem],
    limit_per_item: int = 3,
) -> list[MenuSearchResult]:
    if not extracted_items:
        return []

    items = db.scalars(
        select(MenuItem)
        .where(MenuItem.hotel_id == hotel_id, MenuItem.is_available.is_(True))
        .order_by(MenuItem.name.asc())
    ).all()

    matches: list[MenuSearchResult] = []
    seen: set[tuple[int, str]] = set()
    for extracted in extracted_items:
        for match in _rank_items(items, extracted.name, limit_per_item, min_score=MINIMUM_MENU_MATCH_SCORE):
            key = (match.item.id, extracted.name.lower())
            if key not in seen:
                seen.add(key)
                matches.append(match)
    return matches


def _rank_items(
    items: list[MenuItem],
    query: str,
    limit: int,
    min_score: float = 0,
) -> list[MenuSearchResult]:
    normalized_query = _normalize(query)
    ranked = []

    for item in items:
        normalized_name = _normalize(item.name)
        if not normalized_query or not normalized_name:
            continue

        similarity = SequenceMatcher(None, normalized_query, normalized_name).ratio()
        token_overlap = _token_overlap(normalized_query, normalized_name)
        substring_boost = 0.18 if normalized_query in normalized_name or normalized_name in normalized_query else 0
        score = min(1.0, (similarity * 0.62) + (token_overlap * 0.38) + substring_boost)
        if score >= min_score:
            ranked.append(MenuSearchResult(item=item, score=round(score, 3), extracted_name=query))

    ranked.sort(key=lambda result: result.score, reverse=True)
    return ranked[:limit]


def _normalize(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    return " ".join(value.split())


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
