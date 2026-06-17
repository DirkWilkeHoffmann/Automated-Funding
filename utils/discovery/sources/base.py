"""Discovery source plugin interface.

Every source implements `DiscoverySource` and yields `SourceResult` instances
incrementally so the orchestrator can stream per-source progress to the UI
instead of blocking until each source completes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Protocol, runtime_checkable


@dataclass
class DocumentRef:
    """A document (PDF/attachment) attached to a source result.

    Phase 1 sources may leave this list empty. Phase 2 wires in the document
    fetcher + LLM extraction pipeline that consumes these refs.

    If `prefetched_text` is set, the fetcher skips download (and PyPDF2 parsing)
    and runs LLM extraction directly on the supplied text. This is the escape
    hatch for sources whose PDFs are unreachable from server-side requests
    (e.g. ProPublica's 990 PDFs sit behind Cloudflare bot protection) — the
    adapter can synthesize a summary from API-provided structured data and
    still get a populated llm_summary downstream.
    """

    url: str
    kind: str  # 'form_990' | 'rfp' | 'notice' | 'attachment'
    source_url: str  # the page the doc was found on
    filing_year: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    prefetched_text: Optional[str] = None


@dataclass
class SourceResult:
    """A single discovered funder/opportunity from a source."""

    url: str
    funder_name: Optional[str] = None
    source_metadata: Dict[str, Any] = field(default_factory=dict)
    documents: List[DocumentRef] = field(default_factory=list)


ProgressCallback = Callable[[str, Dict[str, Any]], None]
"""Signature: progress_cb(source_name, partial_update_dict).

The orchestrator passes a callback that mutates the shared DiscoveryProgress
object. Sources call it on meaningful state transitions:
  progress_cb(name, {"current_action": "querying state=CA"})
  progress_cb(name, {"urls_found": 12})
"""


@dataclass
class SourceContext:
    """Per-run context handed to each source's fetch() call."""

    keywords: str
    states: List[str]  # explicit states from config, may be empty
    max_per_source: int
    state: Dict[str, Any]  # cursor / rotation state for this source
    progress_cb: ProgressCallback
    cancel_token: threading.Event

    def cancelled(self) -> bool:
        return self.cancel_token.is_set()


@runtime_checkable
class DiscoverySource(Protocol):
    """Source plugin contract.

    Implementations should:
      - yield SourceResult lazily so the orchestrator can stream progress
      - call ctx.progress_cb on meaningful state changes
      - check ctx.cancelled() between API pages / state iterations
      - return updated state via the new_state attribute set on the instance
        before fetch() returns (or via the return value of close_state())
    """

    name: str

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]: ...

    def close_state(self) -> Dict[str, Any]:
        """Return the updated source state to persist for the next run."""
        ...
