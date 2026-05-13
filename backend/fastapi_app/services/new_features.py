"""Task 1: Voice Ordering, Task 2: Daily Sessions, Task 3: Interactive Menus.

All new methods and helpers for the three features. These are mixed into
TelegramBotService at import time (see bottom of this file).
"""

import logging
import re
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi_app.core.config import get_settings
from fastapi_app.models.customer import Customer
from fastapi_app.models.hotel import Hotel
from fastapi_app.models.menu_item import MenuItem
from fastapi_app.models.order import Order, OrderItem
from fastapi_app.models.user_session import UserSession
from fastapi_app.services.voice_service import download_telegram_voice, transcribe_voice

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# ────────────────────────────────────────────────────────────
#  TASK 2 — Daily Session Reset
# ────────────────────────────────────────────────────────────

def check_and_reset_daily_session(db: Session, session: UserSession) -> bool:
    """Return True if this is the first interaction of a new day (IST).

    Resets the session state, cart and hotel selection when date changes.
    Stores today's date in ``context.last_active_date`` so future calls
    within the same day are no-ops.
    """
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    last_active = (session.context or {}).get("last_active_date")
    if last_active == today_str:
        return False

    # Preserve last_active_date across reset
    session.state = "START"
    session.hotel_id = None
    session.context = {"last_active_date": today_str}
    db.commit()
    return True


def _time_greeting() -> str:
    hour = datetime.now(IST).hour
    if hour < 12:
        return "Good Morning"
    if hour < 17:
        return "Good Afternoon"
    return "Good Evening"


async def send_daily_greeting(self: Any, db: Session, chat_id: int, session: UserSession) -> None:
    """Show a time-aware greeting with today's available hotels."""
    hotels = db.scalars(
        select(Hotel).where(Hotel.is_active.is_(True)).order_by(Hotel.name.asc())
    ).all()

    hotel_lines = "\n".join(f"  {h.telegram_label or h.name}" for h in hotels) if hotels else "  No hotels available right now."

    keyboard = {
        "inline_keyboard": [
            [{"text": h.telegram_label or h.name, "callback_data": f"hotel:{h.id}"}]
            for h in hotels
        ]
    } if hotels else None

    greeting = _time_greeting()
    text = "\n".join([
        f"{greeting}!",
        "",
        "Available Hotels Today:",
        "",
        hotel_lines,
        "",
        "Reply with:",
        "- hotel name",
        "- food items",
        "- or voice message",
    ])
    await self.client.send_message(chat_id, text, keyboard)


async def handle_same_as_yesterday(
    self: Any, db: Session, chat_id: int, customer: Customer, session: UserSession
) -> None:
    """Re-create yesterday's last order into the cart."""
    last_order = db.scalar(
        select(Order)
        .where(Order.customer_id == customer.id)
        .order_by(Order.created_at.desc())
    )
    if not last_order:
        await self.client.send_message(chat_id, "I could not find any previous orders.\n\nSend your food items to start a new order.")
        return

    # Load items from the last order
    order_items_db = db.scalars(
        select(OrderItem).where(OrderItem.order_id == last_order.id)
    ).all()
    if not order_items_db:
        await self.client.send_message(chat_id, "Your last order had no items. Send your food items to start fresh.")
        return

    session.hotel_id = last_order.hotel_id
    order_items = [
        {
            "menu_item_id": oi.menu_item_id,
            "quantity": oi.quantity,
            "extracted_name": oi.item_name_snapshot,
        }
        for oi in order_items_db
    ]
    session.context = {
        **(session.context or {}),
        "order_items": order_items,
        "pending_items": [],
    }
    db.commit()

    # Show the order summary so user can confirm or modify
    await self._send_order_summary(db, chat_id, session)


# ────────────────────────────────────────────────────────────
#  TASK 1 — Voice Ordering
# ────────────────────────────────────────────────────────────

