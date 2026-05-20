"""Web scraping and HTML extraction utilities."""

import io
import logging
import re
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
_HTML_CACHE_MAX = 500
_CACHE_TTL = 86400  # 24 hours


def fetch_page(url: str, retries: int = 4, backoff_factor: int = 2) -> Optional[str]:
    """Fetch a page with exponential backoff on rate limiting. Caches responses for 24h."""
    cached = _html_cache.get(url)
    if cached:
        html, ts = cached
        if time.time() - ts < _CACHE_TTL:
            return html
        del _html_cache[url]

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

    Returns:
        (combined_text, folder_path, num_pages_visited, visited_urls, pdf_metadata)
    """
    import os

    from utils.constants import SAVE_DIR

    seed_base = initial_normalize_url(seed_url)
    seed_norm = normalize_url(seed_url)
    domain_folder = os.path.join(SAVE_DIR, safe_filename_from_url(seed_base))
    os.makedirs(domain_folder, exist_ok=True)

    candidates = discover_links(seed_norm)
    candidates.setdefault(
        seed_norm, {"anchor_texts": set(), "source_titles": set(), "source_snippets": set()}
    )
    scored = [(score_candidate(url, meta), url) for url, meta in candidates.items()]
    scored.sort(reverse=True)

    top_links = [url for _, url in scored[:MAX_PAGES]]
    log_message(f"Fetching top {len(top_links)} links from {seed_base}")

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
