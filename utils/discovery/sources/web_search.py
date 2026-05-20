"""Web search source for grant discovery.

Primary: Brave Search API (https://brave.com/search/api — free tier: 2000 queries/month).
         Store the key in api_tokens under service="brave_search".
Fallback: DuckDuckGo HTML scraping (no key required, rate-limited).

Rotates through 5 targeted search queries across runs using query_idx from discovery_state.
"""

from __future__ import annotations

import logging
import re
import time
from typing import List, Optional, Tuple
from urllib.parse import unquote, urlparse

import requests

logger = logging.getLogger(__name__)

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS_DDG = {
    "User-Agent": "Mozilla/5.0 (compatible; automated-funding-bot/1.0)",
    "Accept": "text/html",
}

_EXCLUDE_DOMAINS = frozenset({
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "linkedin.com", "reddit.com", "wikipedia.org", "nytimes.com",
    "washingtonpost.com", "forbes.com", "bloomberg.com", "huffpost.com",
    "medium.com", "substack.com", "quora.com", "indeed.com", "glassdoor.com",
    "salary.com", "yelp.com", "amazon.com", "ebay.com", "eventbrite.com",
    "meetup.com", "zoom.us", "wordpress.com",
})

_GRANT_SIGNAL = re.compile(
    r"grant|fund|rfp|opportunit|apply|award|deadline|fellowship|scholarship"
    r"|philanthrop|nonprofit|501c3",
    re.IGNORECASE,
)


def _is_useful(url: str) -> bool:
    """True if the URL looks like a grant-relevant page worth scraping."""
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        if not host:
            return False
        for excl in _EXCLUDE_DOMAINS:
            if host == excl or host.endswith("." + excl):
                return False
        # .gov and .edu are inherently useful
        if host.endswith(".gov") or host.endswith(".edu"):
            return True
        return bool(_GRANT_SIGNAL.search(url))
    except Exception:
        return False


def build_queries(keywords: str, org_state: Optional[str] = None) -> List[str]:
    """Return 5 targeted grant-search queries derived from org keywords."""
    base = keywords.strip() or "nonprofit grants"
    loc = f" {org_state}" if org_state else ""
    return [
        f"{base} grants 2026 open applications nonprofit{loc}",
        f"{base} foundation grants 501c3 RFP deadline{loc}",
        f"{base} grant opportunities apply 2026{loc}",
        f"{base} grants funding available nonprofit{loc} site:.org",
        f"{base} grants 2026 site:.gov OR site:.org",
    ]


def _brave_search(query: str, api_key: str, count: int = 20) -> List[str]:
    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
        "User-Agent": "automated-funding-bot/1.0",
    }
    params = {"q": query, "count": min(count, 20), "search_lang": "en", "result_filter": "web"}
    try:
        resp = requests.get(_BRAVE_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return [r["url"] for r in (data.get("web") or {}).get("results") or [] if r.get("url")]
    except Exception as exc:
        logger.warning("Brave Search API error for %r: %s", query, exc)
        return []


def _ddg_search(query: str) -> List[str]:
    try:
        resp = requests.post(
            _DDG_URL,
            data={"q": query, "b": "", "kl": "us-en"},
            headers=_HEADERS_DDG,
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("DuckDuckGo search error for %r: %s", query, exc)
        return []

    raw = re.findall(r'class="result__a"[^>]*href="([^"]+)"', resp.text)
    urls = []
    for u in raw:
        if u.startswith("http"):
            urls.append(u)
        elif "uddg=" in u:
            m = re.search(r"uddg=([^&]+)", u)
            if m:
                urls.append(unquote(m.group(1)))
    return urls


def search_web_for_grants(
    *,
    keywords: str,
    brave_api_key: Optional[str] = None,
    query_idx: int = 0,
    org_state: Optional[str] = None,
    results_per_query: int = 20,
) -> Tuple[List[str], int]:
    """
    Run one search query (selected by query_idx) and return (urls, next_query_idx).

    Returns useful grant-relevant URLs and the updated query_idx for the next run.
    """
    queries = build_queries(keywords, org_state)
    query = queries[query_idx % len(queries)]
    next_idx = (query_idx + 1) % len(queries)

    if not brave_api_key:
        logger.info("Web search: no Brave Search API key — skipping (add key in Admin → API Keys)")
        return [], next_idx

    logger.info("Web search [Brave] query #%d: %r", query_idx, query)
    raw = _brave_search(query, brave_api_key, count=results_per_query)
    useful = [u for u in raw if _is_useful(u)]
    logger.info("Web search: %d/%d URLs passed relevance filter", len(useful), len(raw))
    return useful, next_idx