async def handle_voice_message(
    self: Any,
    db: Session,
    chat_id: int,
    customer: Customer,
    session: UserSession,
    voice: dict[str, Any],
    is_new_day: bool,
) -> None:
    """Download a Telegram voice message, transcribe it, then process as text."""
    if is_new_day:
        await send_daily_greeting(self, db, chat_id, session)

    file_id = voice.get("file_id")
    if not file_id:
        await self.client.send_message(chat_id, "I could not process that voice message. Please try again.")
        return

    # Download
    audio_bytes = await download_telegram_voice(file_id)
    if not audio_bytes:
        await self.client.send_message(
            chat_id,
            "I could not download the voice message. Please type your order instead.",
        )
        return

    # Transcribe
    mime = voice.get("mime_type", "audio/ogg")
    ext = ".ogg"
    if "mp3" in mime:
        ext = ".mp3"
    elif "wav" in mime:
        ext = ".wav"

    transcribed_text = await transcribe_voice(audio_bytes, ext)
    if not transcribed_text:
        await self.client.send_message(
            chat_id,
            "Voice ordering requires an AI provider.\n\nPlease type your order instead.\nExample: 2 biryani and 1 coke",
        )
        return

    # Acknowledge the voice input
    await self.client.send_message(
        chat_id,
        f"Voice Order Received\n\nI heard: \"{transcribed_text}\"\n\nProcessing your order...",
    )

    # Feed into the normal message handler pipeline
    # Build a fake message dict so _handle_message can process it
    fake_message: dict[str, Any] = {
        "chat": {"id": chat_id},
        "from": {"id": session.telegram_user_id},
        "text": transcribed_text,
    }
    await self._handle_message(db, fake_message)


# ────────────────────────────────────────────────────────────
#  TASK 3 — Interactive Menu System
# ────────────────────────────────────────────────────────────

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Dosa": ["dosa", "uttapam", "uthappam"],
    "Idli": ["idli", "idly"],
    "Biryani": ["biryani", "biriyani", "pulao", "rice"],
    "Pizza": ["pizza"],
    "Burger": ["burger"],
    "Sandwich": ["sandwich", "wrap", "roll"],
    "Chinese": ["noodles", "manchurian", "fried rice", "chowmein", "momos"],
    "Bread": ["naan", "roti", "chapati", "paratha", "kulcha"],
    "Curry": ["curry", "dal", "paneer", "gravy"],
    "Snacks": ["samosa", "vada", "pakora", "pakoda", "bhaji", "fries", "nuggets"],
    "Dessert": ["ice cream", "gulab jamun", "rasgulla", "halwa", "sweet", "cake"],
    "Drinks": ["coke", "pepsi", "sprite", "juice", "mojito", "lassi", "buttermilk",
               "tea", "coffee", "chai", "water", "soda", "milkshake", "shake", "lemonade"],
}


class MenuLlmItem(BaseModel):
    id: int
    name: str = Field(..., min_length=1, max_length=180)
    price: float
    category: str = Field(..., min_length=1, max_length=80)


