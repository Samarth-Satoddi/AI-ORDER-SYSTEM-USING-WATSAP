import logging
import re
import asyncio
from datetime import date, datetime
from decimal import Decimal
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi_app.ai.extractor import extractor
from fastapi_app.core.config import get_settings
from fastapi_app.models.customer import Customer
from fastapi_app.models.hotel import Hotel
from fastapi_app.models.menu_item import MenuItem
from fastapi_app.models.user_session import UserSession
from fastapi_app.schemas.order import OrderCreate, OrderItemCreate
from fastapi_app.services.menu_matcher import search_menu
from fastapi_app.services.order_service import create_order, serialize_order
from fastapi_app.services.voice_service import download_telegram_voice, transcribe_voice
from fastapi_app.websocket.manager import manager
from fastapi_app.services import new_features as nf

logger = logging.getLogger(__name__)

STATE_START = "START"
STATE_WAITING_ITEM = "WAITING_ITEM"
STATE_WAITING_SELECTION = "WAITING_SELECTION"
STATE_ENTERING_QUANTITY = "ENTERING_QUANTITY"
STATE_CONFIRMING = "CONFIRMING"
STATE_MODIFY_UPDATE_ORDER = "MODIFY_UPDATE_ORDER"
STATE_MODIFY_QUANTITY_ITEM = "MODIFY_QUANTITY_ITEM"
STATE_MODIFY_QUANTITY_VALUE = "MODIFY_QUANTITY_VALUE"
STATE_MODIFY_CANCEL_ITEM = "MODIFY_CANCEL_ITEM"
STATE_MODIFY_ADD_ITEMS = "MODIFY_ADD_ITEMS"
STATE_BROWSING_MENU = "BROWSING_MENU"
STATE_SELECTING_QUANTITY = "SELECTING_QUANTITY"
SEP = "------------"
DEFAULT_PREP_TIME = "25-30 mins"
IST = ZoneInfo("Asia/Kolkata")


@dataclass
class PlannedMenuItem:
    requested_name: str
    quantity: int | None
    menu_item: MenuItem


@dataclass
class HotelSplitPlan:
    hotel: Hotel
    items: list[PlannedMenuItem]


class TelegramClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        if not self.settings.telegram_bot_token:
            logger.info("Telegram token missing; would send to %s: %s", chat_id, text)
            return

        payload: dict[str, Any] = {"chat_id": chat_id, "text": _plain_english_text(text)}
        if reply_markup:
            payload["reply_markup"] = reply_markup

        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.post(f"{self.settings.telegram_api_base}/sendMessage", json=payload)
                    response.raise_for_status()
                return
            except httpx.HTTPStatusError as exc:
                logger.warning("Telegram sendMessage failed: %s", exc.response.text)
                return
            except httpx.RequestError as exc:
                logger.warning("Telegram sendMessage attempt %s failed: %s", attempt, exc)
                if attempt == 3:
                    return
                await asyncio.sleep(attempt)

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        if not self.settings.telegram_bot_token:
            return

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": _plain_english_text(text)
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.post(f"{self.settings.telegram_api_base}/editMessageText", json=payload)
                    response.raise_for_status()
                return
            except httpx.HTTPStatusError as exc:
                logger.warning("Telegram editMessageText failed: %s", exc.response.text)
                return
            except httpx.RequestError as exc:
                logger.warning("Telegram editMessageText attempt %s failed: %s", attempt, exc)
                if attempt == 3:
                    return
                await asyncio.sleep(attempt)

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        if not self.settings.telegram_bot_token:
            return
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                response = await client.post(f"{self.settings.telegram_api_base}/answerCallbackQuery", json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning("Could not acknowledge Telegram callback: %s", exc.response.text)
            except httpx.RequestError as exc:
                logger.warning("Could not acknowledge Telegram callback: %s", exc)


class TelegramBotService:
    def __init__(self) -> None:
        self.client = TelegramClient()

    async def handle_update(self, db: Session, update: dict[str, Any]) -> dict[str, str]:
        if "callback_query" in update:
            await self._handle_callback(db, update["callback_query"])
            return {"status": "callback_handled"}

        if "message" in update:
            await self._handle_message(db, update["message"])
            return {"status": "message_handled"}

        return {"status": "ignored"}

    async def _handle_message(self, db: Session, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        telegram_user = message.get("from") or {}
        chat_id = int(chat["id"])
        telegram_user_id = int(telegram_user["id"])

        customer = self._upsert_customer(db, telegram_user, chat_id)
        session = self._get_or_create_session(db, telegram_user_id)

        # --- Task 2: Daily session reset ---
        is_new_day = nf.check_and_reset_daily_session(db, session)

        # --- Task 1: Voice message handling ---
        voice = message.get("voice")
        if voice:
            await nf.handle_voice_message(self, db, chat_id, customer, session, voice, is_new_day)
            return

        text = (message.get("text") or "").strip()
        if not text:
            return

        # First message of a new day (or session start): show greeting with hotel list
        if is_new_day:
            await nf.send_daily_greeting(self, db, chat_id, session)
            # If it's purely a greeting word, stop here — hotel list was already shown
            if _normalize_text(text) in {"hi", "hello", "hii", "hey", "good morning", "good afternoon",
                                         "good evening", "namaste", "start", "helo", "hai"}:
                return
            # Otherwise fall through to process the actual content of the message

        if text.startswith("/start") or text.lower() in {"start", "restart", "change hotel"}:
            await self._send_hotel_picker(db, chat_id, session)
            return

        normalized_command = _normalize_text(text)

        # Task 2: "Same as yesterday" / repeat order
        if normalized_command in {"same as yesterday", "repeat last order", "repeat order", "same order", "reorder"}:
            await nf.handle_same_as_yesterday(self, db, chat_id, customer, session)
            return

        # Task 3: Hotel list requests
        if nf.is_hotel_list_request(normalized_command):
            await self._send_hotel_picker(db, chat_id, session)
            return

        # Task 3: Cart commands
        if normalized_command in {"view cart", "show cart", "my cart", "cart"}:
            await nf.send_cart_summary(self, db, chat_id, session)
            return
        if normalized_command in {"checkout", "check out"}:
            if _editable_order_items(session):
                await self._send_order_summary(db, chat_id, session)
            else:
                await self.client.send_message(chat_id, "Your cart is empty. Send a food item to get started.")
            return

        if normalized_command in {"place order", "confirm", "yes", "ok"} and session.state == STATE_CONFIRMING:
            await self._confirm_order(db, chat_id, customer, session)
            return
        if session.state in {
            STATE_MODIFY_UPDATE_ORDER,
            STATE_MODIFY_QUANTITY_ITEM,
            STATE_MODIFY_QUANTITY_VALUE,
            STATE_MODIFY_CANCEL_ITEM,
            STATE_MODIFY_ADD_ITEMS,
        }:
            await self._handle_modify_message(db, chat_id, session, text)
            return
        if normalized_command in {"modify order", "change order", "cancel"}:
            await self._send_modify_options(db, chat_id, session)
            return
        if normalized_command in {"show better options", "better options"}:
            await self.client.send_message(
                chat_id,
                "SHOW BETTER OPTIONS\n\nSend the full order again with a hotel name, and I will search the best match.",
            )
            return

        selected_hotel = self._find_hotel_by_text(db, text)
        if selected_hotel and session.hotel_id != selected_hotel.id:
            await self._select_hotel(db, chat_id, session, selected_hotel)
            item_text = _strip_hotel_reference(text, selected_hotel)
            if _is_menu_request(text):
                await nf.send_smart_menu(self, db, chat_id, session, text)
                return
            if _contains_order_signal(item_text):
                await self._handle_order_text(db, chat_id, session, item_text)
            return

        if selected_hotel and session.hotel_id == selected_hotel.id:
            text = _strip_hotel_reference(text, selected_hotel)

        if _is_natural_modify_text(text) and _editable_order_items(session):
            await self._handle_natural_modify_text(db, chat_id, session, text)
            return

        if not session.hotel_id:
            await self._send_hotel_picker(db, chat_id, session)
            return

        # Task 3: Menu request for current hotel
        if _is_menu_request(text):
            await nf.send_smart_menu(self, db, chat_id, session, text)
            return

        # Task 3: Smart category/filter request
        if nf.is_category_filter_request(text):
            await nf.send_filtered_menu(self, db, chat_id, session, text)
            return

        if session.state == STATE_ENTERING_QUANTITY:
            await self._handle_quantity(db, chat_id, customer, session, text)
            return

        # Task 3: Typed quantity during menu browsing
        if session.state == STATE_SELECTING_QUANTITY:
            quantity = _parse_quantity(text)
            if quantity:
                await nf.handle_browsing_quantity(self, db, chat_id, session, quantity)
            else:
                await self.client.send_message(chat_id, "Enter a quantity between 1 and 99.")
            return

        await self._handle_order_text(db, chat_id, session, text)

    async def _handle_callback(self, db: Session, callback: dict[str, Any]) -> None:
        callback_id = callback["id"]
        data = callback.get("data") or ""
        message = callback.get("message") or {}
        message_id = message.get("message_id")
        chat_id = int(message["chat"]["id"])
        telegram_user = callback.get("from") or {}
        telegram_user_id = int(telegram_user["id"])

        customer = self._upsert_customer(db, telegram_user, chat_id)
        session = self._get_or_create_session(db, telegram_user_id)

        if not data.startswith("addcart:"):
            await self.client.answer_callback_query(callback_id)

        if data.startswith("hotel:"):
            hotel_id = int(data.split(":", 1)[1])
            hotel = db.get(Hotel, hotel_id)
            if not hotel or not hotel.is_active:
                await self.client.send_message(chat_id, "That hotel is not available right now.")
                return

            await self._select_hotel(db, chat_id, session, hotel)
            return

        if data.startswith("item:"):
            await self._handle_item_selection(db, chat_id, session, int(data.split(":", 1)[1]))
            return

        if data == "confirm":
            await self._confirm_order(db, chat_id, customer, session)
            return

        if data == "modify":
            await self._send_modify_options(db, chat_id, session)
            return

        if data.startswith("modify:"):
            await self._handle_modify_callback(db, chat_id, session, data)
            return

        if data == "cancel":
            session.state = STATE_WAITING_ITEM
            session.context = _preserve_date_context(session)
            db.commit()
            await self.client.send_message(chat_id, "Order cancelled.\n\nSend another item when you are ready.")
            return

        # Task 3: Menu item add-to-cart
        if data.startswith("addcart:"):
            menu_item_id = int(data.split(":", 1)[1])
            await nf.handle_addcart_callback(self, db, chat_id, session, menu_item_id, callback_id)
            return

        # Task 3: Quantity selection from menu browsing
        if data.startswith("qty:"):
            parts = data.split(":")
            menu_item_id = int(parts[1])
            quantity = int(parts[2])
            await nf.handle_qty_callback(self, db, chat_id, session, menu_item_id, quantity)
            return

        # Task 3: Cart action buttons
        if data.startswith("cart:"):
            await nf.handle_cart_callback(self, db, chat_id, session, data, message_id)
            return

        # Task 4: Batch multi-select actions
        if data.startswith("batch:"):
            await nf.handle_batch_checkout_callback(self, db, chat_id, session, data, message_id)
            return

        await self.client.send_message(chat_id, "I could not understand that selection.\n\nPlease try /start.")

    async def _send_hotel_picker(self, db: Session, chat_id: int, session: UserSession) -> None:
        hotels = db.scalars(select(Hotel).where(Hotel.is_active.is_(True)).order_by(Hotel.name.asc())).all()
        if not hotels:
            await self.client.send_message(chat_id, "No hotels are accepting orders right now.")
            return

        session.state = STATE_START
        session.hotel_id = None
        # Preserve last_active_date so we don't re-trigger new-day greeting next message
        session.context = _preserve_date_context(session)
        db.commit()

        keyboard = {
            "inline_keyboard": [
                [{"text": hotel.telegram_label or hotel.name, "callback_data": f"hotel:{hotel.id}"}]
                for hotel in hotels
            ]
        }
        lines = [
            "Choose a Hotel",
            "",
            "Select where you would like to order from:",
        ]
        await self.client.send_message(chat_id, "\n".join(lines), keyboard)

    async def _select_hotel(self, db: Session, chat_id: int, session: UserSession, hotel: Hotel) -> None:
        session.hotel_id = hotel.id
        session.state = STATE_WAITING_ITEM
        # Preserve last_active_date; clear cart/pending since switching hotel
        session.context = _preserve_date_context(session)
        db.commit()
        await self.client.send_message(
            chat_id,
            f"{hotel.name} selected\n\nSend your food items or say 'show menu'.\nExample: 2 biryani and 1 coke",
        )

    async def _handle_order_text(self, db: Session, chat_id: int, session: UserSession, text: str) -> None:
        extraction = await extractor.extract(text)

        if extraction.intent != "ORDER":
            if extraction.intent == "GREETING":
                await self.client.send_message(chat_id, _greeting_reply(session))
                return
            if extraction.intent == "MENU_QUERY":
                await self._send_menu(db, chat_id, session)
                return
            await self.client.send_message(
                chat_id,
                extraction.reply or "Please send a food item name.\n\nExample: 2 masala dosa",
            )
            return

        if not extraction.items:
            await self.client.send_message(chat_id, "Please send a food item name.\n\nExample: 2 masala dosa")
            return

        order_items: list[dict[str, Any]] = list(_editable_order_items(session)) if session.state == STATE_CONFIRMING else []
        pending_items: list[dict[str, Any]] = []
        unmatched_names: list[str] = []
        selected_planned_items: list[PlannedMenuItem] = []

        for extracted_item in extraction.items:
            matches = search_menu(db, session.hotel_id, extracted_item.name, limit=6)
            matches = [match for match in matches if match.item.is_available]
            if not matches:
                unmatched_names.append(extracted_item.name)
                continue

            auto_match = _find_auto_match(extracted_item.name, matches)
            quantity = extracted_item.quantity
            if auto_match:
                order_items.append(
                    {
                        "menu_item_id": auto_match.id,
                        "quantity": quantity,
                        "extracted_name": extracted_item.name,
                    }
                )
                selected_planned_items.append(
                    PlannedMenuItem(
                        requested_name=extracted_item.name,
                        quantity=quantity,
                        menu_item=auto_match,
                    )
                )
                continue

            pending_items.append(
                {
                    "name": extracted_item.name,
                    "quantity": quantity,
                    "candidate_ids": [match.item.id for match in matches],
                }
            )

        if unmatched_names:
            await self._send_cross_hotel_recommendation(
                db,
                chat_id,
                session,
                selected_planned_items,
                [item for item in extraction.items if item.name in unmatched_names],
            )
            return

        if not order_items and not pending_items:
            return

        session.context = {**(session.context or {}), "order_items": order_items, "pending_items": pending_items}
        db.commit()

        await self._advance_order_session(db, chat_id, session)

    async def _advance_order_session(self, db: Session, chat_id: int, session: UserSession) -> None:
        pending_items = session.context.get("pending_items", [])
        if pending_items:
            pending_item = pending_items[0]
            candidates = _load_menu_items(db, pending_item.get("candidate_ids", []))
            if not candidates:
                session.context = {**session.context, "pending_items": pending_items[1:]}
                db.commit()
                await self._advance_order_session(db, chat_id, session)
                return

            session.state = STATE_WAITING_SELECTION
            db.commit()

            keyboard = {
                "inline_keyboard": [
                    [{"text": f"{item.name} - INR {Decimal(item.price):.2f}", "callback_data": f"item:{item.id}"}]
                    for item in candidates
                    if item
                ]
            }
            await self.client.send_message(
                chat_id,
                f"Recommendation\n\nSelect the closest menu item for:\n- {pending_item['name']}",
                keyboard,
            )
            return

        order_items = session.context.get("order_items", [])
        missing_quantity_item = next((item for item in order_items if not item.get("quantity")), None)
        if missing_quantity_item:
            menu_item = db.get(MenuItem, missing_quantity_item.get("menu_item_id"))
            if not menu_item:
                session.context = {
                    **session.context,
                    "order_items": [item for item in order_items if item is not missing_quantity_item],
                }
                db.commit()
                await self._advance_order_session(db, chat_id, session)
                return

            session.state = STATE_ENTERING_QUANTITY
            session.context = {**session.context, "quantity_menu_item_id": menu_item.id}
            db.commit()
            await self.client.send_message(chat_id, f"Quantity for {menu_item.name}?")
            return

        await self._send_order_summary(db, chat_id, session)

    async def _send_order_summary(self, db: Session, chat_id: int, session: UserSession) -> None:
        order_items = session.context.get("order_items", [])
        summary_lines: list[str] = []
        total = Decimal("0")
        hotel = db.get(Hotel, session.hotel_id) if session.hotel_id else None

        for order_item in order_items:
            menu_item = db.get(MenuItem, order_item.get("menu_item_id"))
            quantity = order_item.get("quantity")
            if not menu_item or not quantity:
                continue

            line_total = Decimal(menu_item.price) * int(quantity)
            total += line_total
            summary_lines.append(f"- {quantity} {menu_item.name} - INR {line_total:.2f}")

        if not summary_lines:
            session.state = STATE_WAITING_ITEM
            session.context = _preserve_date_context(session)
            db.commit()
            await self.client.send_message(chat_id, "I could not build that order.\n\nPlease send the items again.")
            return

        session.state = STATE_CONFIRMING
        session.context = {
            **session.context,
            "recommended_plans": [
                {
                    "hotel_id": session.hotel_id,
                    "items": [
                        {"menu_item_id": item["menu_item_id"], "quantity": item["quantity"]}
                        for item in order_items
                        if item.get("menu_item_id") and item.get("quantity")
                    ],
                }
            ],
        }
        db.commit()

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "PLACE ORDER", "callback_data": "confirm"},
                    {"text": "MODIFY", "callback_data": "modify"},
                ]
            ]
        }
        summary = "\n".join(
            [
                "Order Summary",
                "",
                f"Hotel: {hotel.name if hotel else 'Selected hotel'}",
                *summary_lines,
                "",
                SEP,
                "",
                f"Total: INR {total:.2f}",
                f"Preparation Time: {DEFAULT_PREP_TIME}",
                "",
                "Reply with:",
                "PLACE ORDER",
                "MODIFY ORDER",
            ]
        )
        await self.client.send_message(chat_id, summary, keyboard)

    async def _send_modify_options(self, db: Session, chat_id: int, session: UserSession) -> None:
        if not _editable_order_items(session):
            await self.client.send_message(chat_id, "No active order to modify.\n\nSend your food items first.")
            return

        keyboard = {
            "inline_keyboard": [
                [{"text": "Update Order", "callback_data": "modify:update_order"}],
                [{"text": "Update Quantity", "callback_data": "modify:update_quantity"}],
                [{"text": "Cancel Item", "callback_data": "modify:cancel_item"}],
                [{"text": "Add More Items", "callback_data": "modify:add_items"}],
                [{"text": "Cancel All Items", "callback_data": "modify:cancel_all"}],
            ]
        }
        session.state = STATE_CONFIRMING
        db.commit()
        await self.client.send_message(chat_id, "Modify Order\n\nWhat would you like to do?", keyboard)

    async def _handle_modify_callback(
        self,
        db: Session,
        chat_id: int,
        session: UserSession,
        data: str,
    ) -> None:
        if data == "modify:update_order":
            session.state = STATE_MODIFY_UPDATE_ORDER
            db.commit()
            await self.client.send_message(
                chat_id,
                "\n".join(
                    [
                        _format_current_order(db, session),
                        "",
                        "What item do you want to update?",
                        "Example: Replace Coke with Pepsi",
                    ]
                ),
            )
            return

        if data == "modify:update_quantity":
            session.state = STATE_MODIFY_QUANTITY_ITEM
            db.commit()
            await self._send_item_choice_prompt(
                db,
                chat_id,
                session,
                "Update Quantity",
                "Which item quantity should be updated?",
                "modify:quantity_item",
            )
            return

        if data.startswith("modify:quantity_item:"):
            menu_item_id = int(data.rsplit(":", 1)[1])
            await self._ask_new_quantity(db, chat_id, session, menu_item_id)
            return

        if data == "modify:cancel_item":
            session.state = STATE_MODIFY_CANCEL_ITEM
            db.commit()
            await self._send_item_choice_prompt(
                db,
                chat_id,
                session,
                "Cancel Item",
                "Which item would you like to cancel?",
                "modify:remove_item",
            )
            return

        if data.startswith("modify:remove_item:"):
            menu_item_id = int(data.rsplit(":", 1)[1])
            order_items = _remove_order_item(session, menu_item_id)
            if not order_items:
                await self._cancel_all_items(db, chat_id, session)
                return
            _store_single_hotel_plan(session, order_items)
            db.commit()
            await self._send_modified_order_summary(db, chat_id, session, "Item cancelled successfully.")
            return

        if data == "modify:add_items":
            session.state = STATE_MODIFY_ADD_ITEMS
            db.commit()
            await self.client.send_message(chat_id, "Add More Items\n\nWhat would you like to add?")
            return

        if data == "modify:cancel_all":
            keyboard = {
                "inline_keyboard": [
                    [{"text": "Yes, cancel all", "callback_data": "modify:cancel_all_yes"}],
                    [{"text": "No, keep my order", "callback_data": "modify:cancel_all_no"}],
                ]
            }
            await self.client.send_message(
                chat_id,
                "Cancel All Items\n\nAre you sure you want to cancel all items?",
                keyboard,
            )
            return

        if data == "modify:cancel_all_yes":
            await self._cancel_all_items(db, chat_id, session)
            return

        if data == "modify:cancel_all_no":
            await self._send_modify_options(db, chat_id, session)
            return

        await self.client.send_message(chat_id, "I could not understand that modify option.")

    async def _handle_modify_message(
        self,
        db: Session,
        chat_id: int,
        session: UserSession,
        text: str,
    ) -> None:
        if session.state == STATE_MODIFY_UPDATE_ORDER:
            await self._handle_update_order_text(db, chat_id, session, text)
            return

        if session.state == STATE_MODIFY_QUANTITY_ITEM:
            order_item = _find_order_item_by_text(db, session, text)
            if not order_item:
                await self.client.send_message(chat_id, "I could not find that item in your order. Please try again.")
                return
            await self._ask_new_quantity(db, chat_id, session, int(order_item["menu_item_id"]))
            return

        if session.state == STATE_MODIFY_QUANTITY_VALUE:
            quantity = _parse_quantity(text)
            if quantity is None:
                await self.client.send_message(chat_id, "Enter a quantity between 1 and 99.")
                return
            menu_item_id = session.context.get("modify_menu_item_id")
            order_items = _editable_order_items(session)
            for order_item in order_items:
                if order_item.get("menu_item_id") == menu_item_id:
                    order_item["quantity"] = quantity
                    break
            session.context = {**session.context, "order_items": order_items}
            _store_single_hotel_plan(session, order_items)
            db.commit()
            await self._send_modified_order_summary(db, chat_id, session, "Quantity updated successfully.")
            return

        if session.state == STATE_MODIFY_CANCEL_ITEM:
            order_item = _find_order_item_by_text(db, session, text)
            if not order_item:
                await self.client.send_message(chat_id, "I could not find that item in your order. Please try again.")
                return
            order_items = _remove_order_item(session, int(order_item["menu_item_id"]))
            if not order_items:
                await self._cancel_all_items(db, chat_id, session)
                return
            _store_single_hotel_plan(session, order_items)
            db.commit()
            await self._send_modified_order_summary(db, chat_id, session, "Item cancelled successfully.")
            return

        if session.state == STATE_MODIFY_ADD_ITEMS:
            await self._handle_add_items_text(db, chat_id, session, text)
            return

    async def _handle_natural_modify_text(
        self,
        db: Session,
        chat_id: int,
        session: UserSession,
        text: str,
    ) -> None:
        replacement = _parse_replacement_text(text)
        if replacement:
            session.state = STATE_MODIFY_UPDATE_ORDER
            db.commit()
            await self._handle_update_order_text(db, chat_id, session, f"replace {replacement[0]} with {replacement[1]}")
            return

        removal_name = _parse_removal_text(text)
        if removal_name:
            order_item = _find_order_item_by_text(db, session, removal_name)
            if not order_item:
                await self.client.send_message(chat_id, f"I could not find {removal_name} in your order.")
                return
            order_items = _remove_order_item(session, int(order_item["menu_item_id"]))
            if not order_items:
                await self._cancel_all_items(db, chat_id, session)
                return
            _store_single_hotel_plan(session, order_items)
            db.commit()
            await self._send_modified_order_summary(db, chat_id, session, "Item cancelled successfully.")
            return

        quantity_change = _parse_quantity_change_text(text)
        if quantity_change:
            item_name, quantity = quantity_change
            order_items = _editable_order_items(session)
            order_item = _find_order_item_by_text(db, session, item_name) if item_name else None
            if not order_item and len(order_items) == 1:
                order_item = order_items[0]
            if not order_item:
                await self.client.send_message(chat_id, "Which item quantity should I update?")
                session.state = STATE_MODIFY_QUANTITY_ITEM
                db.commit()
                return
            order_item["quantity"] = quantity
            session.context = {**session.context, "order_items": order_items}
            _store_single_hotel_plan(session, order_items)
            db.commit()
            await self._send_modified_order_summary(db, chat_id, session, "Quantity updated successfully.")
            return

        await self._handle_add_items_text(db, chat_id, session, text)

    async def _handle_update_order_text(
        self,
        db: Session,
        chat_id: int,
        session: UserSession,
        text: str,
    ) -> None:
        match = re.search(r"\breplace\s+(.+?)\s+with\s+(.+)$", text, flags=re.IGNORECASE)
        if not match:
            parsed = _parse_replacement_text(text)
            if parsed:
                old_name, new_name = parsed
            else:
                await self.client.send_message(chat_id, "Tell me the change, for example: change Coke to Pepsi.")
                return
        else:
            old_name = match.group(1).strip()
            new_name = match.group(2).strip()
        old_item = _find_order_item_by_text(db, session, old_name)
        if not old_item:
            await self.client.send_message(chat_id, f"I could not find {old_name} in your order.")
            return

        old_menu_item = db.get(MenuItem, old_item.get("menu_item_id"))
        hotel_id = session.hotel_id or (old_menu_item.hotel_id if old_menu_item else None)
        if not hotel_id:
            await self.client.send_message(chat_id, "Select a hotel before modifying the order.")
            return

        new_menu_item = _best_menu_match(db, hotel_id, new_name)
        if not new_menu_item:
            await self.client.send_message(chat_id, f"I could not find {new_name} in this hotel menu.")
            return

        old_item["menu_item_id"] = new_menu_item.id
        old_item["extracted_name"] = new_name
        old_item["quantity"] = old_item.get("quantity") or 1
        session.context = {**session.context, "order_items": _editable_order_items(session)}
        _store_single_hotel_plan(session, _editable_order_items(session))
        db.commit()
        await self._send_modified_order_summary(db, chat_id, session, "Order updated successfully.")

    async def _handle_add_items_text(
        self,
        db: Session,
        chat_id: int,
        session: UserSession,
        text: str,
    ) -> None:
        if not session.hotel_id:
            await self.client.send_message(chat_id, "Select a hotel before adding more items.")
            return

        extraction = await extractor.extract(text)
        if extraction.intent != "ORDER" or not extraction.items:
            await self.client.send_message(chat_id, "Please send the item to add. Example: Add 1 Paneer Pizza")
            return

        order_items = _editable_order_items(session)
        added_names: list[str] = []
        missing_names: list[str] = []
        for extracted_item in extraction.items:
            menu_item = _best_menu_match(db, session.hotel_id, extracted_item.name)
            if not menu_item:
                missing_names.append(extracted_item.name)
                continue
            quantity = extracted_item.quantity or 1
            order_items.append(
                {
                    "menu_item_id": menu_item.id,
                    "quantity": quantity,
                    "extracted_name": extracted_item.name,
                }
            )
            added_names.append(f"{quantity} {menu_item.name}")

        if not added_names:
            await self.client.send_message(chat_id, f"I could not find: {', '.join(missing_names)}")
            return

        session.context = {**session.context, "order_items": order_items}
        _store_single_hotel_plan(session, order_items)
        db.commit()
        message = "Item added successfully." if len(added_names) == 1 else "Items added successfully."
        await self._send_modified_order_summary(db, chat_id, session, message)

    async def _ask_new_quantity(
        self,
        db: Session,
        chat_id: int,
        session: UserSession,
        menu_item_id: int,
    ) -> None:
        order_item = _find_order_item_by_menu_item_id(session, menu_item_id)
        menu_item = db.get(MenuItem, menu_item_id)
        if not order_item or not menu_item:
            await self.client.send_message(chat_id, "I could not find that item in your order.")
            return

        session.state = STATE_MODIFY_QUANTITY_VALUE
        session.context = {**session.context, "modify_menu_item_id": menu_item_id}
        db.commit()
        await self.client.send_message(
            chat_id,
            f"Update Quantity\n\nItem: {menu_item.name}\nCurrent quantity: {order_item.get('quantity') or 1}\nEnter new quantity:",
        )

    async def _send_item_choice_prompt(
        self,
        db: Session,
        chat_id: int,
        session: UserSession,
        title: str,
        question: str,
        callback_prefix: str,
    ) -> None:
        order_items = _editable_order_items(session)
        rows = []
        for order_item in order_items:
            menu_item = db.get(MenuItem, order_item.get("menu_item_id"))
            if not menu_item:
                continue
            rows.append(
                [
                    {
                        "text": f"{order_item.get('quantity') or 1} {menu_item.name}",
                        "callback_data": f"{callback_prefix}:{menu_item.id}",
                    }
                ]
            )

        keyboard = {"inline_keyboard": rows} if rows else None
        await self.client.send_message(
            chat_id,
            "\n".join([title, "", _format_current_order(db, session), "", question]),
            keyboard,
        )

    async def _send_modified_order_summary(
        self,
        db: Session,
        chat_id: int,
        session: UserSession,
        success_message: str,
    ) -> None:
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "PLACE ORDER", "callback_data": "confirm"},
                    {"text": "MODIFY", "callback_data": "modify"},
                ]
            ]
        }
        session.state = STATE_CONFIRMING
        db.commit()
        await self.client.send_message(
            chat_id,
            "\n".join([success_message, "", _format_current_order(db, session, "Updated Order:")]),
            keyboard,
        )

    async def _cancel_all_items(self, db: Session, chat_id: int, session: UserSession) -> None:
        session.state = STATE_WAITING_ITEM
        session.context = _preserve_date_context(session)
        db.commit()
        await self.client.send_message(
            chat_id,
            "All items cancelled.\n\nYour order is now empty.\nTotal: INR 0.00\n\nSend another item when you are ready.",
        )

    async def _send_menu(self, db: Session, chat_id: int, session: UserSession) -> None:
        """Delegate to categorized menu (Task 3)."""
        await nf.send_categorized_menu(self, db, chat_id, session)

    async def _handle_item_selection(self, db: Session, chat_id: int, session: UserSession, menu_item_id: int) -> None:
        if not session.hotel_id:
            await self._send_hotel_picker(db, chat_id, session)
            return

        menu_item = db.get(MenuItem, menu_item_id)
        pending_items = session.context.get("pending_items", [])
        pending_item = pending_items[0] if pending_items else {}
        candidate_ids = set(pending_item.get("candidate_ids", []))
        if not pending_item:
            await self.client.send_message(chat_id, "Send a food item first.")
            return
        if not menu_item or menu_item.hotel_id != session.hotel_id or not menu_item.is_available:
            await self.client.send_message(chat_id, "That menu item is not available.")
            return
        if candidate_ids and menu_item_id not in candidate_ids:
            await self.client.send_message(chat_id, "Please choose one of the shown menu items.")
            return

        order_items = session.context.get("order_items", [])
        order_items.append(
            {
                "menu_item_id": menu_item.id,
                "quantity": pending_item.get("quantity"),
                "extracted_name": pending_item.get("name"),
            }
        )
        session.context = {
            **session.context,
            "order_items": order_items,
            "pending_items": pending_items[1:],
        }
        db.commit()
        await self._advance_order_session(db, chat_id, session)

    async def _handle_quantity(
        self,
        db: Session,
        chat_id: int,
        customer: Customer,
        session: UserSession,
        text: str,
    ) -> None:
        quantity = _parse_quantity(text)
        if quantity is None:
            await self.client.send_message(chat_id, "Enter a quantity between 1 and 99.")
            return

        menu_item_id = session.context.get("quantity_menu_item_id")
        menu_item = db.get(MenuItem, menu_item_id)
        if not menu_item:
            session.state = STATE_WAITING_ITEM
            session.context = _preserve_date_context(session)
            db.commit()
            await self.client.send_message(chat_id, "That item is no longer available. Send another item.")
            return

        order_items = session.context.get("order_items", [])
        for order_item in order_items:
            if order_item.get("menu_item_id") == menu_item.id and not order_item.get("quantity"):
                order_item["quantity"] = quantity
                break

        session.context = {**(session.context or {}), "order_items": order_items, "pending_items": session.context.get("pending_items", [])}
        db.commit()
        await self._advance_order_session(db, chat_id, session)

    async def _confirm_order(self, db: Session, chat_id: int, customer: Customer, session: UserSession) -> None:
        if session.state != STATE_CONFIRMING:
            await self.client.send_message(chat_id, "Send a food item first.")
            return

        recommended_plans = session.context.get("recommended_plans") or []
        if recommended_plans:
            created_orders = []
            for plan in recommended_plans:
                payload_items = [
                    OrderItemCreate(menu_item_id=item["menu_item_id"], quantity=item["quantity"])
                    for item in plan.get("items", [])
                    if item.get("menu_item_id") and item.get("quantity")
                ]
                if not plan.get("hotel_id") or not payload_items:
                    continue

                order = create_order(
                    db,
                    OrderCreate(
                        hotel_id=plan["hotel_id"],
                        customer_id=customer.id,
                        items=payload_items,
                    ),
                )
                created_orders.append(order)

            session.state = STATE_WAITING_ITEM
            session.context = _preserve_date_context(session)
            db.commit()

            for order in created_orders:
                await manager.broadcast_to_hotel(
                    order.hotel_id,
                    {"type": "order.created", "order": serialize_order(order)},
                )

            if not created_orders:
                await self._send_hotel_picker(db, chat_id, session)
                return

            total = sum((Decimal(order.total_amount) for order in created_orders), Decimal("0"))
            order_numbers = ", ".join(f"#{order.id}" for order in created_orders)
            await self.client.send_message(
                chat_id,
                "\n".join(
                    [
                        "Order Placed",
                        "",
                        f"Orders: {order_numbers}",
                        f"Total: INR {total:.2f}",
                        f"Preparation Time: {DEFAULT_PREP_TIME}",
                    ]
                ),
            )
            return

        order_items = session.context.get("order_items", [])
        if not session.hotel_id or not order_items:
            await self._send_hotel_picker(db, chat_id, session)
            return

        payload_items = [
            OrderItemCreate(menu_item_id=item["menu_item_id"], quantity=item["quantity"])
            for item in order_items
            if item.get("menu_item_id") and item.get("quantity")
        ]
        if not payload_items:
            await self._send_hotel_picker(db, chat_id, session)
            return

        order = create_order(
            db,
            OrderCreate(
                hotel_id=session.hotel_id,
                customer_id=customer.id,
                items=payload_items,
            ),
        )
        session.state = STATE_WAITING_ITEM
        session.context = _preserve_date_context(session)
        db.commit()

        await manager.broadcast_to_hotel(
            order.hotel_id,
            {"type": "order.created", "order": serialize_order(order)},
        )
        await self.client.send_message(
            chat_id,
            "\n".join(
                [
                    "Order Placed",
                    "",
                    f"Order #{order.id}",
                    f"Total: INR {Decimal(order.total_amount):.2f}",
                    f"Preparation Time: {DEFAULT_PREP_TIME}",
                ]
            ),
        )

    async def _send_cross_hotel_recommendation(
        self,
        db: Session,
        chat_id: int,
        session: UserSession,
        selected_items: list[PlannedMenuItem],
        missing_items: list[Any],
    ) -> None:
        selected_hotel = db.get(Hotel, session.hotel_id)
        if not selected_hotel:
            await self._send_hotel_picker(db, chat_id, session)
            return

        better_single_hotel = _find_single_hotel_plan(db, selected_hotel.id, selected_items, missing_items)
        split_plan, still_missing = _find_minimum_split_plan(db, selected_hotel.id, missing_items)
        alternatives = _find_alternatives_for_missing(db, selected_hotel.id, still_missing)

        lines = ["Order Summary", "", "You requested:"]
        for item in selected_items:
            lines.append(f"- {item.quantity or 1} {item.requested_name}")
        for item in missing_items:
            lines.append(f"- {item.quantity or 1} {item.name}")

        lines.extend(["", SEP, ""])
        if selected_items:
            lines.append(f"Available in {selected_hotel.name}")
            lines.extend(_format_planned_item(item) for item in selected_items)
            lines.extend(["", SEP, ""])

        lines.append(f"Not available in {selected_hotel.name}")
        lines.extend(f"- {item.name}" for item in missing_items)
        lines.extend(["", SEP, ""])

        if better_single_hotel:
            _store_recommended_plans(session, [better_single_hotel])
            db.commit()
            lines.append("Recommendation")
            lines.append("")
            lines.append("Better single-hotel option found")
            lines.append("")
            lines.append(f"Hotel: {better_single_hotel.hotel.name}")
            lines.extend(_format_planned_item(item) for item in better_single_hotel.items)
            lines.extend(
                [
                    "",
                    SEP,
                    "",
                    f"Estimated Total: INR {_plan_total([better_single_hotel]):.2f}",
                    f"Preparation Time: {DEFAULT_PREP_TIME}",
                    "",
                    "Reply with:",
                    "PLACE ORDER",
                    "MODIFY ORDER",
                    "SHOW BETTER OPTIONS",
                ]
            )
            await self.client.send_message(chat_id, "\n".join(lines))
            return

        if split_plan:
            all_plans = [HotelSplitPlan(hotel=selected_hotel, items=selected_items)] + split_plan
            _store_recommended_plans(session, [plan for plan in all_plans if plan.items])
            db.commit()
            lines.append("Best combination found")
            if selected_items:
                lines.append("")
                lines.append(f"Hotel: {selected_hotel.name}")
                lines.extend(_format_planned_item(item) for item in selected_items)
            for plan in split_plan:
                lines.append("")
                lines.append(f"Hotel: {plan.hotel.name}")
                lines.extend(_format_planned_item(item) for item in plan.items)
            lines.extend(
                [
                    "",
                    SEP,
                    "",
                    f"Estimated Total: INR {_plan_total(all_plans):.2f}",
                    f"Preparation Time: {DEFAULT_PREP_TIME}",
                    "",
                    "Reply with:",
                    "PLACE ORDER",
                    "MODIFY ORDER",
                    "SHOW BETTER OPTIONS",
                ]
            )

        if still_missing:
            lines.extend(["", SEP, "", "Unavailable nearby"])
            for item in still_missing:
                alternative = alternatives.get(item.name.lower())
                if alternative:
                    lines.append(
                        f"- {item.name} unavailable. Try {alternative.items[0].menu_item.name} from {alternative.hotel.name}."
                    )
                else:
                    lines.append(f"- {item.name}")

        await self.client.send_message(chat_id, "\n".join(lines))

    def _upsert_customer(self, db: Session, telegram_user: dict[str, Any], chat_id: int) -> Customer:
        telegram_user_id = int(telegram_user["id"])
        customer = db.scalar(select(Customer).where(Customer.telegram_user_id == telegram_user_id))
        if not customer:
            customer = Customer(telegram_user_id=telegram_user_id, telegram_chat_id=chat_id)
            db.add(customer)

        customer.telegram_chat_id = chat_id
        customer.first_name = telegram_user.get("first_name")
        customer.last_name = telegram_user.get("last_name")
        customer.username = telegram_user.get("username")
        db.commit()
        db.refresh(customer)
        return customer

    def _get_or_create_session(self, db: Session, telegram_user_id: int) -> UserSession:
        session = db.scalar(select(UserSession).where(UserSession.telegram_user_id == telegram_user_id))
        if session:
            return session

        session = UserSession(telegram_user_id=telegram_user_id, state=STATE_START, context={})
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def _find_hotel_by_text(self, db: Session, text: str) -> Hotel | None:
        normalized_text = _normalize_text(text)
        if not normalized_text:
            return None

        hotels = db.scalars(select(Hotel).where(Hotel.is_active.is_(True))).all()
        for hotel in hotels:
            names = {hotel.name, hotel.slug, hotel.telegram_label or ""}
            normalized_names = {_normalize_text(name) for name in names if name}
            if normalized_text in normalized_names:
                return hotel
            if any(name and name in normalized_text for name in normalized_names):
                return hotel
        return None


