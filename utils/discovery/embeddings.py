"""OpenAI embedding wrapper for the discovery targeting engine.

Reuses the same key-resolution as llm_utils (DB api_tokens → env). Returns
1536-dim vectors from text-embedding-3-small. All callers must handle a None
return (no API key configured) gracefully.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from utils.llm_utils import get_client

logger = logging.getLogger(__name__)

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
_BATCH_CAP = 100
_MAX_CHARS = 8000  # keep well under the model's token limit


def _clean(text: str) -> str:
    return (text or "").strip()[:_MAX_CHARS]


def embed_text(text: str) -> Optional[List[float]]:
    """Embed a single string. Returns None if no client or empty input."""
    cleaned = _clean(text)
    if not cleaned:
        return None
    out = embed_batch([cleaned])
    return out[0] if out else None


def embed_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """Embed many strings, preserving order. Empty inputs map to None.

    Returns a list the same length as `texts`. On API failure for a chunk,
    that chunk's entries are None (caller decides whether to retry later).
    """
    client = get_client()
    results: List[Optional[List[float]]] = [None] * len(texts)
    if client is None:
        return results

    # Collect indices of non-empty inputs to send.
    payload_idx = [i for i, t in enumerate(texts) if _clean(t)]
    for start in range(0, len(payload_idx), _BATCH_CAP):
        chunk_idx = payload_idx[start : start + _BATCH_CAP]
        chunk = [_clean(texts[i]) for i in chunk_idx]
        for attempt in range(3):
            try:
                resp = client.embeddings.create(model=EMBED_MODEL, input=chunk)
                for local_i, item in enumerate(resp.data):
                    results[chunk_idx[local_i]] = item.embedding
                break
            except Exception as exc:
                if attempt == 2:
                    logger.warning("embed_batch chunk failed after retries: %s", exc)
                else:
                    time.sleep(2 ** attempt)
    return results