class MenuLlmCategory(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    items: list[MenuLlmItem] = Field(default_factory=list)


class MenuLlmPlan(BaseModel):
    intent: str = Field(default="")
    categories: list[MenuLlmCategory] = Field(default_factory=list)


def _infer_category(item_name: str) -> str:
    name_lower = item_name.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return category
    return "Other"


def _get_item_category(item: MenuItem) -> str:
    if item.category:
        return item.category
    return _infer_category(item.name)


def _group_by_category(items: list[MenuItem]) -> dict[str, list[MenuItem]]:
    groups: dict[str, list[MenuItem]] = {}
    for item in items:
        cat = _get_item_category(item)
        groups.setdefault(cat, []).append(item)
    return groups


async def send_categorized_menu(self: Any, db: Session, chat_id: int, session: UserSession, edit_message_id: int | None = None) -> None:
    """Show menu grouped by category."""
    if not session.hotel_id:
        await self._send_hotel_picker(db, chat_id, session)
        return

    hotel = db.get(Hotel, session.hotel_id)
    items = db.scalars(
        select(MenuItem)
        .where(MenuItem.hotel_id == session.hotel_id, MenuItem.is_available.is_(True))
        .order_by(MenuItem.name.asc())
    ).all()

    if not items:
        await self.client.send_message(chat_id, "No menu items are available right now.")
        return

    groups = _group_by_category(list(items))
    hotel_name = hotel.name if hotel else "Selected Hotel"

    lines = [f"{hotel_name} Menu", "", "------------"]

    for category, cat_items in sorted(groups.items()):
        lines.append("")
        lines.append(f"{category}")
        lines.append("")
        for ci in cat_items:
            lines.append(f"  {ci.name} - INR {Decimal(ci.price):.2f}")
        lines.append("")
        lines.append("------------")

    lines.extend(["", "Type your order, for example: 3 dosa and 2 biryani"])
    if edit_message_id:
        await self.client.edit_message_text(chat_id, edit_message_id, "\n".join(lines))
    else:
        await self.client.send_message(chat_id, "\n".join(lines))


async def send_smart_menu(
    self: Any,
    db: Session,
    chat_id: int,
    session: UserSession,
    text: str,
    edit_message_id: int | None = None,
) -> None:
    """Show a menu shaped by the user's question, with heuristic fallback."""
    if not session.hotel_id:
        await self._send_hotel_picker(db, chat_id, session)
        return

    hotel = db.get(Hotel, session.hotel_id)
    items = db.scalars(
        select(MenuItem)
        .where(MenuItem.hotel_id == session.hotel_id, MenuItem.is_available.is_(True))
        .order_by(MenuItem.name.asc())
    ).all()

    if not items:
        await self.client.send_message(chat_id, "No menu items are available right now.")
        return

    sections = await _build_menu_sections_from_question(text, list(items))
    if not sections:
        await self.client.send_message(chat_id, "No matching items found. Try 'show menu' to see all items.")
        return

    hotel_name = hotel.name if hotel else "Selected Hotel"
    title = f"{hotel_name} Menu"
    if _has_specific_menu_filter(text):
        title = f"{hotel_name} - Matching Menu"

    lines = [title, "", "------------"]
    seen_ids: set[int] = set()

    for category, cat_items in sections:
        visible_items = [item for item in cat_items if item.id not in seen_ids]
        if not visible_items:
            continue
        lines.append("")
        lines.append(category)
        lines.append("")
        for item in visible_items:
            seen_ids.add(item.id)
            lines.append(f"  {item.name} - INR {Decimal(item.price):.2f}")
        lines.append("")
        lines.append("------------")

    lines.extend(["", "Type your order, for example: 3 dosa and 2 biryani"])
    if edit_message_id:
        await self.client.edit_message_text(chat_id, edit_message_id, "\n".join(lines))
    else:
        await self.client.send_message(chat_id, "\n".join(lines))


async def _build_menu_sections_from_question(text: str, items: list[MenuItem]) -> list[tuple[str, list[MenuItem]]]:
    if _is_generic_menu_request(text):
        groups = _group_by_category(items)
        return [(category, cat_items) for category, cat_items in sorted(groups.items())]

    llm_sections = await _llm_menu_sections(text, items)
    if llm_sections:
        return llm_sections
    return _heuristic_menu_sections(text, items)


async def _llm_menu_sections(text: str, items: list[MenuItem]) -> list[tuple[str, list[MenuItem]]]:
    settings = get_settings()
    provider = settings.ai_provider.lower().strip()
    if provider == "openai":
        return await _openai_menu_sections(text, items)
    if provider == "gemini":
        return await _gemini_menu_sections(text, items)
    return []


async def _openai_menu_sections(text: str, items: list[MenuItem]) -> list[tuple[str, list[MenuItem]]]:
    settings = get_settings()
    if not settings.openai_api_key:
        return []
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.exception("openai package is not installed; using heuristic menu filtering")
        return []

    payload = _menu_llm_payload(text, items)
    prompt = _menu_llm_prompt(payload)
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.responses.parse(
            model=settings.openai_model,
            input=[
                {"role": "system", "content": MENU_LLM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            text_format=MenuLlmPlan,
        )
    except Exception:
        logger.exception("OpenAI menu filtering failed; using heuristic menu filtering")
        return []

    for output in response.output:
        if output.type != "message":
            continue
        for content in output.content:
            parsed = getattr(content, "parsed", None)
            if parsed:
                return _sections_from_llm_plan(parsed, items)
    return []


async def _gemini_menu_sections(text: str, items: list[MenuItem]) -> list[tuple[str, list[MenuItem]]]:
    settings = get_settings()
    if not settings.gemini_api_key:
        return []
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.exception("google-genai package is not installed; using heuristic menu filtering")
        return []

    prompt = f"{MENU_LLM_SYSTEM_PROMPT}\n\n{_menu_llm_prompt(_menu_llm_payload(text, items))}"
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MenuLlmPlan.model_json_schema(),
            ),
        )
        plan = MenuLlmPlan.model_validate(json.loads(response.text or "{}"))
    except Exception:
        logger.exception("Gemini menu filtering failed; using heuristic menu filtering")
        return []
    return _sections_from_llm_plan(plan, items)


MENU_LLM_SYSTEM_PROMPT = """
You are an intelligent restaurant menu organizer for a Telegram food ordering AI.

Your job:
1. Read the user's food request.
2. Analyze intent carefully.
3. Select ONLY relevant menu items from the provided menu database.
4. Return ONLY valid JSON.
5. Never include explanations, markdown, comments, or extra text.

--------------------------------------------------
CORE RULES
--------------------------------------------------

- Use ONLY items provided in the menu.
- NEVER invent:
  - item names
  - ids
  - prices
  - categories
  - descriptions

- Every selected item MUST contain:
  - id
  - name
  - price
  - category

- Prioritize the most relevant items first.

- Group items into short customer-friendly categories.

--------------------------------------------------
INTENT UNDERSTANDING
--------------------------------------------------

Understand natural human food requests including:
- category requests
- cravings
- ingredients
- meal type
- dietary preference
- language variations
- spelling mistakes
- short forms

Examples:
- "veg items"
- "only dosa"
- "rice items"
- "breakfast"
- "something spicy"
- "cool drinks"
- "non veg starter"
- "south indian"
- "light food"
- "snacks"
- "healthy food"

--------------------------------------------------
VEG / NON-VEG FILTERING
--------------------------------------------------

If the user asks for vegetarian food:
EXCLUDE items containing words like:
- chicken
- mutton
- fish
- prawn
- egg
- keema
- meat
- beef
- pork

If user asks non-veg:
Prioritize meat-based items.

--------------------------------------------------
CATEGORY MATCHING
--------------------------------------------------

Map user intent intelligently.

Examples:
- dosa -> dosa category
- rice -> biryani, fried rice, meals, pulao
- drinks -> juice, cool drinks, shakes
- snacks -> starters, chats, fries
- curry -> gravy, masala, kurma

--------------------------------------------------
SMART PRIORITIZATION
--------------------------------------------------

Order results by:
1. Exact match
2. Strong category match
3. Related items
4. Popular combinations

Example:
User: "dosa"
Priority:
- Masala Dosa
- Plain Dosa
- Onion Dosa
- Set Dosa

NOT:
- Biryani
- Juice

--------------------------------------------------
GENERIC MENU REQUESTS
--------------------------------------------------

If the user asks:
- "show menu"
- "full menu"
- "all items"

Return all menu items grouped properly.

--------------------------------------------------
MULTILINGUAL UNDERSTANDING
--------------------------------------------------

Understand mixed language requests:
Examples:
- "veg dosa"
- "anna rice item"
- "masala dosa ideya"
- "cool drinks"
- "chapati curry"

--------------------------------------------------
OUTPUT FORMAT
--------------------------------------------------

Return STRICT JSON ONLY.

Example format:

{
  "intent": "veg dosa",
  "categories": [
    {
      "name": "Veg Dosa",
      "items": [
        {
          "id": 12,
          "name": "Masala Dosa",
          "price": 80,
          "category": "Dosa"
        }
      ]
    }
  ]
}

--------------------------------------------------
IMPORTANT
--------------------------------------------------

- No duplicate items
- No empty categories
- No markdown
- No explanation text
- No hallucinations
- JSON must always be valid
"""


def _menu_llm_payload(text: str, items: list[MenuItem]) -> dict[str, Any]:
    return {
        "user_question": text,
        "menu_items": [
            {
                "id": item.id,
                "name": item.name,
                "category": _get_item_category(item),
                "description": item.description or "",
                "price": float(item.price),
            }
            for item in items[:120]
        ],
    }


def _menu_llm_prompt(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True)


def _sections_from_llm_plan(plan: MenuLlmPlan, items: list[MenuItem]) -> list[tuple[str, list[MenuItem]]]:
    by_id = {item.id: item for item in items}
    used: set[int] = set()
    sections: list[tuple[str, list[MenuItem]]] = []
    for section in plan.categories:
        selected: list[MenuItem] = []
        for llm_item in section.items:
            item_id = llm_item.id
            if item_id in used or item_id not in by_id:
                continue
            selected.append(by_id[item_id])
            used.add(item_id)
        if selected:
            sections.append((section.name.strip() or "Other", selected))
    return sections


def _heuristic_menu_sections(text: str, items: list[MenuItem]) -> list[tuple[str, list[MenuItem]]]:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    veg_only = "veg" in normalized and "non" not in normalized
    non_veg_only = "non veg" in normalized or "nonveg" in normalized
    filter_terms = [w for w in normalized.split() if w not in {
        "show", "i", "want", "only", "items", "item", "menu", "food", "foods", "veg", "non",
        "spicy", "the", "a", "an", "me", "give", "list", "available", "send", "just", "pure",
    }]

    if "rice" in normalized:
        filter_terms.append("rice")

    filtered: list[MenuItem] = []
    for item in items:
        name_lower = item.name.lower()
        desc_lower = (item.description or "").lower()
        cat = _get_item_category(item).lower()
        non_veg = any(w in name_lower for w in ["chicken", "mutton", "fish", "egg", "prawn", "meat", "keema"])

        if veg_only and non_veg:
            continue
        if non_veg_only and not non_veg:
            continue

        if filter_terms:
            if any(term in name_lower or term in cat or term in desc_lower for term in filter_terms):
                filtered.append(item)
        else:
            filtered.append(item)

    groups = _group_by_category(filtered)
    return [(category, cat_items) for category, cat_items in sorted(groups.items())]


def _is_generic_menu_request(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    normalized = " ".join(normalized.split())
    return normalized in {
        "menu",
        "show menu",
        "send menu",
        "hotel menu",
        "show full menu",
        "full menu",
        "what is available",
        "what food available",
        "available food",
        "items available",
    }


def _has_specific_menu_filter(text: str) -> bool:
    return not _is_generic_menu_request(text)


async def send_filtered_menu(self: Any, db: Session, chat_id: int, session: UserSession, text: str, edit_message_id: int | None = None) -> None:
    """Show menu items matching a category or filter keyword."""
    if not session.hotel_id:
        await self._send_hotel_picker(db, chat_id, session)
        return

    hotel = db.get(Hotel, session.hotel_id)
    items = db.scalars(
        select(MenuItem)
        .where(MenuItem.hotel_id == session.hotel_id, MenuItem.is_available.is_(True))
        .order_by(MenuItem.name.asc())
    ).all()

    normalized = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    # Determine which filter to apply
    veg_only = "veg" in normalized and "non" not in normalized
    filter_terms = [w for w in normalized.split() if w not in {
        "show", "i", "want", "only", "items", "menu", "food", "veg", "non",
        "spicy", "the", "a", "an", "me", "give", "list",
    }]

    filtered: list[MenuItem] = []
    for item in items:
        name_lower = item.name.lower()
        desc_lower = (item.description or "").lower()
        cat = _get_item_category(item).lower()

        if veg_only:
            non_veg = any(w in name_lower for w in ["chicken", "mutton", "fish", "egg", "prawn", "meat", "keema"])
            if non_veg:
                continue

        if filter_terms:
            if any(term in name_lower or term in cat or term in desc_lower for term in filter_terms):
                filtered.append(item)
        else:
            filtered.append(item)

    if not filtered:
        await self.client.send_message(chat_id, f"No matching items found. Try 'show menu' to see all items.")
        return

    hotel_name = hotel.name if hotel else "Selected Hotel"
    lines = [f"{hotel_name} - Filtered Menu", ""]
    for item in filtered[:20]:
        lines.append(f"  {item.name} - INR {Decimal(item.price):.2f}")

    lines.extend(["", "Type your order, for example: 3 dosa and 2 biryani"])
    if edit_message_id:
        await self.client.edit_message_text(chat_id, edit_message_id, "\n".join(lines))
    else:
        await self.client.send_message(chat_id, "\n".join(lines))


async def handle_addcart_callback(
    self: Any, db: Session, chat_id: int, session: UserSession, menu_item_id: int, callback_id: str
) -> None:
    """When user taps a menu item button, add to pending selection and show toast."""
    menu_item = db.get(MenuItem, menu_item_id)
    if not menu_item or not menu_item.is_available:
        await self.client.answer_callback_query(callback_id, "That item is not available.")
        return

    # Update pending selected items
    pending_items = session.context.get("pending_selected_items", {})
    item_id_str = str(menu_item.id)
    pending_items[item_id_str] = pending_items.get(item_id_str, 0) + 1
    
    session.context = {**(session.context or {}), "pending_selected_items": pending_items}
    if not session.hotel_id:
        session.hotel_id = menu_item.hotel_id
    db.commit()

    # Show toast
    count = pending_items[item_id_str]
    await self.client.answer_callback_query(callback_id, f"✅ {menu_item.name} Selected ({count})")


async def handle_batch_checkout_callback(
    self: Any, db: Session, chat_id: int, session: UserSession, data: str, message_id: int | None = None
) -> None:
    if data == "batch:more":
        await send_categorized_menu(self, db, chat_id, session, edit_message_id=message_id)
        return

    if data == "batch:done":
        pending_items = session.context.get("pending_selected_items", {})
        if not pending_items:
            await self.client.send_message(chat_id, "No items selected.")
            return

        lines = ["🛒 Selected Items", ""]
        for mid_str, m_count in pending_items.items():
            mi = db.get(MenuItem, int(mid_str))
            if mi:
                lines.append(f"• {mi.name} ({m_count})")
        lines.extend(["", "Choose Next Action 👇"])

        keyboard = {
            "inline_keyboard": [
                [{"text": "✅ Add Selected Items", "callback_data": "batch:checkout"}],
                [{"text": "➕ Select More", "callback_data": "batch:more"}],
                [{"text": "🛒 View Cart", "callback_data": "cart:view"}]
            ]
        }
        if message_id:
            await self.client.edit_message_text(chat_id, message_id, "\n".join(lines), keyboard)
        else:
            await self.client.send_message(chat_id, "\n".join(lines), keyboard)
        return

    if data == "batch:checkout":
        pending_items = session.context.get("pending_selected_items", {})
        if not pending_items:
            await self.client.send_message(chat_id, "No items selected.")
            return

        batch_queue = list(pending_items.keys())
        session.state = "BATCH_QUANTITY_SELECTION"
        session.context = {
            **(session.context or {}),
            "batch_quantity_queue": batch_queue,
            "batch_cart_items": []
        }
        db.commit()
        await _prompt_next_batch_quantity(self, db, chat_id, session)

async def _prompt_next_batch_quantity(self: Any, db: Session, chat_id: int, session: UserSession) -> None:
    queue = session.context.get("batch_quantity_queue", [])
    if not queue:
        # Done asking quantities, move to cart
        batch_cart_items = session.context.get("batch_cart_items", [])
        order_items = session.context.get("order_items", [])
        order_items.extend(batch_cart_items)
        session.state = "WAITING_ITEM"
        
        ctx = dict(session.context or {})
        ctx.pop("pending_selected_items", None)
        ctx.pop("batch_quantity_queue", None)
        ctx.pop("batch_cart_items", None)
        ctx.pop("selection_message_id", None)
        ctx["order_items"] = order_items
        ctx["pending_items"] = []
        session.context = ctx
        db.commit()
        await send_cart_summary(self, db, chat_id, session, "✅ Items Added to Cart\n\nYour Cart:")
        return

    next_item_id = int(queue[0])
    menu_item = db.get(MenuItem, next_item_id)
    if not menu_item:
        session.context = {**(session.context or {}), "batch_quantity_queue": queue[1:]}
        db.commit()
        await _prompt_next_batch_quantity(self, db, chat_id, session)
        return

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "1", "callback_data": f"qty:{menu_item.id}:1"},
                {"text": "2", "callback_data": f"qty:{menu_item.id}:2"},
                {"text": "3", "callback_data": f"qty:{menu_item.id}:3"},
                {"text": "4", "callback_data": f"qty:{menu_item.id}:4"},
            ]
        ]
    }
    await self.client.send_message(
        chat_id,
        f"🍽️ Quantity for {menu_item.name}?",
        keyboard,
    )


