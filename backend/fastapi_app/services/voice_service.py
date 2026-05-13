"""Voice transcription service for Telegram voice messages."""

import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx

from fastapi_app.core.config import get_settings

logger = logging.getLogger(__name__)


async def download_telegram_voice(file_id: str) -> bytes | None:
    """Download a voice file from Telegram by file_id."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN missing; cannot download voice file")
        return None

    api_base = settings.telegram_api_base
    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: get file path from Telegram
        response = await client.post(f"{api_base}/getFile", json={"file_id": file_id})
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            logger.warning("Telegram getFile failed: %s", data)
            return None

        file_path = data["result"]["file_path"]

        # Step 2: download the actual file
        file_url = f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}"
        file_response = await client.get(file_url)
        file_response.raise_for_status()
        return file_response.content


async def transcribe_voice(audio_bytes: bytes, file_extension: str = ".ogg") -> str | None:
    """Transcribe audio bytes to text using the configured AI provider."""
    settings = get_settings()
    provider = settings.ai_provider.lower().strip()

    if provider == "openai":
        return await _transcribe_openai(audio_bytes, file_extension)
    if provider == "gemini":
        return await _transcribe_gemini(audio_bytes, file_extension)
    return _transcribe_mock(audio_bytes)


async def _transcribe_openai(audio_bytes: bytes, file_extension: str) -> str | None:
    settings = get_settings()
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY missing; cannot transcribe voice")
        return None

    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.exception("openai package not installed; cannot transcribe voice")
        return None

    # Write to a temp file because the OpenAI SDK needs a file-like object
    with tempfile.NamedTemporaryFile(suffix=file_extension, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = Path(tmp.name)

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        with open(tmp_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="en",
            )
        text = transcription.text.strip()
        logger.info("Whisper transcription: %s", text)
        return text if text else None
    except Exception:
        logger.exception("OpenAI Whisper transcription failed")
        return None
    finally:
        tmp_path.unlink(missing_ok=True)


async def _transcribe_gemini(audio_bytes: bytes, file_extension: str) -> str | None:
    settings = get_settings()
    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY missing; cannot transcribe voice")
        return None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.exception("google-genai package not installed; cannot transcribe voice")
        return None

    mime_map = {".ogg": "audio/ogg", ".oga": "audio/ogg", ".mp3": "audio/mp3", ".wav": "audio/wav"}
    mime_type = mime_map.get(file_extension, "audio/ogg")

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                types.Content(
                    parts=[
                        types.Part(
                            inline_data=types.Blob(mime_type=mime_type, data=audio_bytes)
                        ),
                        types.Part(
                            text=(
                                "Transcribe this audio message exactly. The speaker is ordering food "
                                "and may speak in English, Hindi, Kannada, or a mix. Return ONLY the "
                                "transcribed text, nothing else."
                            )
                        ),
                    ]
                )
            ],
        )
        text = (response.text or "").strip()
        logger.info("Gemini voice transcription: %s", text)
        return text if text else None
    except Exception:
        logger.exception("Gemini voice transcription failed")
        return None


def _transcribe_mock(audio_bytes: bytes) -> str | None:
    """Mock transcription for local dev without API keys."""
    logger.info("Mock voice transcription (AI_PROVIDER=mock). Returning None.")
    return None
