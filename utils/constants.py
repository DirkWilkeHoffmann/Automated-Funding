"""
Backwards-compatibility module for constants.

Constants have been reorganized into:
- utils/constants/scraping.py - Scraping-related constants
- utils/constants/llm.py - LLM prompts and eligibility settings
- utils/constants/storage.py - Storage and schema constants

This module re-exports all constants for backwards compatibility.
New code should import directly from utils.constants (which is a package).
"""

# Re-export all constants for backwards compatibility
from utils.constants.llm import ELIGIBILITY_ORDER, LLM_PROMPT
from utils.constants.scraping import (
    DISCOVERY_DEPTH,
    HEADERS,
    KEYWORDS,
    MAX_DISCOVERY_PAGES,
    MAX_PAGES,
    PAUSE_BETWEEN_REQUESTS,
)
from utils.constants.storage import CSV_COLUMNS, SAVE_DIR

__all__ = [
    "SAVE_DIR",
    "DISCOVERY_DEPTH",
    "MAX_PAGES",
    "MAX_DISCOVERY_PAGES",
    "PAUSE_BETWEEN_REQUESTS",
    "HEADERS",
    "ELIGIBILITY_ORDER",
    "LLM_PROMPT",
    "CSV_COLUMNS",
    "KEYWORDS",
]
