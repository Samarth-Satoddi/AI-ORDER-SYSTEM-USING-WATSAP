import json
import logging
import re
from typing import Iterable

from fastapi_app.core.config import get_settings
from fastapi_app.schemas.ai import ExtractedItem, OrderExtraction

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are an intelligent conversational AI food ordering extractor for WhatsApp and Telegram. "
    "Understand real human conversations naturally, including casual greetings, incomplete sentences, "
    "short replies, spelling mistakes, and mixed English/Hindi/Kannada typing. Return only valid JSON. "
    "Classify intent as one of GREETING, ORDER, MENU_QUERY, BAD_MESSAGE, GOODBYE, UNKNOWN. "
    "If a message mixes a greeting with an order, classify it as ORDER and extract the food items. "
    "Ignore filler words such as hi, hello, hey, bro, buddy, please, i want, give me, make, add, order. "
    "Correct obvious food spelling variants in extracted names, such as dosaa to dosa, idly to idli, "
    "biriyani to biryani, ice creme to ice cream. "
    "For ORDER extract only food or drink items with name and quantity; use quantity null when not provided. "
    "Understand natural modification wording as the user's meaning, but still return the food names and quantities "
    "when a quantity or new item is present. "
    "For MENU_QUERY, classify menu requests like show menu, hotel menu, what items available, or Haldiram menu. "
    "For GREETING return reply: 'Hi! What would you like to order today?' "
    "For MENU_QUERY return reply: 'Here is the menu.' "
    "For BAD_MESSAGE return reply: 'Please use respectful language. I am here to help with your order.' "
    "For GOODBYE return reply: 'Thank you! Have a great day.' "
    "For UNKNOWN return reply: 'Tell me what you would like to order.' "
    "Do not invent menu items, prices, hotels, or explanations."
)

class OrderItemExtractor:
    async def extract(self, message: str) -> OrderExtraction:
        settings = get_settings()
        provider = settings.ai_provider.lower().strip()

        if provider == "openai":
            return await self._extract_openai(message)
        if provider == "gemini":
            return await self._extract_gemini(message)
        return self._extract_heuristic(message)

    async def _extract_openai(self, message: str) -> OrderExtraction:
        settings = get_settings()
        if not settings.openai_api_key:
            logger.warning("OPENAI_API_KEY is missing; falling back to heuristic extraction")
            return self._extract_heuristic(message)

        try:
            from openai import AsyncOpenAI
        except ImportError:
            logger.exception("openai package is not installed; falling back to heuristic extraction")
            return self._extract_heuristic(message)

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.responses.parse(
            model=settings.openai_model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            text_format=OrderExtraction,
        )

        for output in response.output:
            if output.type != "message":
                continue
            for item in output.content:
                parsed = getattr(item, "parsed", None)
                if parsed:
                    return parsed
        return OrderExtraction(items=[])

    async def _extract_gemini(self, message: str) -> OrderExtraction:
        settings = get_settings()
        if not settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY is missing; falling back to heuristic extraction")
            return self._extract_heuristic(message)

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            logger.exception("google-genai package is not installed; falling back to heuristic extraction")
            return self._extract_heuristic(message)

        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = f"{SYSTEM_PROMPT}\n\nCustomer message: {message}"
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=OrderExtraction.model_json_schema(),
            ),
        )
        try:
            payload = json.loads(response.text or "{}")
            return OrderExtraction.model_validate(payload)
        except (json.JSONDecodeError, ValueError):
            logger.exception("Gemini extraction response was not valid JSON")
            return OrderExtraction(items=[])

    def _extract_heuristic(self, message: str) -> OrderExtraction:
        text = message.lower().strip()
        normalized = _normalize_message(text)

        if _is_bad_message(normalized):
            return OrderExtraction(
                intent="BAD_MESSAGE",
                reply="Please use respectful language. I am here to help with your order.",
            )
        if _is_menu_query(normalized):
            return OrderExtraction(intent="MENU_QUERY", reply="Here is the menu.")
        if _is_goodbye(normalized):
            return OrderExtraction(intent="GOODBYE", reply="Thank you! Have a great day.")

        text = _normalize_food_spellings(text)
        text = re.sub(r"\b(i want|please|pls|order|give me|send me|need|can i get|i need|want|make|add|bro|buddy|yo|hii|hi|hello|hey)\b", " ", text)
        text = re.sub(r"\b(cheap option|nearest hotel|fastest|best rating|takeaway|delivery)\b", " ", text)
        text = re.sub(r"\b(good morning|good afternoon|good evening)\b", " ", text)
        text = re.sub(r"\b(from|hotel|restaurant)\b\s+[a-z0-9 '&.-]+$", " ", text)
        text = re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b", lambda m: str(_number_word(m.group())), text)
        chunks = re.split(r",|;|\band\b|\+|&|\n", text)

        items: list[ExtractedItem] = []
        for chunk in chunks:
            cleaned = re.sub(r"\b(plate|plates|piece|pieces|qty|quantity|of|a|an|the)\b", " ", chunk)
            cleaned = " ".join(cleaned.split())
            if not cleaned:
                continue

            quantity = None
            match = re.match(r"^(\d{1,2})\s+(.+)$", cleaned)
            if match:
                quantity = int(match.group(1))
                cleaned = match.group(2).strip()
            else:
                match = re.match(r"^(.+?)\s+(\d{1,2})$", cleaned)
                if match:
                    cleaned = match.group(1).strip()
                    quantity = int(match.group(2))

            if len(cleaned) >= 2 and not cleaned.isdigit():
                items.append(ExtractedItem(name=cleaned[:120], quantity=quantity))

        items = _dedupe_items(items)
        if not items or not _looks_like_order(normalized, items):
            if _is_greeting(normalized):
                return OrderExtraction(intent="GREETING", reply="Hi! What would you like to order today?")
            return OrderExtraction(
                intent="UNKNOWN",
                reply="Tell me what you would like to order.",
            )
        return OrderExtraction(intent="ORDER", items=items)


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


