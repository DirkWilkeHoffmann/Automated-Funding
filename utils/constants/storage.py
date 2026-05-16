"""Storage and data schema constants."""

from pathlib import Path

SAVE_DIR = "Scraped"

CSV_COLUMNS = [
    "fund_url",
    "fund_name",
    "applicant_types",
    "geographic_scope",
    "beneficiary_focus",
    "funding_range",
    "restrictions",
    "application_status",
    "deadline",
    "notes",
    "eligibility",
    "evidence",
    "pages_scraped",
    "visited_urls_count",
    "pdf_read",
    "pdf_url",
    "pdf_pages",
    "pdf_text",
    "extraction_timestamp",
    "error",
]
