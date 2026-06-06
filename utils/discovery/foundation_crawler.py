"""Foundation /grants page detector — Phase 3 of the auto-discovery rebuild.

Foundations are different from RFPs: the URL is a *foundation homepage*, not
the grant itself. The actual "how to apply" content lives at sub-pages like
/grants, /apply, /funding-opportunities — and a non-trivial fraction of
foundations don't accept unsolicited proposals at all.

This module finds the grant-application page on a foundation website using a
two-phase strategy:

  Phase A — Keyword scoring on URL + anchor text. Cheap, deterministic,
            handles ~90% of standard foundation websites. No LLM cost.

  Phase B — Fallback LLM classifier on the link list. Only invoked when
            Phase A returns zero candidates (i.e. the foundation uses
            non-standard nav language like "Our Approach" / "Partner With Us").
            One cheap gpt-4o-mini call per foundation.

Returns None when both phases come up empty → the orchestrator drops the
foundation as "no application page detectable", marks
`discovery_funders.no_grants_page = true`, and never bothers with it again.

This module is called from the rebuilt foundation pipeline in
`utils/discovery/sources/registry.py` (ProPublicaSource and IRS_BMF_Source).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from utils.scraping import fetch_page

logger = logging.getLogger(__name__)

# ── Tuning constants ─────────────────────────────────────────────────────────

# Regex for URL/anchor patterns that indicate a grant-application page.
# Word boundaries prevent false matches like "ingrants" (in "engineering").
# Ordering doesn't affect correctness; conceptually grouped by signal strength.
_GRANT_PAGE_PATTERNS = re.compile(
    r"\b("
    r"grants?|grant-?making|grantmaker|"
    r"apply|application|applying|how-?to-?apply|"
    r"funding|funding-?opportunit(?:y|ies)|"
    r"rfps?|request-?for-?proposals?|"
    r"proposals?|loi|letter-?of-?inquiry|loi-?process|"
    r"guidelines|guidance|criteria|eligibility|"
    r"for-?applicants|for-?nonprofits|"
    r"how-?we-?fund|what-?we-?fund|how-?we-?give|"
    r"opportunit(?:y|ies)|programs?-?and-?initiatives?"
    r")\b",
    re.IGNORECASE,
)

# URL extensions / segments to skip outright (assets, archives, social, etc.)
_SKIP_URL_PATTERNS = re.compile(
    r"\.(?:pdf|jpg|jpeg|png|gif|svg|zip|mp4|mp3|doc|docx)$|"
    r"/wp-content/|/wp-admin/|/blog/|/news/|/press/|/events?/|/calendar/|"
    r"/staff/|/board/|/team/|/about/|/contact/|"
    r"facebook\.com|twitter\.com|linkedin\.com|youtube\.com|instagram\.com",
    re.IGNORECASE,
)

# Anchor text patterns we *demote* — high false-positive rate.
_DEMOTE_PATTERNS = re.compile(
    r"\b(news|article|story|stories|blog|press|annual report|impact report)\b",
    re.IGNORECASE,
)

_PHASE_A_MIN_SCORE = 8        # below this, Phase A says "no confident hit"
_PHASE_A_KEEP_TOP_N = 3       # how many candidates Phase A returns to the orchestrator
_LLM_MAX_LINKS = 30           # cap on links sent to gpt-4o-mini in Phase B
_LLM_MAX_ANCHOR_LEN = 80      # truncate noisy anchor text before sending


# ── Phase A — keyword scoring ────────────────────────────────────────────────


def _score_link(url: str, anchor: str) -> int:
    """Higher = more likely a grant-application page."""
    score = 0
    u = url.lower()
    a = (anchor or "").lower().strip()

    # Direct URL match — strongest signal
    if _GRANT_PAGE_PATTERNS.search(u):
        score += 10

    # Anchor text match
    if a and _GRANT_PAGE_PATTERNS.search(a):
        score += 6

    # Strong bonus for "apply" or "guidelines" specifically (precision-skewed)
    if re.search(r"\b(apply|application|guidelines|grant\s*application)\b", a, re.IGNORECASE):
        score += 4
    if re.search(r"/(apply|guidelines|grant-application)", u):
        score += 4

    # Short URLs are usually navigation; long URLs are usually leaf articles
    path = urlparse(url).path.strip("/")
    segs = path.split("/") if path else []
    if len(segs) > 0:
        score += max(0, 4 - max(0, len(segs) - 2))
    # Reduce score for very deep paths
    score -= max(0, len(segs) - 4) * 2

    # Demote news / blog / about
    if _DEMOTE_PATTERNS.search(u) or _DEMOTE_PATTERNS.search(a):
        score -= 6

    return score


def _extract_links(html: str, base_url: str) -> Dict[str, str]:
    """Return {abs_url: best_anchor_text} for all internal links on the page."""
    soup = BeautifulSoup(html, "html.parser")
    base_netloc = urlparse(base_url).netloc.replace("www.", "")

    out: Dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].split("#")[0].strip()
        if not href:
            continue
        abs_url = urljoin(base_url, href)
        if not abs_url.startswith("http"):
            continue
        parsed = urlparse(abs_url)
        if base_netloc not in parsed.netloc:
            continue  # off-site, skip
        if _SKIP_URL_PATTERNS.search(abs_url):
            continue
        anchor = (a.get_text(" ", strip=True) or "")[:_LLM_MAX_ANCHOR_LEN]
        # Prefer the most informative anchor text we've seen for a given URL
        existing = out.get(abs_url, "")
        if len(anchor) > len(existing):
            out[abs_url] = anchor
    return out


def _phase_a_candidates(links: Dict[str, str]) -> List[Tuple[str, str, int]]:
    """Return scored, sorted candidates from Phase A keyword scoring."""
    scored = [(url, anchor, _score_link(url, anchor)) for url, anchor in links.items()]
    scored = [t for t in scored if t[2] >= _PHASE_A_MIN_SCORE]
    scored.sort(key=lambda t: t[2], reverse=True)
    return scored[:_PHASE_A_KEEP_TOP_N]


# ── Phase B — LLM classifier fallback ────────────────────────────────────────


_LLM_SYSTEM = (
    "You identify which links on a foundation's website lead to a grant "
    "application page. Reply with strict JSON only. Be conservative — only "
    "include links that clearly describe how to apply for a grant, not news, "
    "blog posts, or general 'about us' pages."
)


def _phase_b_candidates(
    foundation_homepage: str, links: Dict[str, str]
) -> List[str]:
    """Send link list to gpt-4o-mini, return candidate URLs."""
    from utils.llm_utils import get_client

    client = get_client()
    if client is None:
        return []

    sample_items = list(links.items())[:_LLM_MAX_LINKS]
    if not sample_items:
        return []

    link_lines = [f"{i+1}. URL={u} | anchor={a or '(empty)'}" for i, (u, a) in enumerate(sample_items)]
    user_prompt = (
        f"Foundation homepage: {foundation_homepage}\n\n"
        "Below are internal links on this foundation's website. Pick the URLs "
        "that would lead a visitor to information about how to apply for a "
        "grant from this foundation. Examples of valid targets: a 'Grants' "
        "overview page, an 'Apply Now' page, a 'Funding Guidelines' page, an "
        "'RFP' or 'Letter of Inquiry' page. Skip news, blog, events, board "
        "biographies, and general about pages.\n\n"
        "Links:\n" + "\n".join(link_lines) + "\n\n"
        "Return JSON with EXACTLY this shape:\n"
        '{"grant_page_urls": ["https://...", "https://..."]}\n'
        "Return at most 3 URLs. If none are clear grant-application pages, "
        'return {"grant_page_urls": []}.'
    )

    try:
        resp = client.chat.completions.create(
            # model="gpt-4o-mini",
            model=_MODEL_FAST,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=30,
        )
        data = json.loads(resp.choices[0].message.content)
        urls = data.get("grant_page_urls") or []
        # Validate: only URLs that appeared in our submitted link list
        submitted = {u for u, _ in sample_items}
        return [u for u in urls if isinstance(u, str) and u in submitted][:3]
    except Exception as exc:
        logger.warning("Phase B LLM classifier failed for %s: %s", foundation_homepage, exc)
        return []


# ── Application-process invitation-only gate ─────────────────────────────────

_INVITATION_ONLY_RE = re.compile(
    r"\b("
    r"invitation only|by invitation|invitation-?based|"
    r"do not accept unsolicited|not accept unsolicited|"
    r"unsolicited (proposals|applications|requests)? (are )?not (accepted|considered|reviewed)|"
    r"no unsolicited (proposals|applications|requests)|"
    r"we do not (accept|consider|review)|"
    r"closed to (new )?(applicants|applications)|"
    r"not accepting (new )?(applicants|applications)|"
    r"applications? (are )?(currently )?closed|"
    r"giving is limited to|grants?-?making is limited to|"
    r"pre-?selected (recipients?|grantees?)"
    r")\b",
    re.IGNORECASE,
)


def is_invitation_only(text: Optional[str]) -> bool:
    """True if the 990 application_process text says invitation-only / closed.

    Called as the cheapest possible drop-gate before we ever fetch a website.
    Returns False when text is None or empty (i.e. unknown → don't drop yet).
    """
    if not text or not text.strip():
        return False
    return bool(_INVITATION_ONLY_RE.search(text))


# ── Public entry point ───────────────────────────────────────────────────────


def find_grants_page(
    homepage_url: str,
    *,
    allow_llm_fallback: bool = True,
) -> Optional[Tuple[str, str]]:
    """Find the most likely grant-application page on a foundation website.

    Returns (url, reason) on success, None when no candidate page is found.
    `reason` is one of: "keyword_match", "llm_classifier".

    Strategy:
      1. Fetch homepage. If fetch fails → None.
      2. Phase A: keyword-score all internal links, return top 3 if any score
         above threshold.
      3. Phase B (optional): if Phase A returns nothing, ask gpt-4o-mini.
      4. None when both phases come up empty.

    Cost: 1 HTTP fetch always. 1 LLM call only when Phase A finds nothing.
    """
    html = fetch_page(homepage_url)
    if not html:
        logger.info("foundation_crawler: could not fetch %s", homepage_url)
        return None

    links = _extract_links(html, homepage_url)
    if not links:
        return None

    phase_a = _phase_a_candidates(links)
    if phase_a:
        best_url, _anchor, _score = phase_a[0]
        return best_url, "keyword_match"

    if allow_llm_fallback:
        phase_b = _phase_b_candidates(homepage_url, links)
        if phase_b:
            return phase_b[0], "llm_classifier"

    return None
