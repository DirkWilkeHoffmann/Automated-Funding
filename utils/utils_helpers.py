"""Utility helpers for URL handling, timestamps, and logging."""

import logging
import re
from calendar import monthrange
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from utils.config import get_settings

logger = logging.getLogger(__name__)


def log_message(message: str, level: str = "info") -> None:
    """Write to the configured callback and fall back to logging."""
    settings = get_settings()
    callback = settings.log_callback
    if callback:
        try:
            callback(level, message)
            return
        except Exception:
            logger.exception("Log callback failed")

    log_fn = getattr(logger, level, None)
    if callable(log_fn):
        log_fn(message)
    else:
        logger.info("%s", message)


def safe_filename_from_url(url: str) -> str:
    """Convert a URL to a safe filename."""
    parsed = urlparse(url)
    name = parsed.netloc + parsed.path
    name = name.strip("/").replace("/", "_")
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    return name[:150]


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication within one domain."""
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc
    path = parsed.path.rstrip("/")
    qs = ("?" + parsed.query) if parsed.query else ""
    return f"{scheme}://{netloc}{path}{qs}"


def initial_normalize_url(url: str) -> str:
    """
    For initial seed URLs (user-provided), produce a base link to restrict crawling.
    Strips query params so the crawl stays within the funder's own content tree.
    """
    url = url.strip()
    if not url:
        return url

    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower().replace("www.", "")
    path = parsed.path or "/"
    path = re.sub(r"/+$", "", path)

    return f"{scheme}://{netloc}{path}"


def parse_extraction_timestamp(value: Any) -> Optional[datetime]:
    """Parse extraction_timestamp values into datetimes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    cleaned = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    # Handle malformed timestamps like "2025-11-20 11:33:60" by rolling overflow seconds forward.
    overflow_match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2}):(\d+)", text)
    if overflow_match:
        date_part, hour_part, minute_part, second_part = overflow_match.groups()
        try:
            base = datetime.strptime(
                f"{date_part} {hour_part}:{minute_part}:00", "%Y-%m-%d %H:%M:%S"
            )
            return base + timedelta(seconds=int(second_part))
        except ValueError:
            return None
    return None


def subtract_months(source: datetime, months: int) -> datetime:
    """Subtract whole calendar months from a datetime."""
    if months <= 0:
        return source
    year = source.year
    month = source.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(source.day, monthrange(year, month)[1])
    return source.replace(year=year, month=month, day=day)


def canon_funder_url(url: str) -> str:
    """Canonical funder URL — returns the base domain."""
    if not url:
        return ""
    try:
        u = normalize_url(url)
        domain = urlparse(u).netloc.lower().replace("www.", "")
        return f"https://{domain}"
    except Exception:
        return url.strip().lower()


def folder_name_for_url(u: str) -> str:
    """Get safe folder name from URL."""
    return safe_filename_from_url(normalize_url(u))
