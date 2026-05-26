"""Philanthropy News Digest RFP/Grants source — historical.

NOTE: As of 2026, philanthropynewsdigest.org has been folded into Candid
(https://candid.org/candid-search/find-nonprofit-funding/) and the rfps.rss
feed no longer exists — requests to it 301-redirect to a Candid HTML search
page. The fetcher detects this and returns an empty list with a clear log
message instead of crashing on malformed XML.

The source is kept (rather than deleted) so existing run history that
references it still renders, and so we can re-enable it if Candid surfaces
an equivalent RSS/JSON feed in the future. The replacement source for
"timely grant announcements" is utils/discovery/sources/usaspending.py.
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
    """Attempt to fetch the (now-defunct) PND RFP RSS feed.

    Returns an empty list when the feed redirects to Candid (the modern home),
    when XML parsing fails, or on any network error. Always logs a one-line
    diagnostic so operators can see what happened in run history.
    """
    cutoff: Optional[date] = None
    if since_date:
        try:
            cutoff = date.fromisoformat(since_date)
        except ValueError:
            logger.warning("Invalid since_date %r — ignoring date filter", since_date)

    try:
        # allow_redirects=False so we can detect the Candid handover explicitly
        resp = requests.get(
            _PND_RSS_URL, headers=_HEADERS, timeout=20, allow_redirects=False
        )
    except Exception as exc:
        logger.info("PND RSS unreachable (likely defunct): %s", exc)
        return []

    if resp.status_code in (301, 302, 303, 307, 308):
        target = resp.headers.get("Location", "")
        logger.info(
            "PND RSS is gone — feed now redirects to %s. "
            "Discovery skips this source; consider enabling USAspending.gov instead.",
            target,
        )
        return []

    if resp.status_code != 200:
        logger.info("PND RSS returned HTTP %s — treating as empty.", resp.status_code)
        return []

    content_type = (resp.headers.get("Content-Type") or "").lower()
    if "xml" not in content_type and "rss" not in content_type:
        logger.info(
            "PND RSS returned %s (not XML) — feed appears defunct, treating as empty.",
            content_type or "unknown content-type",
        )
        return []

    try:
        root = ElementTree.fromstring(resp.text)
    except ElementTree.ParseError as exc:
        logger.info("PND RSS body is not well-formed XML: %s — treating as empty.", exc)
        return []

    urls: List[str] = []
    for item in root.iter("item"):
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        url = (link_el.text or "").strip() if link_el is not None else ""
        if not url:
            continue
        if cutoff and pub_el is not None and pub_el.text:
            try:
                pub_dt = parsedate_to_datetime(pub_el.text.strip())
                if pub_dt.astimezone(timezone.utc).date() < cutoff:
                    continue
            except Exception:
                pass
        urls.append(url)

    logger.info("PND RSS: %d entries (since %s)", len(urls), since_date or "all")
    return urls
