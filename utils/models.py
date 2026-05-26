"""Data models for scraping and configuration."""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class ToolSettings:
    """Runtime configuration for scraping tools."""

    openai_api_key: Optional[str] = None
    supabase_url: Optional[str] = None
    supabase_service_key: Optional[str] = None
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
    cancelled: bool = False


@dataclass
class SourceProgress:
    """Live progress for a single discovery source within a run."""

    name: str
    status: str = "pending"  # pending | running | completed | failed | cancelled
    urls_found: int = 0
    urls_new: int = 0
    documents_found: int = 0
    current_action: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "urls_found": self.urls_found,
            "urls_new": self.urls_new,
            "documents_found": self.documents_found,
            "current_action": self.current_action,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class DiscoveryProgress:
    """Live progress for an in-flight discovery run.

    Held in an in-memory registry keyed by run_id (mirrors api.jobs.JobStore).
    A compact snapshot is persisted to discovery_runs.progress_snapshot on each
    update so the frontend can recover state after a refresh.
    """

    run_id: str
    status: str = "running"  # running | running_docs | completed | failed | cancelled
    sources: Dict[str, SourceProgress] = field(default_factory=dict)
    urls_discovered: int = 0
    urls_new: int = 0
    documents_submitted: int = 0
    documents_downloaded: int = 0
    documents_extracted: int = 0
    documents_skipped_dedup: int = 0
    documents_errors: int = 0
    scrape_job_id: Optional[str] = None
    latest_results: List[Dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    cancel_token: threading.Event = field(default_factory=threading.Event)

    def ensure_source(self, name: str) -> SourceProgress:
        sp = self.sources.get(name)
        if sp is None:
            sp = SourceProgress(name=name)
            self.sources[name] = sp
        return sp

    def update_source(self, name: str, **fields_to_update: Any) -> None:
        sp = self.ensure_source(name)
        for k, v in fields_to_update.items():
            if hasattr(sp, k):
                setattr(sp, k, v)
        # Auto-stamp timestamps on status transitions
        if "status" in fields_to_update:
            if fields_to_update["status"] == "running" and sp.started_at is None:
                sp.started_at = time.time()
            if fields_to_update["status"] in ("completed", "failed", "cancelled") and sp.finished_at is None:
                sp.finished_at = time.time()

    def add_result_preview(self, result: Dict[str, Any], cap: int = 5) -> None:
        """Append a freshly discovered result for the live preview, capped."""
        self.latest_results.append(result)
        if len(self.latest_results) > cap:
            self.latest_results = self.latest_results[-cap:]

    def to_snapshot(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "sources": {name: sp.to_dict() for name, sp in self.sources.items()},
            "urls_discovered": self.urls_discovered,
            "urls_new": self.urls_new,
            "documents_submitted": self.documents_submitted,
            "documents_downloaded": self.documents_downloaded,
            "documents_extracted": self.documents_extracted,
            "documents_skipped_dedup": self.documents_skipped_dedup,
            "documents_errors": self.documents_errors,
            "scrape_job_id": self.scrape_job_id,
            "latest_results": self.latest_results,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }
