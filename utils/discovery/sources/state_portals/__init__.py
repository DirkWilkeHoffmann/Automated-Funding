"""State grant-portal adapters.

Each state adapter implements a `fetch(keywords, since_date, max_results)`
function and returns a list of grant dicts with at minimum:
  url, title, agency, deadline, applicant_types

The aggregator `StatePortalsSource` (in registry.py) fans out across all
enabled state adapters and yields a uniform stream of SourceResults to the
orchestrator.

Adding a new state: write a new module here, expose it via STATE_ADAPTERS.
"""

from __future__ import annotations

from typing import Callable, Dict

from utils.discovery.sources.state_portals.ca_grants import fetch_ca_grants
from utils.discovery.sources.state_portals.ny_grants import fetch_ny_grants
from utils.discovery.sources.state_portals.tx_grants import fetch_tx_grants


# Two-letter state code → adapter function.
# Adapter signature: (keywords: str, since_date: str | None, max_results: int)
#                    -> list[dict]
StateAdapter = Callable[..., list]

STATE_ADAPTERS: Dict[str, StateAdapter] = {
    "CA": fetch_ca_grants,
    "NY": fetch_ny_grants,
    "TX": fetch_tx_grants,
}
