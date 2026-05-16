"""Data models for scraping and configuration."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class ToolSettings:
    """Runtime configuration for scraping tools."""

    openai_api_key: Optional[str] = None
    google_service_account: Optional[dict] = None
    google_sheet_id: Optional[str] = None
    log_callback: Optional[Callable[[str, str], None]] = None


@dataclass
class ScrapeProgress:
    """Tracks progress of a background scrape job."""

    done: bool = False
    progress_percent: int = 0
    results: List[dict] = field(default_factory=list)
    errors: List[Tuple[str, str]] = field(default_factory=list)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    current_url: Optional[str] = None
    current_started_at: Optional[float] = None
    url_timings: List[Dict[str, Any]] = field(default_factory=list)
