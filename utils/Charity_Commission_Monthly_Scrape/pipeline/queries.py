"""Database and file I/O queries for the grant pipeline."""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def load_json_file(path: Path) -> dict[str, Any]:
    """Load JSON file from disk."""
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON payload to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)


def load_download_manifest(manifest_path: Path) -> dict[str, dict[str, Any]]:
    """Load the ZIP download manifest."""
    if not manifest_path.exists():
        return {}
    try:
        return load_json_file(manifest_path)
    except Exception as exc:
        logger.warning(f"Failed to load manifest ({manifest_path}): {exc}")
        return {}


def save_download_manifest(
    manifest_path: Path, manifest: dict[str, dict[str, Any]]
) -> None:
    """Save the ZIP download manifest."""
    write_json_payload(manifest_path, manifest)


def load_snapshot_payload(snapshot_path: Path) -> dict[str, Any]:
    """Load a snapshot JSON file."""
    return load_json_file(snapshot_path)


def discover_json_zip_urls(
    timeout: int = 300, local_html_path: Path | None = None
) -> list[str]:
    """Discover JSON ZIP URLs from Charity Commission."""
    urls = []

    if local_html_path and local_html_path.exists():
        try:
            with open(local_html_path, "r", encoding="utf-8") as f:
                html = f.read()
            urls = extract_download_links_from_html(html)
            if urls:
                logger.info(f"Discovered {len(urls)} URLs from local HTML")
                return urls
        except Exception as exc:
            logger.warning(f"Failed to read local HTML ({local_html_path}): {exc}")

    base_url = "https://www.charitycommission.gov.uk"
    path = "/about-us/our-research-and-reports/charity-research-topics/charity-register-data"
    full_url = base_url + path

    try:
        req = Request(full_url)
        req.add_header("User-Agent", "Mozilla/5.0 (automated)")
        with urlopen(req, timeout=timeout) as response:
            html = response.read().decode("utf-8")
        urls = extract_download_links_from_html(html)
    except Exception as exc:
        logger.warning(f"Failed to fetch ({full_url}): {exc}")
    return urls


def extract_download_links_from_html(html: str) -> list[str]:
    """Extract JSON ZIP download links from HTML."""
    url_pattern = re.compile(
        r'href=["\']([^"\']*\.zip)["\']',
        re.IGNORECASE,
    )
    matches = url_pattern.findall(html)
    urls = []
    for match in matches:
        if match.lower().endswith(".zip"):
            if not match.startswith("http"):
                match = urljoin("https://www.charitycommission.gov.uk", match)
            urls.append(match)
    return list(set(urls))


def select_urls(
    urls: list[str],
    required_only: bool = False,
) -> list[str]:
    """Select URLs to process."""
    if not urls:
        return []

    required_keywords = {"charity", "annual", "area", "classification"}
    selected = []
    for url in urls:
        url_lower = url.lower()
        if any(kw in url_lower for kw in required_keywords):
            selected.append(url)
            if not required_only:
                continue

    return selected


def build_download_manifest_entry(
    url: str,
    destination: Path,
    previous_entry: dict[str, Any],
    remote_metadata: dict[str, Any],
    downloaded: bool,
) -> dict[str, Any]:
    """Build a manifest entry for a downloaded ZIP."""
    return {
        "url": url,
        "local_path": str(destination),
        "size": destination.stat().st_size if destination.exists() else None,
        "etag": remote_metadata.get("etag", previous_entry.get("etag")),
        "last_modified": remote_metadata.get("last_modified", previous_entry.get("last_modified")),
        "downloaded_at": (
            datetime.utcnow().isoformat() if downloaded else previous_entry.get("downloaded_at")
        ),
    }


def download_file(
    url: str,
    destination: Path,
    timeout: int = 300,
    force: bool = False,
    previous_metadata: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Download a file from a URL with caching."""
    destination.parent.mkdir(parents=True, exist_ok=True)

    remote_metadata: dict[str, Any] = {}
    try:
        req = Request(url)
        req.add_header("User-Agent", "Mozilla/5.0 (automated)")

        if not force and destination.exists() and previous_metadata:
            if_etag = previous_metadata.get("etag")
            if_modified = previous_metadata.get("last_modified")
            if if_etag:
                req.add_header("If-None-Match", if_etag)
            if if_modified:
                req.add_header("If-Modified-Since", if_modified)

        with urlopen(req, timeout=timeout) as response:
            if response.status == 304:
                return False, remote_metadata
            remote_metadata["etag"] = response.headers.get("ETag", "")
            remote_metadata["last_modified"] = response.headers.get("Last-Modified", "")
            content = response.read()

        with open(destination, "wb") as f:
            f.write(content)
        return True, remote_metadata
    except Exception as exc:
        logger.error(f"Failed to download {url}: {exc}")
        raise


def extract_json_files(
    zip_path: Path, output_dir: Path, overwrite: bool = False
) -> list[Path]:
    """Extract JSON files from a ZIP archive."""
    import zipfile

    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP not found: {zip_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for file_info in zf.infolist():
                if not file_info.filename.lower().endswith(".json"):
                    continue
                output_path = output_dir / Path(file_info.filename).name
                if output_path.exists() and not overwrite:
                    continue
                zf.extract(file_info, output_dir)
                extracted.append(output_path)
    except Exception as exc:
        logger.error(f"Failed to extract {zip_path}: {exc}")
        raise
    return extracted


def ensure_required_inputs_present(input_dir: Path) -> None:
    """Verify required JSON input files are present."""
    required_files = [
        "charity.json",
        "charity_annual_return_history.json",
        "charity_annual_return_parta.json",
        "charity_annual_return_partb.json",
        "charity_area.json",
        "charity_classification.json",
    ]
    missing = [f for f in required_files if not (input_dir / f).exists()]
    if missing:
        raise FileNotFoundError(f"Missing required JSON files: {missing}")


def build_input_manifest(input_dir: Path) -> dict[str, dict[str, Any]]:
    """Build a manifest of available input JSON files."""
    manifest = {}
    if not input_dir.exists():
        return manifest
    for json_file in input_dir.glob("*.json"):
        manifest[json_file.name] = {
            "path": str(json_file),
            "size": json_file.stat().st_size,
            "modified": json_file.stat().st_mtime,
        }
    return manifest


def write_to_scrape_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write to-scrape CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["charity_number", "name", "reason", "run_id"])
            writer.writeheader()
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
