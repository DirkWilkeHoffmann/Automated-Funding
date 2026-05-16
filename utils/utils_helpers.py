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
        except Exception:  # pragma: no cover - defensive
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

    Example:
        https://register-of-charities.charitycommission.gov.uk/...?query=params
        becomes
        https://register-of-charities.charitycommission.gov.uk/en/charity-search/-/charity-details/1010625
    """
    url = url.strip()
    if not url:
        return url

    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower().replace("www.", "")
    path = parsed.path or "/"
    path = re.sub(r"/+$", "", path)

    # special case: Charity Commission pattern
    if "charitycommission.gov.uk" in netloc and "/charity-details/" in path:
        # keep only the ID part
        match = re.search(r"(/charity-details/\d+)", path)
        if match:
            path = "/en/charity-search/-" + match.group(1)

    normalized = f"{scheme}://{netloc}{path}"
    return normalized


def parse_extraction_timestamp(value: Any) -> Optional[datetime]:
    """Parse extraction_timestamp values from Google Sheets into datetimes."""
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
    # Handle malformed timestamps like "2025-11-20 11:33:60" by rolling
    # overflow seconds forward from the minute boundary.
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
    """
    Canonical funder URL.

    Special rule:
    - For Charity Commission register URLs:
      Must match EXACT FULL URL (after basic normalization).
    - Otherwise:
      Canonicalize to base domain only.
    """
    if not url:
        return ""

    try:
        u = normalize_url(url)
        parts = urlparse(u)
        domain = parts.netloc.lower().replace("www.", "")

        # SPECIAL CASE: Charity Commission Register
        if domain.startswith("register-of-charities.charitycommission"):
            # exact match, no simplification
            return u.rstrip("/")

        # DEFAULT: return only the domain
        return f"https://{domain}"

    except Exception:
        return url.strip().lower()


def is_charity_commission_url(url: str) -> bool:
    """Check if URL is from Charity Commission."""
    try:
        netloc = urlparse(url).netloc.lower()
    except Exception:
        return False
    return "register-of-charities.charitycommission.gov.uk" in netloc


def folder_name_for_url(u: str) -> str:
    """Get safe folder name from URL."""
    return safe_filename_from_url(normalize_url(u))
