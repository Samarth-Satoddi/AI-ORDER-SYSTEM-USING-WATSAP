import argparse
import asyncio
import logging
from typing import Any

import httpx

from fastapi_app.core.config import get_settings
from fastapi_app.db.session import SessionLocal
from fastapi_app.services.telegram_service import telegram_bot

logger = logging.getLogger(__name__)


class TelegramPollingConnectionError(RuntimeError):
    pass


class TelegramConflictError(RuntimeError):
    """Raised when Telegram returns 409 Conflict (another polling instance is running)."""
    pass


async def _post_telegram(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: dict[str, Any],
    timeout: float | httpx.Timeout | None = None,
    attempts: int = 3,
) -> httpx.Response:
    last_error: httpx.RequestError | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = await client.post(url, json=json, timeout=timeout)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                raise TelegramConflictError(
                    "Telegram returned 409 Conflict. Another polling instance or webhook "
                    "is already running for this bot token. Stop the other instance first."
                ) from exc
            raise
        except httpx.RequestError as exc:
            last_error = exc
            logger.warning("Telegram request attempt %s/%s failed: %s", attempt, attempts, exc)
            if attempt < attempts:
                await asyncio.sleep(attempt)

    raise TelegramPollingConnectionError(
        "Could not connect to Telegram Bot API after multiple attempts. "
        "Check your internet/VPN/proxy/firewall connection to https://api.telegram.org, "
        "or increase TELEGRAM_HTTP_TIMEOUT_SECONDS for slow networks."
    ) from last_error


async def delete_webhook(client: httpx.AsyncClient, api_base: str, drop_pending_updates: bool) -> None:
    await _post_telegram(
        client,
        f"{api_base}/deleteWebhook",
        json={"drop_pending_updates": drop_pending_updates},
    )


async def fetch_updates(client: httpx.AsyncClient, api_base: str, offset: int | None, timeout: int) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {
        "timeout": timeout,
        "allowed_updates": ["message", "callback_query"],
    }
    if offset is not None:
        payload["offset"] = offset

    response = await _post_telegram(client, f"{api_base}/getUpdates", json=payload, timeout=timeout + 10)
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram getUpdates failed: {data}")
    return data.get("result", [])


async def poll_forever(timeout: int = 30, drop_pending_updates: bool = True) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    offset: int | None = None
    consecutive_failures = 0
    max_backoff = 60  # seconds
    client_timeout = httpx.Timeout(settings.telegram_http_timeout_seconds)
    async with httpx.AsyncClient(timeout=client_timeout) as client:
        await delete_webhook(client, settings.telegram_api_base, drop_pending_updates=drop_pending_updates)
        logger.info("Telegram polling started. Press Ctrl+C to stop.")

        while True:
            try:
                updates = await fetch_updates(client, settings.telegram_api_base, offset, timeout)
                consecutive_failures = 0  # reset on success
            except TelegramConflictError:
                raise  # 409 is fatal — another instance is running
            except (TelegramPollingConnectionError, httpx.RequestError, OSError) as exc:
                consecutive_failures += 1
                backoff = min(2 ** consecutive_failures, max_backoff)
                logger.warning(
                    "Network error (attempt %s), retrying in %ss: %s",
                    consecutive_failures, backoff, exc,
                )
                await asyncio.sleep(backoff)
                continue

            for update in updates:
                offset = int(update["update_id"]) + 1
                db = SessionLocal()
                try:
                    result = await telegram_bot.handle_update(db, update)
                    logger.info("Handled update %s: %s", update["update_id"], result["status"])
                except Exception:
                    logger.exception("Failed to handle update %s", update.get("update_id"))
                finally:
                    db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Telegram bot locally with getUpdates polling.")
    parser.add_argument("--timeout", type=int, default=30, help="Telegram long-poll timeout in seconds.")
    parser.add_argument(
        "--keep-pending",
        action="store_true",
        help="Process old pending Telegram updates instead of dropping them on startup.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        asyncio.run(poll_forever(timeout=args.timeout, drop_pending_updates=not args.keep_pending))
    except TelegramConflictError as exc:
        logger.error("%s", exc)
        logger.error("Fix: Close other terminal windows running telegram_polling, then try again.")
    except TelegramPollingConnectionError as exc:
        logger.error("%s", exc)
    except KeyboardInterrupt:
        print("Telegram polling stopped.")


if __name__ == "__main__":
    main()
