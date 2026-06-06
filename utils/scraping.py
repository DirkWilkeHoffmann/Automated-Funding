"""Web scraping and HTML extraction utilities."""

import io
import ipaddress
import logging
import re
import socket
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from utils.constants import (
    DISCOVERY_DEPTH,
    HEADERS,
    KEYWORDS,
    LISTING_EXCLUDED_DOMAINS,
    LISTING_GRANT_LINK_KEYWORDS,
    LISTING_SIGNAL_THRESHOLD,
    LISTING_TITLE_KEYWORDS,
    LISTING_URL_KEYWORDS,
    MAX_DISCOVERY_PAGES,
    MAX_PAGES,
    PAUSE_BETWEEN_REQUESTS,
)
from utils.utils_helpers import (
    initial_normalize_url,
    log_message,
    normalize_url,
    safe_filename_from_url,
)

logger = logging.getLogger(__name__)

_html_cache: "OrderedDict[str, Tuple[str, float]]" = OrderedDict()


def _is_safe_url(url: str) -> bool:
    """Return True only when the URL is safe to fetch.

    Blocks loopback, private, link-local, reserved, and unspecified addresses
    to prevent SSRF attacks (e.g. probing 127.0.0.1, 169.254.169.254, 10.x,
    192.168.x, fd00::, etc.).  Only http/https schemes are allowed.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").rstrip(".").lower()
        if not host:
            return False
        try:
            addrinfos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        for info in addrinfos:
            addr_str = info[4][0]
            try:
                ip = ipaddress.ip_address(addr_str)
                if (
                    ip.is_loopback
                    or ip.is_private
                    or ip.is_link_local
                    or ip.is_reserved
                    or ip.is_unspecified
                    or ip.is_multicast
                ):
                    log_message(f"SSRF guard: blocked {url} → {ip}", "warning")
                    return False
            except ValueError:
                return False
        return True
    except Exception:
        return False
_HTML_CACHE_MAX = 500
_CACHE_TTL = 86400  # 24 hours


def fetch_page(url: str, retries: int = 4, backoff_factor: int = 2) -> Optional[str]:
    """Fetch a page with exponential backoff on rate limiting. Caches responses for 24h."""
    if not _is_safe_url(url):
        log_message(f"fetch_page: refused to fetch unsafe URL: {url}", "warning")
        return None
    cached = _html_cache.get(url)
    if cached:
        html, ts = cached
        if time.time() - ts < _CACHE_TTL:
            return html
        _html_cache.pop(url, None)

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", (backoff_factor**attempt) * 5))
                log_message(f"Rate limited ({resp.status_code}) – pausing {wait}s", "warning")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            html = resp.text
            if len(_html_cache) >= _HTML_CACHE_MAX:
                _html_cache.popitem(last=False)
            _html_cache[url] = (html, time.time())
            return html
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                pause = (backoff_factor**attempt) * 2
                log_message(f"Fetch failed: {url} ({e}); retrying in {pause}s", "warning")
                time.sleep(pause)
            else:
                log_message(f"Fetch failed for {url}: {e}", "error")
    return None


def extract_visible_text(html: str) -> str:
    """Extract visible text from HTML, removing scripts, styles, and navigation."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "footer", "nav", "form", "header"]):
        tag.decompose()
    text = " ".join(
        t.get_text(" ", strip=True)
        for t in soup.find_all(["h1", "h2", "h3", "p", "li", "td", "th"])
    )
    return re.sub(r"\s+", " ", text).strip()


