"""Text-to-speech via OpenAI TTS."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from bot.config import get_settings

logger = logging.getLogger(__name__)


class TTS:
    def __init__(self) -> None:
        settings = get_settings()
        self._enabled = bool(settings.openai_api_key)
        self._model = settings.tts_model
        self._voice = settings.tts_voice
        self._client: Optional[AsyncOpenAI] = (
            AsyncOpenAI(api_key=settings.openai_api_key) if self._enabled else None
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def synthesize(self, text: str, out_path: Path) -> Path:
        """Synthesize `text` and write OGG/Opus to `out_path`. Returns the path."""
        if not self._client:
            raise RuntimeError("TTS not configured (OPENAI_API_KEY missing)")
        # OGG/Opus is what Telegram voice messages use natively
        async with self._client.audio.speech.with_streaming_response.create(
            model=self._model,
            voice=self._voice,
            input=text,
            response_format="opus",
        ) as response:
            with out_path.open("wb") as f:
                async for chunk in response.iter_bytes():
                    f.write(chunk)
        return out_path
