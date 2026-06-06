"""Scraping-related constants."""

HEADERS = {"User-Agent": "automated-funding-bot/1.0"}

DISCOVERY_DEPTH = 2
MAX_PAGES = 10
MAX_DISCOVERY_PAGES = 40
PAUSE_BETWEEN_REQUESTS = 1.0

# ── Listing-page detection ────────────────────────────────────────────────────
# A URL is classified as a listing/aggregator page when this many signals fire.
LISTING_SIGNAL_THRESHOLD = 2

# URL-path substrings that strongly suggest a listing page.
LISTING_URL_KEYWORDS = [
    "/category/", "/tag/", "/page/",
    "funding-opportunities", "funding-opportunity-list",
    "april-may", "may-june", "june-july", "july-august", "august-september",
    "september-october", "october-november", "november-december",
    "-roundup", "grant-list", "grants-list",
]

# Phrases in page title / H1 that indicate a listing.
LISTING_TITLE_KEYWORDS = [
    "funding opportunities", "grants for", "roundup",
    "list of grants", "list of fund", "funding roundup",
]

# Domains always excluded when extracting grant links from listing pages.
LISTING_EXCLUDED_DOMAINS = {
    "facebook.com", "twitter.com", "x.com", "linkedin.com",
    "instagram.com", "youtube.com", "whatsapp.com", "t.co",
    "google.com", "maps.google.com",
}

# Anchor-text / URL keywords that indicate a link leads to a grant detail page.
LISTING_GRANT_LINK_KEYWORDS = {
    "apply", "grant", "fund", "deadline", "opportunity",
    "award", "nofa", "rfp", "solicit", "proposal",
}

KEYWORDS = [
    "grant",
    "grants",
    "apply",
    "fund",
    "funding",
    "eligible",
    "eligibility",
    "criteria",
    "who-can-apply",
    "what-we-fund",
    "apply-for",
    "apply-for-funding",
    "support",
    "programme",
    "award",
    "awarded",
    "application",
    "guidelines",
]