def download_and_extract_pdf_text(url: str, *, max_chars: int = 20000) -> Dict[str, Any]:
    """Download and extract text from a PDF file."""
    try:
        from PyPDF2 import PdfReader
    except Exception as exc:
        return {"success": False, "error": f"PyPDF2 not available: {exc}"}

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        pdf_file = io.BytesIO(response.content)
        pdf_reader = PdfReader(pdf_file)

        text_parts: List[str] = []
        for page in pdf_reader.pages:
            page_text = page.extract_text() or ""
            if page_text:
                text_parts.append(page_text)

        full_text = "\n".join(text_parts).strip()
        if max_chars and len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "\n...[pdf text truncated]..."

        return {
            "success": True,
            "text": full_text,
            "num_pages": len(pdf_reader.pages),
            "file_size": len(response.content),
        }
    except requests.exceptions.RequestException as exc:
        return {"success": False, "error": f"Download error: {exc}"}
    except Exception as exc:
        return {"success": False, "error": f"PDF processing error: {exc}"}


def discover_links(
    seed_url: str, discovery_depth: int = DISCOVERY_DEPTH, max_pages: int = MAX_DISCOVERY_PAGES
) -> Dict[str, Dict[str, Any]]:
    """
    Crawl only pages related to the same base domain and seed path.
    Returns a dict of discovered links with metadata.
    """
    seed_base = initial_normalize_url(seed_url)
    seed_norm = normalize_url(seed_url)
    base_domain = urlparse(seed_norm).netloc.replace("www.", "")
    queue = [(seed_norm, 0)]
    visited, candidates = set(), {}
    pages_visited = 0

    while queue:
        url, depth = queue.pop(0)
        if url in visited or depth > discovery_depth or pages_visited >= max_pages:
            continue
        visited.add(url)
        pages_visited += 1

        html = fetch_page(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        snippet = ""
        if p := soup.find("p"):
            snippet = p.get_text(" ", strip=True)[:300]

        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"].split("#")[0])
            if not href.startswith("http"):
                continue
            parsed_href = urlparse(href)
            if base_domain not in parsed_href.netloc:
                continue
            if any(
                href.lower().endswith(ext)
                for ext in [".pdf", ".jpg", ".jpeg", ".png", ".zip", ".mp4", ".doc", ".docx"]
            ):
                continue

            hnorm = normalize_url(href)
            anchor = (a.get_text(" ", strip=True) or "").strip()
            meta = candidates.setdefault(
                hnorm, {"anchor_texts": set(), "source_titles": set(), "source_snippets": set()}
            )
            if anchor:
                meta["anchor_texts"].add(anchor)
            if title:
                meta["source_titles"].add(title)
            if snippet:
                meta["source_snippets"].add(snippet)
            if hnorm not in visited and depth + 1 <= discovery_depth:
                queue.append((hnorm, depth + 1))

        time.sleep(PAUSE_BETWEEN_REQUESTS)

    log_message(
        f"Found {len(candidates)} internal links (visited {pages_visited} pages) from {seed_base}"
    )
    return candidates


def score_candidate(url: str, meta: Dict[str, Any]) -> int:
    """Score a candidate URL based on keywords and URL characteristics."""
    score = 0
    u = url.lower()
    for kw in KEYWORDS:
        if kw in u:
            score += 50
    for a in meta.get("anchor_texts", []):
        if any(kw in a.lower() for kw in KEYWORDS):
            score += 25
    for t in meta.get("source_titles", []):
        if any(kw in t.lower() for kw in KEYWORDS):
            score += 10
    for s in meta.get("source_snippets", []):
        if any(kw in s.lower() for kw in KEYWORDS):
            score += 7
    depth_penalty = len(urlparse(url).path.strip("/").split("/")) - 3
    score -= max(0, depth_penalty) * 3
    score += max(0, 10 - len(url) / 50)
    return score


def prioritized_crawl(seed_url: str) -> Tuple[str, str, int, List[str], Dict[str, Any]]:
    """
    Crawl and prioritize the most relevant internal pages for a seed URL.

    PATH-PREFIX RULE (2026-05-31 fix):
      Only follow links whose URL path is the seed itself or a SUB-path of
      the seed. This prevents a critical bug on aggregator sites like
      fundsforngos.org where every "/{category}/{slug}" sibling page outscored
      the seed (because all the URL slugs contain grant keywords) and got
      concatenated into the LLM's input, polluting field extraction (deadlines,
      amounts, etc. would be from sibling grants, not the seed).

    SEED-FIRST RULE:
      The seed URL is ALWAYS fetched first, unconditionally. Previously the
      seed could be bumped out of the top-N by higher-scoring siblings.

    Returns:
        (combined_text, folder_path, num_pages_visited, visited_urls, pdf_metadata)
    """
    import os

    from utils.constants import SAVE_DIR

    seed_base = initial_normalize_url(seed_url)
    seed_norm = normalize_url(seed_url)
    domain_folder = os.path.join(SAVE_DIR, safe_filename_from_url(seed_base))
    os.makedirs(domain_folder, exist_ok=True)

    seed_path = urlparse(seed_norm).path.rstrip("/")

    def _is_sub_path(candidate_url: str) -> bool:
        """True if candidate's path is the seed path or a sub-path of it.

        Examples (seed = /education/apply-for-da-young-leaders):
          /education/apply-for-da-young-leaders/         → True (same)
          /education/apply-for-da-young-leaders/guidelines → True (sub)
          /education/apply-for-da-young-leaders-OTHER    → False (sibling at same depth)
          /individuals/apply-for-henry-moore             → False (different branch)
          /                                              → False
        """
        if not seed_path:
            # Seed is a root URL — only the seed itself matches the rule.
            return candidate_url == seed_norm
        cand_path = urlparse(candidate_url).path.rstrip("/")
        if cand_path == seed_path:
            return True
        # Sub-path must START with seed_path followed by "/" (so we don't
        # accept "/foo-other" as a sub of "/foo").
        return cand_path.startswith(seed_path + "/")

    candidates = discover_links(seed_norm)

    # Apply the path-prefix filter. The seed itself is always re-added so it
    # survives even if discover_links produced an empty set.
    candidates = {url: meta for url, meta in candidates.items() if _is_sub_path(url)}
    candidates.setdefault(
        seed_norm, {"anchor_texts": set(), "source_titles": set(), "source_snippets": set()}
    )

    scored = [(score_candidate(url, meta), url) for url, meta in candidates.items()]
    scored.sort(reverse=True)

    # Build fetch order: seed FIRST, then top-scored sub-paths up to MAX_PAGES.
    ordered: List[str] = [seed_norm]
    for _, url in scored:
        if url != seed_norm and url not in ordered:
            ordered.append(url)
    top_links = ordered[:MAX_PAGES]
    log_message(
        f"Fetching {len(top_links)} page(s) from {seed_base} "
        f"(seed first, sub-paths only, dropped {len(scored) - len(top_links) + (0 if seed_norm in [u for _, u in scored] else 1)} sibling candidates)"
    )

    visited_urls: List[str] = []
    seen_urls: set = set()
    for url in top_links:
        if url in seen_urls:
            continue
        visited_urls.append(url)
        seen_urls.add(url)

    pdf_meta: Dict[str, Any] = {"pdf_read": False, "pdf_url": "", "pdf_pages": 0, "pdf_text": ""}
    all_text = []
    for i, url in enumerate(top_links, 1):
        log_message(f"  ({i}/{len(top_links)}) {url}")
        html = fetch_page(url)
        if not html:
            continue
        text = extract_visible_text(html)
        all_text.append(text)
        fname = safe_filename_from_url(url) + ".txt"
        with open(os.path.join(domain_folder, fname), "w", encoding="utf-8") as f:
            f.write(text)
        time.sleep(PAUSE_BETWEEN_REQUESTS)

    combined_text = " ".join(all_text)
    return combined_text, domain_folder, len(all_text), visited_urls, pdf_meta


def detect_listing_page(url: str, text: str) -> bool:
    """Return True when the page looks like an aggregator/listing of multiple grants.

    Fires on ≥LISTING_SIGNAL_THRESHOLD of five heuristic signals so that a single
    keyword hit doesn't wrongly classify a real grant detail page.
    """
    signals = 0
    url_lower = url.lower()
    text_lower = text.lower()

    # 1. URL-path pattern
    if any(kw in url_lower for kw in LISTING_URL_KEYWORDS):
        signals += 1

    # 2. Title / early content contains listing-indicator phrase
    if any(kw in text_lower[:800] for kw in LISTING_TITLE_KEYWORDS):
        signals += 1

    # 3. Deadline density — ≥3 separate mentions
    if text_lower.count("deadline") >= 3:
        signals += 1

    # 4. Apply / read-more density
    if text_lower.count("apply now") + text_lower.count("read more") >= 3:
        signals += 1

    # 5. Currency-amount density — ≥5 separate amounts suggests many grants
    if len(re.findall(r'[\$£€]\s*[\d,]+|\bUSD\s*[\d,]+|\bZAR\s*[\d,]+', text)) >= 5:
        signals += 1

    return signals >= LISTING_SIGNAL_THRESHOLD


def extract_listing_urls(seed_url: str, max_results: int = 60) -> List[Dict[str, str]]:
    """Extract individual grant-opportunity URLs from a listing/aggregator page.

    Parses both same-domain AND external links from the page HTML — listing pages
    often link out to actual funder websites. Returns a list of
    ``{"url": str, "title": str}`` dicts, capped at *max_results*.
    """
    html = fetch_page(seed_url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    seed_parsed = urlparse(seed_url)
    seed_domain = seed_parsed.netloc.replace("www.", "")
    seed_norm = normalize_url(seed_url)

    _EXCLUDE_PATH_FRAGMENTS = {"/category/", "/tag/", "/author/", "/archive/", "/page/"}

    candidates: List[Dict[str, str]] = []
    seen: set = set()

    for a in soup.find_all("a", href=True):
        raw_href = (a.get("href") or "").strip()
        if not raw_href or raw_href.startswith("#") or raw_href.startswith("javascript:") or raw_href.startswith("mailto:"):
            continue

        full_url = urljoin(seed_url, raw_href)
        if not full_url.startswith("http"):
            continue

        parsed = urlparse(full_url)
        link_domain = parsed.netloc.replace("www.", "")
        path = parsed.path.lower()

        # Skip social / analytics domains
        if any(excl in link_domain for excl in LISTING_EXCLUDED_DOMAINS):
            continue

        # Skip the seed URL itself
        norm = normalize_url(full_url)
        if norm == seed_norm or norm in seen:
            continue

        # Skip file downloads
        if any(path.endswith(ext) for ext in (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".doc", ".docx")):
            continue

        anchor = (a.get_text(" ", strip=True) or "").strip()
        combined = (anchor + " " + path).lower()
        has_grant_kw = any(kw in combined for kw in LISTING_GRANT_LINK_KEYWORDS)

        is_same_domain = seed_domain in link_domain
        is_external = not is_same_domain
        path_depth = len([p for p in path.split("/") if p])

        # Same-domain links: include if depth ≥ 2 and not an archive/category path
        if is_same_domain:
            if path_depth >= 2 and not any(frag in path for frag in _EXCLUDE_PATH_FRAGMENTS):
                seen.add(norm)
                title = anchor or path.rstrip("/").split("/")[-1].replace("-", " ").title() or full_url
                candidates.append({"url": full_url, "title": title[:120]})

        # External links: only include when anchor text / URL signals a grant
        elif is_external and has_grant_kw:
            seen.add(norm)
            title = anchor or link_domain
            candidates.append({"url": full_url, "title": title[:120]})

        if len(candidates) >= max_results:
            break

    log_message(f"extract_listing_urls: found {len(candidates)} candidate URLs from {seed_url}")
    return candidates
