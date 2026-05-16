"""Orchestration functions for grant making pipeline."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .queries import load_download_manifest, load_snapshot_payload, save_download_manifest
from .transformations import (
    build_funds_snapshot,
    calculate_monthly_delta,
    utc_iso,
)


def run_grant_script(script_path: Path) -> None:
    """Execute the grant prospector script."""
    if not script_path.exists():
        raise FileNotFoundError(f"Could not find script: {script_path}")

    print(f"\nRunning analysis script: {script_path.name}\n")
    result = subprocess.run([sys.executable, str(script_path)], cwd=str(script_path.parent))
    if result.returncode != 0:
        raise RuntimeError(f"{script_path.name} failed with exit code {result.returncode}.")
    print(f"\nCompleted: {script_path.name}")


def allocate_run_id(runs_dir: Path, preferred_run_id: str) -> str:
    """Allocate a unique run ID, with collision avoidance."""
    if not (runs_dir / preferred_run_id).exists():
        return preferred_run_id
    suffix = 2
    while True:
        candidate = f"{preferred_run_id}_{suffix}"
        if not (runs_dir / candidate).exists():
            return candidate
        suffix += 1


def find_latest_snapshot(runs_dir: Path) -> tuple[Path | None, str]:
    """Find the latest snapshot in a runs directory."""
    if not runs_dir.exists():
        return None, ""
    candidates: list[tuple[str, Path]] = []
    for child in runs_dir.iterdir():
        if not child.is_dir():
            continue
        snapshot_path = child / "funds_snapshot.json"
        if snapshot_path.exists():
            candidates.append((child.name, snapshot_path))
    if not candidates:
        return None, ""
    candidates.sort(key=lambda item: item[0])
    run_id, path = candidates[-1]
    return path, run_id


def copy_latest_aliases(latest_dir: Path, alias_map: dict[str, Path]) -> None:
    """Copy files to latest directory as aliases."""
    import shutil

    latest_dir.mkdir(parents=True, exist_ok=True)
    for alias_name, source_path in alias_map.items():
        destination = latest_dir / alias_name
        shutil.copy2(source_path, destination)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Monthly grant pipeline orchestrator: download Charity Commission extracts, "
            "run grant_prospector.py, archive dated outputs, compare with previous run, "
            "and generate a to_scrape pipeline CSV."
        )
    )
    parser.add_argument(
        "--required-only",
        action="store_true",
        help=(
            "Only download ZIPs required by grant_prospector.py "
            "(charity, annual return history/parta/partb, area, classification)."
        ),
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download/extract and only run grant_prospector.py.",
    )
    parser.add_argument(
        "--skip-run",
        action="store_true",
        help="Download/extract only, and do not run grant_prospector.py.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download ZIPs and overwrite extracted JSON files.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="HTTP timeout in seconds for each request (default: 300).",
    )
    parser.add_argument(
        "--local-html",
        type=Path,
        default=Path(__file__).resolve().parent / "ChatiryCommission.html",
        help=(
            "Optional local HTML file to parse first for download links "
            "(default: ChatiryCommission.html)."
        ),
    )
    parser.add_argument(
        "--download-manifest",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "charity_commission" / "json_zips" / "download_manifest.json",
        help=(
            "Path to ZIP metadata manifest used to detect unchanged downloads "
            "(default: data/charity_commission/json_zips/download_manifest.json)."
        ),
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output" / "monthly_runs",
        help="Directory for dated monthly run folders (default: output/monthly_runs).",
    )
    parser.add_argument(
        "--latest-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output" / "latest",
        help="Directory for latest-file aliases (default: output/latest).",
    )
    parser.add_argument(
        "--to-scrape-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output" / "to_scrape",
        help=("Directory for dated and latest to_scrape CSV files " "(default: output/to_scrape)."),
    )
    parser.add_argument(
        "--significant-change-abs",
        type=float,
        default=50_000.0,
        help=(
            "Absolute numeric delta threshold for significant change detection " "(default: 50000)."
        ),
    )
    parser.add_argument(
        "--significant-change-pct",
        type=float,
        default=0.20,
        help=(
            "Relative numeric delta threshold for significant change detection "
            "(default: 0.20 = 20%%)."
        ),
    )
    parser.add_argument(
        "--run-id",
        default="",
        help=(
            "Optional run id for the dated output folder. If omitted, UTC timestamp is used "
            "(for example: 20260225T120000Z)."
        ),
    )
    return parser.parse_args()


def archive_run_results(base_dir: Path, run_dir: Path) -> dict[str, Path]:
    """Archive grant outputs to run directory."""
    import shutil

    output_dir = base_dir / "output"
    grant_output_filenames = (
        "grant_making_main_activity_active.json",
        "grant_making_classification_302_active.json",
        "grant_making_cross_file_comparison.json",
        "grant_making_merged_detailed.csv",
    )

    archived: dict[str, Path] = {}
    for file_name in grant_output_filenames:
        source_path = output_dir / file_name
        if not source_path.exists():
            raise FileNotFoundError(
                f"Expected output file is missing after grant script run: {source_path}"
            )
        destination_path = run_dir / file_name
        shutil.copy2(source_path, destination_path)
        archived[file_name] = destination_path
    return archived


def orchestrate_pipeline(
    base_dir: Path,
    args: argparse.Namespace,
) -> None:
    """Orchestrate the complete pipeline execution."""
    from .queries import (
        discover_json_zip_urls,
        download_file,
        extract_json_files,
        ensure_required_inputs_present,
        build_download_manifest_entry,
        select_urls,
    )

    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than 0.")
    if args.significant_change_abs < 0:
        raise ValueError("--significant-change-abs must be >= 0.")
    if args.significant_change_pct < 0:
        raise ValueError("--significant-change-pct must be >= 0.")

    run_started = datetime.now(timezone.utc)
    run_started_utc = utc_iso(run_started)

    download_manifest = load_download_manifest(args.download_manifest)
    download_events: list[dict[str, Any]] = []

    input_dir = base_dir / "input"
    zip_download_dir = base_dir / "data" / "charity_commission" / "json_zips"

    if not args.skip_download:
        urls = discover_json_zip_urls(timeout=args.timeout, local_html_path=args.local_html)
        urls = select_urls(urls, required_only=args.required_only)
        if not urls:
            raise RuntimeError("No JSON ZIP URLs selected for download.")

        print(f"Preparing to process {len(urls)} JSON ZIP file(s).")
        all_extracted: list[Path] = []
        for url in urls:
            from urllib.parse import urlparse
            from pathlib import Path as PathlibPath

            zip_name = PathlibPath(urlparse(url).path).name
            if not zip_name.lower().endswith(".zip"):
                continue

            zip_path = zip_download_dir / zip_name
            previous_entry = download_manifest.get(zip_name, {})
            downloaded, remote_metadata = download_file(
                url=url,
                destination=zip_path,
                timeout=args.timeout,
                force=args.force,
                previous_metadata=previous_entry,
            )
            updated_entry = build_download_manifest_entry(
                url=url,
                destination=zip_path,
                previous_entry=previous_entry,
                remote_metadata=remote_metadata,
                downloaded=downloaded,
            )
            download_manifest[zip_name] = updated_entry

            extracted = extract_json_files(
                zip_path=zip_path,
                output_dir=input_dir,
                overwrite=args.force or downloaded,
            )
            all_extracted.extend(extracted)

            download_events.append(
                {
                    "zip_name": zip_name,
                    "url": url,
                    "downloaded": downloaded,
                    "local_size": zip_path.stat().st_size if zip_path.exists() else None,
                    "etag": updated_entry.get("etag"),
                    "last_modified": updated_entry.get("last_modified"),
                }
            )

        save_download_manifest(args.download_manifest, download_manifest)

        print(f"JSON files available in input/: {len(set(all_extracted))}")
        ensure_required_inputs_present(input_dir)
        print("Required JSON inputs are present.")
    else:
        ensure_required_inputs_present(input_dir)
        print("Skipped download. Required JSON inputs already present.")

    if args.skip_run:
        print("Skipped running grant_prospector.py as requested.")
        return

    grant_script = base_dir / "grant_prospector.py"
    run_grant_script(grant_script)

    args.runs_dir.mkdir(parents=True, exist_ok=True)
    previous_snapshot_path, previous_run_id = find_latest_snapshot(args.runs_dir)

    preferred_run_id = (
        args.run_id.strip() if isinstance(args.run_id, str) and args.run_id.strip() else ""
    )
    if not preferred_run_id:
        preferred_run_id = run_started.strftime("%Y%m%dT%H%M%SZ")
    run_id = allocate_run_id(args.runs_dir, preferred_run_id)

    run_dir = args.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    archived_outputs = archive_run_results(base_dir, run_dir)
    merged_csv_path = archived_outputs["grant_making_merged_detailed.csv"]

    snapshot_payload = build_funds_snapshot(
        merged_csv_path=merged_csv_path,
        run_id=run_id,
        generated_at_utc=utc_iso(datetime.now(timezone.utc)),
    )
    snapshot_path = run_dir / "funds_snapshot.json"
    from .queries import write_json_payload

    write_json_payload(snapshot_path, snapshot_payload)

    previous_snapshot_payload: dict[str, Any] = {}
    if previous_snapshot_path is not None:
        try:
            previous_snapshot_payload = load_snapshot_payload(previous_snapshot_path)
        except Exception as exc:
            print(
                "Warning: failed to load previous snapshot "
                f"({previous_snapshot_path}): {exc}. Treating this run as baseline."
            )
            previous_snapshot_payload = {}
            previous_run_id = ""

    delta_payload, to_scrape_rows = calculate_monthly_delta(
        current_snapshot=snapshot_payload,
        previous_snapshot=previous_snapshot_payload,
        run_id=run_id,
        run_started_utc=run_started_utc,
        previous_run_id=previous_run_id,
        absolute_threshold=args.significant_change_abs,
        percent_threshold=args.significant_change_pct,
    )
    delta_path = run_dir / "monthly_delta.json"
    write_json_payload(delta_path, delta_payload)

    from .queries import write_to_scrape_csv

    to_scrape_run_path = run_dir / "to_scrape_pipeline.csv"
    write_to_scrape_csv(to_scrape_run_path, to_scrape_rows)

    from .transformations import first_non_empty_text

    source_extract_month = first_non_empty_text(snapshot_payload.get("source_extract_month"))
    if not source_extract_month:
        source_extract_month = run_started.strftime("%Y-%m")

    to_scrape_monthly_path = args.to_scrape_dir / f"to_scrape_pipeline_{source_extract_month}.csv"
    write_to_scrape_csv(to_scrape_monthly_path, to_scrape_rows)

    to_scrape_latest_path = args.to_scrape_dir / "to_scrape_pipeline_latest.csv"
    write_to_scrape_csv(to_scrape_latest_path, to_scrape_rows)

    from .queries import build_input_manifest

    run_metadata = {
        "schema_version": 1,
        "run_id": run_id,
        "run_started_utc": run_started_utc,
        "run_completed_utc": utc_iso(datetime.now(timezone.utc)),
        "source_extract_date": snapshot_payload.get("source_extract_date"),
        "source_extract_month": source_extract_month,
        "previous_run_id": previous_run_id,
        "previous_snapshot_path": str(previous_snapshot_path) if previous_snapshot_path else "",
        "configuration": {
            "required_only": bool(args.required_only),
            "skip_download": bool(args.skip_download),
            "force": bool(args.force),
            "timeout": int(args.timeout),
            "download_manifest": str(args.download_manifest),
            "runs_dir": str(args.runs_dir),
            "latest_dir": str(args.latest_dir),
            "to_scrape_dir": str(args.to_scrape_dir),
            "significant_change_abs": args.significant_change_abs,
            "significant_change_pct": args.significant_change_pct,
        },
        "download_events": download_events,
        "input_files": build_input_manifest(input_dir),
        "output_files": {
            "run_dir": str(run_dir),
            "annual_return_output": str(run_dir / "grant_making_main_activity_active.json"),
            "classification_output": str(run_dir / "grant_making_classification_302_active.json"),
            "comparison_output": str(run_dir / "grant_making_cross_file_comparison.json"),
            "merged_output": str(run_dir / "grant_making_merged_detailed.csv"),
            "snapshot": str(snapshot_path),
            "delta": str(delta_path),
            "to_scrape_run": str(to_scrape_run_path),
            "to_scrape_monthly": str(to_scrape_monthly_path),
            "to_scrape_latest": str(to_scrape_latest_path),
        },
        "delta_counts": delta_payload.get("counts", {}),
    }
    metadata_path = run_dir / "run_metadata.json"
    write_json_payload(metadata_path, run_metadata)

    latest_aliases = dict(archived_outputs)
    latest_aliases.update(
        {
            "funds_snapshot.json": snapshot_path,
            "monthly_delta.json": delta_path,
            "to_scrape_pipeline.csv": to_scrape_run_path,
            "run_metadata.json": metadata_path,
        }
    )
    copy_latest_aliases(args.latest_dir, latest_aliases)

    print()
    print(f"Monthly run id: {run_id}")
    print(f"Run folder: {run_dir}")
    print(f"Current charities in snapshot: {snapshot_payload.get('charity_count', 0):,}")
    print(
        "To-scrape charities (new + significant changes): "
        f"{delta_payload.get('counts', {}).get('to_scrape_charities', 0):,}"
    )
    print(f"Saved dated to-scrape CSV: {to_scrape_monthly_path}")
    print(f"Saved latest to-scrape CSV: {to_scrape_latest_path}")
    print(f"Saved delta summary JSON: {delta_path}")
