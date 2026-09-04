"""Timezone-aware timestamps for user-visible runtime logs."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment,misc]

ARIZONA_TIMEZONE = timezone(timedelta(hours=-7), "MST")
configured = os.getenv("FABRIC_LOG_TIMEZONE", "America/Phoenix").strip()
if configured and configured != "America/Phoenix" and ZoneInfo is not None:
    try:
        LOG_TIMEZONE = ZoneInfo(configured)
    except Exception:
        LOG_TIMEZONE = ARIZONA_TIMEZONE
else:
    LOG_TIMEZONE = ARIZONA_TIMEZONE


def log_timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(LOG_TIMEZONE).isoformat()
