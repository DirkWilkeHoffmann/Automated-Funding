"""IRS 990 ZIP bundle fetcher with on-disk caching.

Each annual IRS 990 release is split into ~50 ZIP files (~70MB each), where
each ZIP contains thousands of {object_id}_public.xml entries. We cache the
downloaded ZIPs on disk briefly so that orgs in the same batch only cost one
HTTP download per discovery run.

Cache layout:
  ~/.cache/automated-funding/irs/{year}_TEOS_XML_NNA.zip

ZIPs older than CACHE_TTL_HOURS are evicted on next access.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.path.expanduser("~/.cache/automated-funding/irs"))
CACHE_TTL_HOURS = 24
MAX_NEW_BATCHES_PER_CALL = 3  # cap fresh ~1GB ZIP downloads per discovery run
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/zip,application/octet-stream",
}

# In-process lock to prevent two concurrent downloads of the same ZIP
import threading
_download_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(batch_zip: str) -> threading.Lock:
    with _locks_guard:
        lock = _download_locks.get(batch_zip)
        if lock is None:
            lock = threading.Lock()
            _download_locks[batch_zip] = lock
        return lock


def _zip_url(batch_zip: str, submission_year: int) -> str:
    # batch_zip e.g. "2024_TEOS_XML_11A" → filename "2024_TEOS_XML_11A.zip"
    return f"https://apps.irs.gov/pub/epostcard/990/xml/{submission_year}/{batch_zip}.zip"


def _cache_path(batch_zip: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{batch_zip}.zip"


def _is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age_h = (time.time() - path.stat().st_mtime) / 3600
    return age_h < CACHE_TTL_HOURS


def _prune_stale_cache() -> None:
    """Best-effort eviction of ZIPs past TTL — keeps the cache dir small."""
    if not CACHE_DIR.exists():
        return
    cutoff = time.time() - CACHE_TTL_HOURS * 3600
    for p in CACHE_DIR.glob("*.zip"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


def download_zip(batch_zip: str, submission_year: int) -> Optional[Path]:
    """Download an IRS batch ZIP (or return cached path)."""
    path = _cache_path(batch_zip)
    if _is_fresh(path):
        return path

    lock = _lock_for(batch_zip)
    with lock:
        if _is_fresh(path):  # another thread beat us to it
            return path
        url = _zip_url(batch_zip, submission_year)
        logger.info("Downloading IRS ZIP %s (~70MB)", batch_zip)
        try:
            with requests.get(url, headers=_HEADERS, stream=True, timeout=300) as resp:
                resp.raise_for_status()
                # Stream to a temp file in the same dir then atomic-move so a
                # failed download doesn't poison the cache
                tmp = tempfile.NamedTemporaryFile(
                    dir=CACHE_DIR, delete=False, suffix=".zip.part"
                )
                try:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        if chunk:
                            tmp.write(chunk)
                    tmp.close()
                    os.replace(tmp.name, path)
                except Exception:
                    tmp.close()
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
                    raise
            logger.info("Cached IRS ZIP %s (%d bytes)", batch_zip, path.stat().st_size)
            return path
        except Exception as exc:
            logger.warning("Could not download IRS ZIP %s: %s", batch_zip, exc)
            return None


ZIP_DEFLATED64 = 9


def _read_with_inflate64(zf: zipfile.ZipFile, target: str) -> Optional[str]:
    """Decompress a Deflate64 (method 9) entry that stdlib zipfile rejects.

    IRS bulk ZIPs published in 2025+ use Deflate64 for most entries, which
    Python's stdlib zlib can't handle. We pull the raw compressed bytes from
    the zip and feed them through the `inflate64` library.
    """
    try:
        import inflate64
    except ImportError:
        return None
    try:
        info = zf.getinfo(target)
        with zf.open(target, "r") as raw_f:
            # zf.open returns a ZipExtFile; we need the RAW compressed bytes.
            # Re-open via the underlying _fileobj at the right offset.
            zf.fp.seek(info.header_offset)
            local_header = zf.fp.read(30)
            fname_len = int.from_bytes(local_header[26:28], "little")
            extra_len = int.from_bytes(local_header[28:30], "little")
            zf.fp.seek(info.header_offset + 30 + fname_len + extra_len)
            compressed = zf.fp.read(info.compress_size)
        decompressor = inflate64.Inflater()
        decompressed = decompressor.inflate(compressed)
        return decompressed.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("inflate64 fallback failed for %s: %s", target, exc)
        return None


def extract_xml(batch_zip_path: Path, object_id: str) -> Optional[str]:
    """Extract the {object_id}_public.xml entry from a cached ZIP.

    Two-tier extraction:
      1. stdlib zipfile (covers Deflate, Stored, BZIP2, LZMA)
      2. inflate64 fallback (covers Deflate64 — IRS uses this for newer batches)

    Returns the XML text, or None if both paths fail.
    """
    target = f"{object_id}_public.xml"
    try:
        with zipfile.ZipFile(batch_zip_path, "r") as zf:
            if target not in zf.namelist():
                cands = [n for n in zf.namelist() if n.endswith(target)]
                if not cands:
                    logger.warning("ZIP %s missing entry %s", batch_zip_path.name, target)
                    return None
                target = cands[0]

            try:
                with zf.open(target) as f:
                    return f.read().decode("utf-8", errors="replace")
            except NotImplementedError:
                # Compression unsupported by stdlib — try inflate64
                info = zf.getinfo(target)
                if info.compress_type == ZIP_DEFLATED64:
                    text = _read_with_inflate64(zf, target)
                    if text is not None:
                        return text
                logger.warning(
                    "Could not extract %s from %s: compression method %s not supported",
                    target, batch_zip_path.name, info.compress_type,
                )
                return None
    except (zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        logger.warning("Could not extract %s from %s: %s", target, batch_zip_path.name, exc)
        return None
    except Exception as exc:
        logger.warning("Unexpected error extracting %s from %s: %s", target, batch_zip_path.name, exc)
        return None


def fetch_multiple_xmls(
    filings: Iterable[Tuple[str, str, int]],
) -> Dict[str, str]:
    """Batch-aware fetch: group by ZIP, download each at most once.

    Args:
        filings: iterable of (object_id, batch_zip, submission_year) tuples.

    Returns:
        dict: object_id → xml_text (only successful entries are included).
    """
    _prune_stale_cache()

    # Group by (batch_zip, submission_year) so we download each ZIP once
    by_batch: Dict[Tuple[str, int], List[str]] = {}
    for object_id, batch_zip, submission_year in filings:
        if not object_id or not batch_zip:
            continue
        key = (batch_zip, submission_year)
        by_batch.setdefault(key, []).append(object_id)

    # Cap fresh ZIP downloads. Already-cached ZIPs are free, so we let
    # those proceed first. Each fresh download is ~1GB and ~30-60s.
    out: Dict[str, str] = {}
    cached_batches: List[Tuple[Tuple[str, int], List[str]]] = []
    fresh_batches: List[Tuple[Tuple[str, int], List[str]]] = []
    for key, object_ids in by_batch.items():
        batch_zip, _ = key
        if _is_fresh(_cache_path(batch_zip)):
            cached_batches.append((key, object_ids))
        else:
            fresh_batches.append((key, object_ids))

    fresh_to_fetch = fresh_batches[:MAX_NEW_BATCHES_PER_CALL]
    fresh_skipped = len(fresh_batches) - len(fresh_to_fetch)
    if fresh_skipped:
        logger.info(
            "IRS ZIP cap: %d cached + %d fresh fetched, %d fresh skipped this run",
            len(cached_batches), len(fresh_to_fetch), fresh_skipped,
        )

    for (batch_zip, submission_year), object_ids in cached_batches + fresh_to_fetch:
        path = download_zip(batch_zip, submission_year)
        if path is None:
            continue
        for oid in object_ids:
            xml = extract_xml(path, oid)
            if xml:
                out[oid] = xml
    return out
