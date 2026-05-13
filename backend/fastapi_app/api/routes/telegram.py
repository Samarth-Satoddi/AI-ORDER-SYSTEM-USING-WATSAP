from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from fastapi_app.core.config import get_settings
from fastapi_app.db.session import get_db
from fastapi_app.services.telegram_service import telegram_bot

router = APIRouter()


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None,
        alias="X-Telegram-Bot-Api-Secret-Token",
    ),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    settings = get_settings()
    if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram secret token")

    update = await request.json()
    return await telegram_bot.handle_update(db, update)

