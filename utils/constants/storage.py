"""Storage and data schema constants."""

from pathlib import Path

SAVE_DIR = "Scraped"

CSV_COLUMNS = [
    "fund_url",
    "fund_name",
    "applicant_types",
    "geographic_scope",
    "us_state_scope",
    "beneficiary_focus",
    "funding_range",
    "restrictions",
    "application_status",
    "deadline",
    "notes",
    "grant_type",
    "eligibility",
    "evidence",
    "match_rubric",
    "pages_scraped",
    "visited_urls_count",
    "pdf_read",
    "pdf_url",
    "pdf_pages",
    "pdf_text",
    "extraction_timestamp",
    "error",
    "discovery_source",
    "content_hash",
    "last_checked_at",
    "discovery_funder_ein",
]
