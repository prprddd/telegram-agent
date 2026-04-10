"""Google Calendar client — read + write, multi-calendar support."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from bot.config import get_settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._service = None

    @property
    def configured(self) -> bool:
        return self._settings.google_credentials_file.exists()

    def _load_credentials(self) -> Credentials:
        token_path: Path = self._settings.google_token_file
        creds_path: Path = self._settings.google_credentials_file
        creds: Optional[Credentials] = None

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not creds_path.exists():
                    raise FileNotFoundError(
                        f"Google credentials file not found at {creds_path}. "
                        "See docs/setup.md for instructions."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def _ensure_service(self):
        if self._service is None:
            creds = self._load_credentials()
            self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def list_calendars(self) -> list[dict[str, Any]]:
        svc = self._ensure_service()
        result = svc.calendarList().list().execute()
        return [
            {
                "id": item["id"],
                "summary": item.get("summary", ""),
                "primary": item.get("primary", False),
                "accessRole": item.get("accessRole", ""),
            }
            for item in result.get("items", [])
        ]

    def create_event(
        self,
        calendar_id: str,
        title: str,
        start: datetime,
        end: datetime,
        description: Optional[str] = None,
        attendee_emails: Optional[list[str]] = None,
        reminder_minutes_before: int = 60,
        timezone: str = "Asia/Jerusalem",
    ) -> dict[str, Any]:
        svc = self._ensure_service()
        body: dict[str, Any] = {
            "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": reminder_minutes_before},
                ],
            },
        }
        if description:
            body["description"] = description
        if attendee_emails:
            body["attendees"] = [{"email": e} for e in attendee_emails]
        event = (
            svc.events()
            .insert(calendarId=calendar_id, body=body, sendUpdates="all" if attendee_emails else "none")
            .execute()
        )
        return event

    def list_events(
        self,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        svc = self._ensure_service()
        result = (
            svc.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min.isoformat() + "Z" if time_min.tzinfo is None else time_min.isoformat(),
                timeMax=time_max.isoformat() + "Z" if time_max.tzinfo is None else time_max.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return result.get("items", [])

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        title: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        description: Optional[str] = None,
        attendee_emails: Optional[list[str]] = None,
        timezone: str = "Asia/Jerusalem",
    ) -> dict[str, Any]:
        svc = self._ensure_service()
        existing = svc.events().get(calendarId=calendar_id, eventId=event_id).execute()
        if title is not None:
            existing["summary"] = title
        if start is not None:
            existing["start"] = {"dateTime": start.isoformat(), "timeZone": timezone}
        if end is not None:
            existing["end"] = {"dateTime": end.isoformat(), "timeZone": timezone}
        if description is not None:
            existing["description"] = description
        if attendee_emails is not None:
            existing["attendees"] = [{"email": e} for e in attendee_emails]
        updated = (
            svc.events()
            .update(calendarId=calendar_id, eventId=event_id, body=existing, sendUpdates="all" if attendee_emails else "none")
            .execute()
        )
        return updated

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        svc = self._ensure_service()
        svc.events().delete(calendarId=calendar_id, eventId=event_id).execute()