def _dedupe_items(items: Iterable[ExtractedItem]) -> list[ExtractedItem]:
    seen: set[str] = set()
    deduped: list[ExtractedItem] = []
    for item in items:
        key = item.name.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_message(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return " ".join(text.split())


def _normalize_food_spellings(text: str) -> str:
    replacements = {
        "dosaa": "dosa",
        "dossa": "dosa",
        "idly": "idli",
        "biriyani": "biryani",
        "briyani": "biryani",
        "ice creme": "ice cream",
        "icecream": "ice cream",
    }
    for old, new in replacements.items():
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    return text


def _is_greeting(text: str) -> bool:
    return text in {
        "hi",
        "hello",
        "hii",
        "hey",
        "yo",
        "bro",
        "hello buddy",
        "good morning",
        "good afternoon",
        "good evening",
        "namaste",
    }


def _is_menu_query(text: str) -> bool:
    menu_terms = {
        "menu",
        "show menu",
        "send menu",
        "what food available",
        "what is available",
        "food available",
        "available food",
        "items available",
        "list items",
        "hotel menu",
    }
    return text in menu_terms or "menu" in text or ("available" in text and "food" in text)


def _is_goodbye(text: str) -> bool:
    return text in {"bye", "goodbye", "see you", "see ya", "thanks bye", "thank you bye"}


def _is_bad_message(text: str) -> bool:
    abusive_words = {
        "asshole",
        "bastard",
        "bitch",
        "bloody fool",
        "fuck",
        "idiot",
        "moron",
        "shit",
        "stupid",
    }
    angry_phrases = {"i hate you", "shut up", "go away"}
    words = set(text.split())
    return any(word in words for word in abusive_words) or any(phrase in text for phrase in angry_phrases)


def _looks_like_order(text: str, items: list[ExtractedItem]) -> bool:
    if re.search(r"\b\d{1,2}\b", text):
        return True
    if re.search(r"\b(order|want|need|get|give|send|bring)\b", text):
        return True

    known_food_terms = {
        "biryani",
        "burger",
        "chapati",
        "chai",
        "coffee",
        "dosa",
        "idli",
        "juice",
        "meal",
        "noodles",
        "paratha",
        "pizza",
        "poori",
        "rice",
        "samosa",
        "tea",
        "vada",
    }
    return any(term in item.name.lower().split() for item in items for term in known_food_terms)


extractor = OrderItemExtractor()