async def handle_qty_callback(
    self: Any, db: Session, chat_id: int, session: UserSession, menu_item_id: int, quantity: int
) -> None:
    """Add the item to batch cart with chosen quantity, then prompt next."""
    menu_item = db.get(MenuItem, menu_item_id)
    if not menu_item:
        await self.client.send_message(chat_id, "That item is no longer available.")
        return

    if session.state == "BATCH_QUANTITY_SELECTION":
        batch_cart_items = session.context.get("batch_cart_items", [])
        batch_cart_items.append({
            "menu_item_id": menu_item.id,
            "quantity": quantity,
            "extracted_name": menu_item.name,
        })
        queue = session.context.get("batch_quantity_queue", [])
        if queue and queue[0] == str(menu_item.id):
            queue = queue[1:]
        session.context = {
            **(session.context or {}),
            "batch_cart_items": batch_cart_items,
            "batch_quantity_queue": queue
        }
        db.commit()
        await _prompt_next_batch_quantity(self, db, chat_id, session)
        return

    order_items = (session.context or {}).get("order_items", [])
    order_items.append({
        "menu_item_id": menu_item.id,
        "quantity": quantity,
        "extracted_name": menu_item.name,
    })

    session.state = "WAITING_ITEM"
    if not session.hotel_id:
        session.hotel_id = menu_item.hotel_id
    session.context = {**(session.context or {}), "order_items": order_items, "pending_items": []}
    db.commit()

    await send_cart_summary(self, db, chat_id, session, f"{quantity} {menu_item.name} added to cart.")


