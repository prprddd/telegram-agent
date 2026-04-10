"""Configuration loaded from environment variables (.env)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram Bot
    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_owner_id: int = Field(..., alias="TELEGRAM_OWNER_ID")

    # Anthropic
    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-sonnet-4-6", alias="ANTHROPIC_MODEL")

    # OpenAI / Whisper / TTS
    openai_api_key: Optional[str] = Field(None, alias="OPENAI_API_KEY")
    whisper_model: str = Field("whisper-1", alias="WHISPER_MODEL")
    tts_model: str = Field("tts-1", alias="TTS_MODEL")
    tts_voice: str = Field("nova", alias="TTS_VOICE")

    # Google Calendar
    google_credentials_file: Path = Field(
        Path("./data/google_credentials.json"), alias="GOOGLE_CREDENTIALS_FILE"
    )
    google_token_file: Path = Field(
        Path("./data/google_token.json"), alias="GOOGLE_TOKEN_FILE"
    )
    google_default_calendar: str = Field("primary", alias="GOOGLE_DEFAULT_CALENDAR")

    # Userbot
    telegram_api_id: Optional[int] = Field(None, alias="TELEGRAM_API_ID")
    telegram_api_hash: Optional[str] = Field(None, alias="TELEGRAM_API_HASH")
    telethon_session_name: str = Field("userbot", alias="TELETHON_SESSION_NAME")
    userbot_other_folder: str = Field("שאר הצ'אטים", alias="USERBOT_OTHER_FOLDER")
    userbot_scan_time: str = Field("03:00", alias="USERBOT_SCAN_TIME")

    # General
    timezone: str = Field("Asia/Jerusalem", alias="TIMEZONE")
    database_path: Path = Field(Path("./data/agent.db"), alias="DATABASE_PATH")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    bot_name: str = Field("העוזר", alias="BOT_NAME")

    @field_validator(
        "openai_api_key",
        "telegram_api_id",
        "telegram_api_hash",
        mode="before",
    )
    @classmethod
    def _empty_str_to_none(cls, v):
        """Treat empty strings in .env as None for optional fields."""
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
        # Ensure data directory exists
        _settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return _settings
