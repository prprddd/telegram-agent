"""Voice transcription via OpenAI Whisper."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from bot.config import get_settings

logger = logging.getLogger(__name__)


class Transcriber:
    def __init__(self) -> None:
        settings = get_settings()
        self._enabled = bool(settings.openai_api_key)
        self._model = settings.whisper_model
        self._client: Optional[AsyncOpenAI] = (
            AsyncOpenAI(api_key=settings.openai_api_key) if self._enabled else None
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def transcribe(self, audio_path: Path, language: str = "he") -> str:
        if not self._client:
            raise RuntimeError("Transcriber not configured (OPENAI_API_KEY missing)")
        with audio_path.open("rb") as f:
            resp = await self._client.audio.transcriptions.create(
                model=self._model,
                file=f,
                language=language,
                prompt=(
                    "שלום, זוהי הודעה קולית בעברית. "
                    "תזכורת, קבוצה, שלח, יומן, פגישה, אנשי קשר, "
                    "כתוב לי, תזכיר לי, מה יש לי היום, תשלח לקבוצת"
                ),
            )
        return (resp.text or "").strip()
