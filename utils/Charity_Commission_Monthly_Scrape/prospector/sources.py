"""Source file operations and data collection for grant prospector."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Set

from dataclasses import dataclass


@dataclass
class FilterResult:
    """Result of filtering a source file."""

    source_rows: int
    predicate_rows: int
    active_rows: int
    written_rows: int
    duplicate_rows_skipped: int
    missing_charity_id_rows: int
    charity_ids: Set[int]


def get_charity_id(row: Dict[str, Any]) -> Optional[int]:
    """Extract charity ID from row, trying registered_charity_number first."""
    from .search import coerce_int

    registered = coerce_int(row.get("registered_charity_number"))
    if registered is not None:
        return registered
    return coerce_int(row.get("organisation_number"))


def iter_json_array(path: Path, chunk_size: int = 1_048_576) -> Iterator[Dict[str, Any]]:
    """Iterate JSON array from file."""
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8-sig") as handle:
        buffer = ""
        in_array = False
        reached_eof = False

        while True:
            if not reached_eof and len(buffer) < chunk_size:
                chunk = handle.read(chunk_size)
                if chunk:
                    buffer += chunk
                else:
                    reached_eof = True

            idx = 0
            buffer_len = len(buffer)

            while True:
                while idx < buffer_len and buffer[idx].isspace():
                    idx += 1

                if not in_array:
                    if idx >= buffer_len:
                        break
                    if buffer[idx] != "[":
                        raise ValueError(f"{path} is not a JSON array.")
                    in_array = True
                    idx += 1
                    continue

                while idx < buffer_len and buffer[idx].isspace():
                    idx += 1

                if idx < buffer_len and buffer[idx] == ",":
                    idx += 1
                    continue

                while idx < buffer_len and buffer[idx].isspace():
                    idx += 1

                if idx < buffer_len and buffer[idx] == "]":
                    return

                if idx >= buffer_len:
                    break

                try:
                    obj, next_idx = decoder.raw_decode(buffer, idx)
                except json.JSONDecodeError:
                    break

                if not isinstance(obj, dict):
                    raise ValueError(f"Expected objects in {path}, got {type(obj).__name__}.")

                yield obj
                idx = next_idx

            buffer = buffer[idx:]

            if reached_eof:
                trailing = buffer.strip()
                if trailing and trailing != "]":
                    raise ValueError(f"Unexpected trailing content in {path}: {trailing[:80]!r}")
                return


def write_json_array(output_path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    """Write rows as JSON array."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("[\n")
        first = True
        for row in rows:
            if first:
                first = False
            else:
                handle.write(",\n")
            json.dump(row, handle, ensure_ascii=False, separators=(",", ":"))
            count += 1
        handle.write("\n]\n")
    return count


def write_json_object(output_path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON object to file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")


def collect_rows_for_charities(
    source_file: Path, charity_ids: Set[int]
) -> Dict[int, list[Dict[str, Any]]]:
    """Collect all rows for specified charities."""
    rows_by_charity: Dict[int, list[Dict[str, Any]]] = {}
    if not charity_ids:
        return rows_by_charity

    for row in iter_json_array(source_file):
        charity_id = get_charity_id(row)
        if charity_id is None or charity_id not in charity_ids:
            continue
        rows_by_charity.setdefault(charity_id, []).append(row)

    return rows_by_charity


def filter_source_to_output(
    source_file: Path,
    output_file: Path,
    active_charities: Set[int],
    predicate: Callable[[Dict[str, Any]], bool],
) -> FilterResult:
    """Filter source file to output based on predicate and active charities."""
    source_rows = 0
    predicate_rows = 0
    active_rows = 0
    duplicate_rows_skipped = 0
    missing_charity_id_rows = 0
    written_charity_ids: Set[int] = set()

    def iter_filtered_rows() -> Iterator[Dict[str, Any]]:
        nonlocal source_rows
        nonlocal predicate_rows
        nonlocal active_rows
        nonlocal duplicate_rows_skipped
        nonlocal missing_charity_id_rows

        for row in iter_json_array(source_file):
            source_rows += 1

            if not predicate(row):
                continue
            predicate_rows += 1

            charity_id = get_charity_id(row)
            if charity_id is None:
                missing_charity_id_rows += 1
                continue

            if charity_id not in active_charities:
                continue
            active_rows += 1

            if charity_id in written_charity_ids:
                duplicate_rows_skipped += 1
                continue

            written_charity_ids.add(charity_id)
            yield row

    written_rows = write_json_array(output_file, iter_filtered_rows())

    return FilterResult(
        source_rows=source_rows,
        predicate_rows=predicate_rows,
        active_rows=active_rows,
        written_rows=written_rows,
        duplicate_rows_skipped=duplicate_rows_skipped,
        missing_charity_id_rows=missing_charity_id_rows,
        charity_ids=written_charity_ids,
    )


def write_merged_csv(
    output_path: Path,
    charities: list[Dict[str, Any]],
    charity_details_url_template: str = "",
) -> None:
    """Write merged charity data to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "registered_charity_number",
        "url",
        "segment",
        "annual_return_filtered_count",
        "classification_filtered_count",
        "charity_count",
        "area_of_operation_count",
        "classification_all_rows_count",
        "annual_return_history_count",
        "annual_return_parta_count",
        "annual_return_partb_count",
        "annual_return_filtered_rows_json",
        "classification_filtered_rows_json",
        "charity_rows_json",
        "area_of_operation_rows_json",
        "classification_all_rows_json",
        "annual_return_history_rows_json",
        "annual_return_parta_rows_json",
        "annual_return_partb_rows_json",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in charities:
            charity_number = item["registered_charity_number"]
            annual_filtered = item["matched_rows"]["annual_return_filtered"]
            classification_filtered = item["matched_rows"]["classification_filtered"]
            charity_rows = item["charity"]
            area_rows = item["area_of_operation"]
            classification_rows = item["classification_all_rows"]
            history_rows = item["annual_return_history"]
            parta_rows = item["annual_return_parta"]
            partb_rows = item["annual_return_partb"]

            url = charity_details_url_template.format(charity_number=charity_number)
            writer.writerow(
                {
                    "registered_charity_number": charity_number,
                    "url": url,
                    "segment": item["segment"],
                    "annual_return_filtered_count": len(annual_filtered),
                    "classification_filtered_count": len(classification_filtered),
                    "charity_count": len(charity_rows),
                    "area_of_operation_count": len(area_rows),
                    "classification_all_rows_count": len(classification_rows),
                    "annual_return_history_count": len(history_rows),
                    "annual_return_parta_count": len(parta_rows),
                    "annual_return_partb_count": len(partb_rows),
                    "annual_return_filtered_rows_json": json.dumps(
                        annual_filtered, ensure_ascii=False, separators=(",", ":")
                    ),
                    "classification_filtered_rows_json": json.dumps(
                        classification_filtered, ensure_ascii=False, separators=(",", ":")
                    ),
                    "charity_rows_json": json.dumps(
                        charity_rows, ensure_ascii=False, separators=(",", ":")
                    ),
                    "area_of_operation_rows_json": json.dumps(
                        area_rows, ensure_ascii=False, separators=(",", ":")
                    ),
                    "classification_all_rows_json": json.dumps(
                        classification_rows, ensure_ascii=False, separators=(",", ":")
                    ),
                    "annual_return_history_rows_json": json.dumps(
                        history_rows, ensure_ascii=False, separators=(",", ":")
                    ),
                    "annual_return_parta_rows_json": json.dumps(
                        parta_rows, ensure_ascii=False, separators=(",", ":")
                    ),
                    "annual_return_partb_rows_json": json.dumps(
                        partb_rows, ensure_ascii=False, separators=(",", ":")
                    ),
                }
            )
