"""Sitemap-based funding URL discovery — Phase 6.

find_funding_urls(homepage) inspects a foundation's robots.txt and sitemap
XML files to surface grant/apply/funding URLs without JavaScript rendering.

Returns URLs keyword-ranked by grant-intent signal (strongest first). An
empty list means the sitemap approach found nothing useful; callers should
then fall back to homepage link-scanning.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import defusedxml.ElementTree as ET
from urllib.parse import urljoin, urlparse

from utils.scraping import fetch_page

logger = logging.getLogger(__name__)

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_MAX_SITEMAP_URLS = 500   # don't parse giant sitemaps exhaustively
_MAX_CHILD_SITEMAPS = 3   # for sitemapindex: fetch at most this many children


def _grant_pattern():
    from utils.discovery.foundation_crawler import _GRANT_PAGE_PATTERNS
    return _GRANT_PAGE_PATTERNS


def _parse_sitemap_xml(xml_text: str) -> tuple[bool, List[str]]:
    """Parse sitemap XML. Returns (is_index, list_of_loc_urls)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False, []

    is_index = "sitemapindex" in root.tag
    locs: List[str] = []
    tag = f"{_SITEMAP_NS}sitemap" if is_index else f"{_SITEMAP_NS}url"
    for el in root.findall(tag)[:_MAX_SITEMAP_URLS]:
        loc = el.find(f"{_SITEMAP_NS}loc")
        if loc is not None and loc.text:
            locs.append(loc.text.strip())
    return is_index, locs


def _sitemap_urls_from_robots(homepage: str) -> List[str]:
    """Return Sitemap: URLs declared in /robots.txt."""
    try:
        content = fetch_page(urljoin(homepage, "/robots.txt"))
        if not content:
            return []
        return [
            line.split(":", 1)[1].strip()
            for line in content.splitlines()
            if line.lower().startswith("sitemap:")
            and "http" in line
        ]
    except Exception:
        return []


def _collect_locs(sitemap_url: str) -> List[str]:
    """Fetch a sitemap and return all page <loc> URLs.

    If it turns out to be a sitemapindex, fetches child sitemaps
    (up to _MAX_CHILD_SITEMAPS) and merges their page URLs.
    """
    content = fetch_page(sitemap_url)
    if not content or "<" not in content:
        return []

    is_index, locs = _parse_sitemap_xml(content)
    if not is_index:
        return locs

    # It's a sitemapindex — locs are child sitemap URLs
    all_locs: List[str] = []
    for child_url in locs[:_MAX_CHILD_SITEMAPS]:
        child_content = fetch_page(child_url)
        if child_content and "<" in child_content:
            _, child_locs = _parse_sitemap_xml(child_content)
            all_locs.extend(child_locs)
    return all_locs


def find_funding_urls(homepage: str) -> List[str]:
    """Return grant/funding-intent URLs discovered via sitemaps.

    Strategy:
      1. Parse /robots.txt for declared Sitemap: lines.
      2. Fall back to /sitemap.xml when robots.txt declares nothing.
      3. Collect all page <loc> URLs from the sitemap(s).
      4. Filter to same-domain URLs that match the grant-keyword pattern.
      5. Rank by number of keyword hits; return strongest-match first.

    Returns an empty list when no sitemap or no matching URLs are found.
    """
    pattern = _grant_pattern()
    base_netloc = urlparse(homepage).netloc.replace("www.", "")

    sitemap_sources = _sitemap_urls_from_robots(homepage)
    if not sitemap_sources:
        sitemap_sources = [urljoin(homepage, "/sitemap.xml")]

    all_locs: List[str] = []
    for sm_url in sitemap_sources[:3]:
        all_locs.extend(_collect_locs(sm_url))

    if not all_locs:
        return []

    scored: List[tuple[int, str]] = []
    seen: set = set()
    for url in all_locs:
        if url in seen:
            continue
        seen.add(url)
        if base_netloc not in urlparse(url).netloc:
            continue
        hits = len(pattern.findall(url))
        if hits > 0:
            scored.append((hits, url))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [url for _, url in scored]