async def handle_browsing_quantity(
    self: Any, db: Session, chat_id: int, session: UserSession, quantity: int
) -> None:
    """Handle typed quantity during BATCH_QUANTITY_SELECTION state."""
    queue = (session.context or {}).get("batch_quantity_queue", [])
    if not queue:
        session.state = "WAITING_ITEM"
        db.commit()
        await self.client.send_message(chat_id, "Send a food item or type 'show menu'.")
        return
    await handle_qty_callback(self, db, chat_id, session, int(queue[0]), quantity)


async def send_cart_summary(
    self: Any, db: Session, chat_id: int, session: UserSession, header: str = "Your Cart:", edit_message_id: int | None = None
) -> None:
    """Show current cart with action buttons."""
    order_items = (session.context or {}).get("order_items", [])
    if not order_items:
        await self.client.send_message(chat_id, "Your cart is empty.\n\nSend a food item or type 'show menu'.")
        return

    lines = [header, ""]
    total = Decimal("0")
    for oi in order_items:
        mi = db.get(MenuItem, oi.get("menu_item_id"))
        if not mi:
            continue
        qty = int(oi.get("quantity") or 1)
        lt = Decimal(mi.price) * qty
        total += lt
        lines.append(f"  {qty} {mi.name} - INR {lt:.2f}")

    lines.extend(["", f"Total: INR {total:.2f}"])

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "PLACE ORDER", "callback_data": "confirm"},
                {"text": "MODIFY", "callback_data": "modify"},
            ],
            [
                {"text": "Add More Items", "callback_data": "cart:addmore"},
                {"text": "View Menu", "callback_data": "cart:menu"},
            ],
        ]
    }
    session.state = "CONFIRMING"
    from fastapi_app.services.telegram_service import _store_single_hotel_plan
    _store_single_hotel_plan(session, order_items)
    db.commit()
    if edit_message_id:
        await self.client.edit_message_text(chat_id, edit_message_id, "\n".join(lines), keyboard)
    else:
        await self.client.send_message(chat_id, "\n".join(lines), keyboard)


