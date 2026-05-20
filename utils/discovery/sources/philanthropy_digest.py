"""Philanthropy News Digest RFP/Grants RSS feed parser.

Fetches https://philanthropynewsdigest.org/rfps.rss (no API key required).
Each RSS entry is a new grant announcement with a direct link to the listing.
Filters to entries published since `since_date` so each run only surfaces new ones.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from xml.etree import ElementTree

import requests

logger = logging.getLogger(__name__)

_PND_RSS_URL = "https://philanthropynewsdigest.org/rfps.rss"
_HEADERS = {"User-Agent": "automated-funding-bot/1.0", "Accept": "application/rss+xml, application/xml"}


def fetch_pnd_grant_urls(*, since_date: Optional[str] = None) -> List[str]:
    """
    Fetch grant listing URLs from the PND RFP RSS feed.

    Args:
        since_date: ISO date string (YYYY-MM-DD). Only return entries published on or after
                    this date. If None, returns all entries in the feed (typically ~30).

    Returns:
        List of grant listing URLs.
    """
    cutoff: Optional[date] = None
    if since_date:
        try:
            cutoff = date.fromisoformat(since_date)
        except ValueError:
            logger.warning("Invalid since_date %r — ignoring date filter", since_date)

    try:
        resp = requests.get(_PND_RSS_URL, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        xml_text = resp.text
    except Exception as exc:
        logger.warning("Could not fetch PND RSS feed: %s", exc)
        return []

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        logger.warning("Could not parse PND RSS XML: %s", exc)
        return []

    urls: List[str] = []
    # RSS 2.0: rss > channel > item
    for item in root.iter("item"):
        link_el = item.find("link")
        pub_el = item.find("pubDate")

        url = (link_el.text or "").strip() if link_el is not None else ""
        if not url:
            continue

        if cutoff and pub_el is not None and pub_el.text:
            try:
                pub_dt = parsedate_to_datetime(pub_el.text.strip())
                pub_date = pub_dt.astimezone(timezone.utc).date()
                if pub_date < cutoff:
                    continue
            except Exception:
                pass  # if we can't parse the date, include the entry

        urls.append(url)

    logger.info("PND RSS: %d entries (since %s)", len(urls), since_date or "all")
    return urls
