"""In-memory registry of live DiscoveryProgress objects.

Mirrors the pattern in api/jobs.JobStore — the live progress object is the
source of truth while a run is in flight; a compact snapshot is persisted to
discovery_runs.progress_snapshot on each update so the frontend can recover
state after a refresh or if the API process restarts.
"""

from __future__ import annotations

import threading
from typing import Dict, Optional

from utils.models import DiscoveryProgress


class DiscoveryProgressRegistry:
    def __init__(self) -> None:
        self._runs: Dict[str, DiscoveryProgress] = {}
        self._lock = threading.Lock()

    def create(self, run_id: str) -> DiscoveryProgress:
        progress = DiscoveryProgress(run_id=run_id)
        with self._lock:
            self._runs[run_id] = progress
        return progress

    def get(self, run_id: str) -> Optional[DiscoveryProgress]:
        with self._lock:
            return self._runs.get(run_id)

    def cancel(self, run_id: str) -> bool:
        progress = self.get(run_id)
        if not progress:
            return False
        progress.cancel_token.set()
        return True


progress_registry = DiscoveryProgressRegistry()
