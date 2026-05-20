"""Scrape job tracking — in-memory state for real-time polling, Supabase for durability."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List

from utils.db.client import get_supabase
from utils.tools import ScrapeProgress, start_background_scrape

logger = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    urls: List[str]
    progress: ScrapeProgress
    _db_synced: bool = field(default=False, init=False, repr=False)
    _cancelled: bool = field(default=False, init=False, repr=False)
    _sync_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def cancel(self) -> None:
        self._cancelled = True
        if not self.progress.done:
            self.progress.cancelled = True
            self.progress.done = True
            self.progress.finished_at = time.time()

    def snapshot(self) -> Dict:
        now = time.time()
        current_elapsed = 0
        if self.progress.current_url and self.progress.current_started_at:
            current_elapsed = int(max(0, now - self.progress.current_started_at))
        total_elapsed = 0
        if self.progress.started_at:
            total_elapsed = int(
                max(0, (self.progress.finished_at or now) - self.progress.started_at)
            )

        result = {
            "job_id": self.id,
            "done": self.progress.done,
            "progress_percent": self.progress.progress_percent,
            "results": self.progress.results,
            "errors": self.progress.errors,
            "current_url": self.progress.current_url,
            "current_elapsed_seconds": current_elapsed,
            "total_elapsed_seconds": total_elapsed,
            "started_at": self.progress.started_at,
            "finished_at": self.progress.finished_at,
            "url_timings": self.progress.url_timings,
            "total_urls": len(self.urls),
            "completed_urls": len(self.progress.results),
        }

        # Sync completion to DB once when job finishes.
        if result["done"] and not self._db_synced:
            with self._sync_lock:
                if not self._db_synced:
                    if _sync_job_completion(self.id, result["completed_urls"], self.progress.finished_at):
                        self._db_synced = True

        return result


def _sync_job_completion(job_id: str, completed_urls: int, finished_at: float | None) -> bool:
    try:
        finished_iso = (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(finished_at))
            if finished_at
            else None
        )
        get_supabase().table("scrape_jobs").update(
            {
                "done": True,
                "progress_percent": 100,
                "completed_urls": completed_urls,
                "finished_at": finished_iso,
            }
        ).eq("id", job_id).execute()
        return True
    except Exception as exc:
        logger.warning("Could not sync job completion to DB for %s: %s", job_id, exc)
        return False


class JobStore:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, urls: List[str], *, url_metadata: dict | None = None) -> Job:
        job_id = uuid.uuid4().hex
        progress = ScrapeProgress(started_at=time.time())
        job = Job(id=job_id, urls=urls, progress=progress)
        _persist_job_created(job_id, urls)      # DB row exists first
        with self._lock:
            self._jobs[job_id] = job            # then visible in memory
        start_background_scrape(urls, job_id=job_id, url_metadata=url_metadata, _progress=progress)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)


def _persist_job_created(job_id: str, urls: List[str]) -> None:
    try:
        get_supabase().table("scrape_jobs").insert(
            {
                "id": job_id,
                "urls": urls,
                "total_urls": len(urls),
            }
        ).execute()
    except Exception as exc:
        logger.error("Could not persist job record to DB for %s: %s", job_id, exc)
        raise


job_store = JobStore()