async def handle_cart_callback(
    self: Any, db: Session, chat_id: int, session: UserSession, action: str, message_id: int | None = None
) -> None:
    """Handle cart action callbacks."""
    if action == "cart:addmore" or action == "cart:menu":
        if session.hotel_id:
            await send_categorized_menu(self, db, chat_id, session, edit_message_id=message_id)
        else:
            await self._send_hotel_picker(db, chat_id, session)
    elif action == "cart:view":
        await send_cart_summary(self, db, chat_id, session, edit_message_id=message_id)


def is_hotel_list_request(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    normalized = " ".join(normalized.split())
    keywords = {
        "hotel list", "show hotels", "available hotels", "which hotels",
        "select hotel", "nearby hotels", "hotels available", "list hotels",
        "show hotel list", "hotel available",
    }
    return normalized in keywords or (
        "hotel" in normalized and any(w in normalized for w in ("list", "show", "available", "which", "nearby", "select"))
    )


def is_category_filter_request(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    filter_signals = [
        "veg only", "veg menu", "non veg", "show dosa", "show biryani",
        "show drinks", "show snacks", "show pizza", "show burger",
        "i want dosa", "i want pizza", "i want biryani",
        "spicy items", "spicy food",
    ]
    if any(sig in normalized for sig in filter_signals):
        return True
    # "show <category>" pattern
    if re.search(r"\bshow\s+(dosa|biryani|pizza|burger|drinks|snacks|chinese|bread|curry|dessert|idli|sandwich)\b", normalized):
        return True
    # "veg only" / "only veg"
    if "veg" in normalized and ("only" in normalized or "menu" in normalized):
        return True
    return False
