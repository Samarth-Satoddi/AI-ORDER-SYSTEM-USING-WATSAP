from pydantic import BaseModel, Field
from fastapi import APIRouter

from fastapi_app.ai.extractor import extractor
from fastapi_app.schemas.ai import OrderExtraction

router = APIRouter()


class ExtractionRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


@router.post("/extract", response_model=OrderExtraction)
async def extract_order_items(payload: ExtractionRequest) -> OrderExtraction:
    return await extractor.extract(payload.message)