def _parse_quantity(text: str) -> int | None:
    match = re.search(r"\d{1,2}", text)
    if not match:
        return None
    quantity = int(match.group())
    if quantity < 1 or quantity > 99:
        return None
    return quantity


def _number_word(word: str) -> int:
    return {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }.get(word, 1)


def _greeting_reply(session: UserSession) -> str:
    if _editable_order_items(session):
        return "Welcome back. Your order is still active.\n\nSay 'view cart' to see it or add more items."
    if session.hotel_id:
        return "Hi again! You can order food, say 'show menu', or type an item name."
    return "Hi! Say 'show hotels' to pick a hotel, or just type what you want to order."


def _is_natural_modify_text(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return bool(
        re.search(r"\b(remove|cancel|delete|replace|change|swap|make|reduce|increase|only)\b", normalized)
        or re.search(r"\b(add more|add another)\b", normalized)
    )


def _is_menu_request(text: str) -> bool:
    normalized = _normalize_text(text)
    return "menu" in normalized or ("available" in normalized and "item" in normalized)


def _parse_replacement_text(text: str) -> tuple[str, str] | None:
    normalized = _normalize_text(text)
    patterns = [
        r"\breplace\s+(.+?)\s+with\s+(.+)$",
        r"\bchange\s+(.+?)\s+to\s+(.+)$",
        r"\bswap\s+(.+?)\s+with\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match.group(1).strip(), match.group(2).strip()
    return None


def _parse_removal_text(text: str) -> str | None:
    normalized = _normalize_text(text)
    match = re.search(r"\b(?:remove|cancel|delete)\s+(.+)$", normalized)
    if not match:
        return None
    item_name = re.sub(r"\b(from|in|item|order|cart|please|pls)\b", " ", match.group(1))
    item_name = " ".join(item_name.split())
    return item_name or None


def _parse_quantity_change_text(text: str) -> tuple[str | None, int] | None:
    normalized = _normalize_text(text)
    normalized = re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b", lambda m: str(_number_word(m.group())), normalized)
    patterns = [
        r"\b(?:make|reduce|increase|change|set)\s+(.+?)\s+(?:to\s+)?(\d{1,2})\b",
        r"\bonly\s+(\d{1,2})\s+(.+)$",
        r"\b(.+?)\s+(?:to\s+)?(\d{1,2})\b",
        r"\bmake\s+it\s+(\d{1,2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        if pattern == patterns[1]:
            quantity = int(match.group(1))
            item_name = match.group(2)
        elif pattern == patterns[3]:
            quantity = int(match.group(1))
            item_name = None
        else:
            item_name = match.group(1)
            quantity = int(match.group(2))
        if quantity < 1 or quantity > 99:
            return None
        if item_name:
            item_name = re.sub(r"\b(quantity|qty|item|please|pls|it)\b", " ", item_name)
            item_name = " ".join(item_name.split()) or None
        return item_name, quantity
    return None


def _editable_order_items(session: UserSession) -> list[dict[str, Any]]:
    order_items = session.context.get("order_items") or []
    if order_items:
        return order_items

    recommended_plans = session.context.get("recommended_plans") or []
    if len(recommended_plans) != 1:
        return []

    plan = recommended_plans[0]
    if plan.get("hotel_id") and not session.hotel_id:
        session.hotel_id = plan["hotel_id"]
    return [
        {
            "menu_item_id": item.get("menu_item_id"),
            "quantity": item.get("quantity"),
            "extracted_name": item.get("extracted_name"),
        }
        for item in plan.get("items", [])
        if item.get("menu_item_id")
    ]


def _store_single_hotel_plan(session: UserSession, order_items: list[dict[str, Any]]) -> None:
    session.context = {
        **(session.context or {}),
        "order_items": order_items,
        "pending_items": [],
        "recommended_plans": [
            {
                "hotel_id": session.hotel_id,
                "items": [
                    {"menu_item_id": item["menu_item_id"], "quantity": item.get("quantity") or 1}
                    for item in order_items
                    if item.get("menu_item_id")
                ],
            }
        ],
    }


def _format_current_order(db: Session, session: UserSession, title: str = "Current Order:") -> str:
    order_items = _editable_order_items(session)
    lines = [title]
    total = Decimal("0")

    for order_item in order_items:
        menu_item = db.get(MenuItem, order_item.get("menu_item_id"))
        if not menu_item:
            continue
        quantity = int(order_item.get("quantity") or 1)
        line_total = Decimal(menu_item.price) * quantity
        total += line_total
        lines.append(f"- {quantity} {menu_item.name} - INR {line_total:.2f}")

    if len(lines) == 1:
        lines.append("- No items")
    lines.extend(["", f"Total: INR {total:.2f}"])
    return "\n".join(lines)


def _find_order_item_by_text(db: Session, session: UserSession, text: str) -> dict[str, Any] | None:
    normalized_query = _normalize_text(text)
    if not normalized_query:
        return None

    for order_item in _editable_order_items(session):
        menu_item = db.get(MenuItem, order_item.get("menu_item_id"))
        names = [order_item.get("extracted_name") or "", menu_item.name if menu_item else ""]
        normalized_names = [_normalize_text(name) for name in names if name]
        if any(normalized_query == name for name in normalized_names):
            return order_item
        if any(normalized_query in name or name in normalized_query for name in normalized_names):
            return order_item
    return None


def _find_order_item_by_menu_item_id(session: UserSession, menu_item_id: int) -> dict[str, Any] | None:
    return next(
        (item for item in _editable_order_items(session) if item.get("menu_item_id") == menu_item_id),
        None,
    )


def _remove_order_item(session: UserSession, menu_item_id: int) -> list[dict[str, Any]]:
    removed = False
    remaining = []
    for item in _editable_order_items(session):
        if item.get("menu_item_id") == menu_item_id and not removed:
            removed = True
            continue
        remaining.append(item)
    session.context = {**session.context, "order_items": remaining}
    return remaining


def _find_auto_match(extracted_name: str, matches: list[Any]) -> Any | None:
    normalized_query = _normalize_text(extracted_name)
    containing_matches: list[Any] = []

    for match in matches:
        item = match.item
        normalized_name = _normalize_text(item.name)
        if normalized_name == normalized_query:
            return item
        if normalized_query in normalized_name.split() or normalized_query in normalized_name:
            containing_matches.append(item)

    if len(containing_matches) == 1:
        return containing_matches[0]
    return None


def _load_menu_items(db: Session, menu_item_ids: list[int]) -> list[MenuItem]:
    if not menu_item_ids:
        return []

    items = db.scalars(select(MenuItem).where(MenuItem.id.in_(menu_item_ids))).all()
    by_id = {item.id: item for item in items}
    return [by_id[item_id] for item_id in menu_item_ids if item_id in by_id]


def _store_recommended_plans(session: UserSession, plans: list[HotelSplitPlan]) -> None:
    session.state = STATE_CONFIRMING
    session.context = {
        **(session.context or {}),
        "recommended_plans": [
            {
                "hotel_id": plan.hotel.id,
                "items": [
                    {"menu_item_id": item.menu_item.id, "quantity": item.quantity or 1}
                    for item in plan.items
                ],
            }
            for plan in plans
            if plan.items
        ],
    }


def _find_single_hotel_plan(
    db: Session,
    selected_hotel_id: int,
    selected_items: list[PlannedMenuItem],
    missing_items: list[Any],
) -> HotelSplitPlan | None:
    requested = [(item.requested_name, item.quantity) for item in selected_items]
    requested.extend((item.name, item.quantity) for item in missing_items)
    if not requested:
        return None

    best_plan: HotelSplitPlan | None = None
    for hotel in _active_hotels_except(db, selected_hotel_id):
        planned_items: list[PlannedMenuItem] = []
        for requested_name, quantity in requested:
            menu_item = _best_menu_match(db, hotel.id, requested_name)
            if not menu_item:
                break
            planned_items.append(
                PlannedMenuItem(requested_name=requested_name, quantity=quantity, menu_item=menu_item)
            )
        else:
            plan = HotelSplitPlan(hotel=hotel, items=planned_items)
            if not best_plan or _plan_total([plan]) < _plan_total([best_plan]):
                best_plan = plan
    return best_plan


def _find_minimum_split_plan(
    db: Session,
    selected_hotel_id: int,
    missing_items: list[Any],
) -> tuple[list[HotelSplitPlan], list[Any]]:
    remaining = list(missing_items)
    plans: list[HotelSplitPlan] = []

    while remaining:
        best_hotel: Hotel | None = None
        best_items: list[PlannedMenuItem] = []

        for hotel in _active_hotels_except(db, selected_hotel_id):
            planned_items: list[PlannedMenuItem] = []
            for missing_item in remaining:
                menu_item = _best_menu_match(db, hotel.id, missing_item.name)
                if menu_item:
                    planned_items.append(
                        PlannedMenuItem(
                            requested_name=missing_item.name,
                            quantity=missing_item.quantity,
                            menu_item=menu_item,
                        )
                    )

            if not planned_items:
                continue
            if not best_items:
                best_hotel = hotel
                best_items = planned_items
                continue

            best_key = (-len(best_items), _items_total(best_items))
            candidate_key = (-len(planned_items), _items_total(planned_items))
            if candidate_key < best_key:
                best_hotel = hotel
                best_items = planned_items

        if not best_hotel or not best_items:
            break

        plans.append(HotelSplitPlan(hotel=best_hotel, items=best_items))
        covered_names = {item.requested_name.lower() for item in best_items}
        remaining = [item for item in remaining if item.name.lower() not in covered_names]

    return plans, remaining


def _find_alternatives_for_missing(
    db: Session,
    selected_hotel_id: int,
    missing_items: list[Any],
) -> dict[str, HotelSplitPlan]:
    alternatives: dict[str, HotelSplitPlan] = {}
    for missing_item in missing_items:
        best_plan: HotelSplitPlan | None = None
        best_score = 0.0
        for hotel in _active_hotels_except(db, selected_hotel_id):
            matches = search_menu(db, hotel.id, missing_item.name, limit=1, min_score=0.18)
            if not matches:
                continue
            match = matches[0]
            if match.score <= best_score:
                continue
            best_score = match.score
            best_plan = HotelSplitPlan(
                hotel=hotel,
                items=[
                    PlannedMenuItem(
                        requested_name=missing_item.name,
                        quantity=missing_item.quantity,
                        menu_item=match.item,
                    )
                ],
            )
        if best_plan:
            alternatives[missing_item.name.lower()] = best_plan
    return alternatives


def _active_hotels_except(db: Session, hotel_id: int) -> list[Hotel]:
    return db.scalars(
        select(Hotel).where(Hotel.is_active.is_(True), Hotel.id != hotel_id).order_by(Hotel.name.asc())
    ).all()


def _best_menu_match(db: Session, hotel_id: int, requested_name: str) -> Any | None:
    matches = search_menu(db, hotel_id, requested_name, limit=6)
    if not matches:
        return None
    auto_match = _find_auto_match(requested_name, matches)
    if auto_match:
        return auto_match
    return matches[0].item


def _format_planned_item(item: PlannedMenuItem) -> str:
    quantity = item.quantity or 1
    line_total = Decimal(item.menu_item.price) * quantity
    return f"- {quantity} {item.menu_item.name} - INR {line_total:.2f}"


def _plan_total(plans: list[HotelSplitPlan]) -> Decimal:
    return sum((_items_total(plan.items) for plan in plans), Decimal("0"))


def _items_total(items: list[PlannedMenuItem]) -> Decimal:
    return sum((Decimal(item.menu_item.price) * (item.quantity or 1) for item in items), Decimal("0"))


def _strip_hotel_reference(text: str, hotel: Hotel) -> str:
    cleaned = text
    names = [hotel.name, hotel.slug, hotel.telegram_label or ""]
    for name in names:
        if not name:
            continue
        cleaned = re.sub(re.escape(name), " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(from|hotel|restaurant|order|show menu|menu|i want food from)\b", " ", cleaned, flags=re.I)
    return " ".join(cleaned.split())


def _contains_order_signal(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    filler = {"from", "hotel", "restaurant", "order", "menu", "show", "i", "want", "food"}
    tokens = [token for token in normalized.split() if token not in filler]
    return bool(tokens)




def _preserve_date_context(session: UserSession) -> dict:
    """Return a fresh context dict that preserves last_active_date from the current session.

    Use this instead of ``session.context = {}`` everywhere we want to clear the
    ordering state but NOT lose the daily-session date tracking.
    """
    saved_date = (session.context or {}).get("last_active_date")
    return {"last_active_date": saved_date} if saved_date else {}

def _normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


def _plain_english_text(text: str) -> str:
    text = _repair_mojibake(text)
    replacements = {
        "\u20b9": "INR",
        "\u2192": "-",
        "\u2022": "-",
        "\u2501": "-",
        "\u2705": "",
        "\u26a0": "",
        "\u270f": "",
        "\ufe0f": "",
        "\U0001f374": "",
        "\U0001f916": "",
        "\U0001f3e8": "",
        "\U0001f4b0": "",
        "\U0001f501": "",
        "\u23f1": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"^[ \t]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"-{13,}", SEP, text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _repair_mojibake(text: str) -> str:
    try:
        return text.encode("latin1").decode("utf-8")
    except UnicodeError:
        return text


telegram_bot = TelegramBotService()
