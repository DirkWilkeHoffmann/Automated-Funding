"""Google Sheets integration for persistent data storage."""

import logging
import time
from typing import Any, List, Tuple

import gspread
import pandas as pd
import requests
from google.oauth2.service_account import Credentials

from utils.config import get_settings
from utils.constants import CSV_COLUMNS
from utils.utils_helpers import log_message

logger = logging.getLogger(__name__)


def _require_google_config() -> Tuple[dict, str]:
    """Ensure Google Sheets credentials are configured."""
    settings = get_settings()
    if not settings.google_service_account or not settings.google_sheet_id:
        raise RuntimeError(
            "Google Sheets credentials not configured. Call configure_tools(...) first."
        )
    return settings.google_service_account, settings.google_sheet_id


def _format_service_account_for_log(service_account: Any) -> str:
    """Return a safe-to-log summary of the service account config."""
    if isinstance(service_account, dict):
        summary = {
            "type": service_account.get("type"),
            "project_id": service_account.get("project_id"),
            "client_email": service_account.get("client_email"),
            "private_key_id": service_account.get("private_key_id"),
            "has_private_key": bool(service_account.get("private_key")),
        }
        return str(summary)
    # Fall back to a short preview for unexpected types (e.g. JSON string).
    text = str(service_account)
    preview = text if len(text) <= 200 else text[:200] + "...(truncated)"
    return f"{type(service_account).__name__}: {preview}"


def _get_sheet(retries: int = 3, delay: int = 1):
    """Connect to Google Sheet with retry logic."""
    creds_info, sheet_id = _require_google_config()
    log_message(
        f"Google Sheets config: sheet_id={sheet_id} "
        f"service_account={_format_service_account_for_log(creds_info)}",
        "info",
    )

    def try_connect():
        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        client = gspread.authorize(creds)
        sh = client.open_by_key(sheet_id)
        return sh.sheet1

    for attempt in range(retries):
        try:
            return try_connect()
        except requests.exceptions.RequestException as exc:
            if attempt == retries - 1:
                log_message(f"Network error while contacting Google Sheets: {exc}", "error")
                raise
            time.sleep(delay * (2**attempt))
        except Exception as exc:
            if attempt == retries - 1:
                log_message(
                    "Failed to connect to Google Sheets. "
                    f"sheet_id={sheet_id} "
                    f"service_account={_format_service_account_for_log(creds_info)} "
                    f"error={exc}",
                    "error",
                )
                raise
            time.sleep(delay * (2**attempt))


def load_google_sheet_as_dataframe() -> pd.DataFrame:
    """Load Google Sheet as a DataFrame (fresh, no caching)."""
    try:
        ws = _get_sheet()
        data = ws.get_all_records()
        return pd.DataFrame(data)
    except Exception as exc:
        log_message(f"Failed to load Google Sheet: {exc}", "error")
        return pd.DataFrame(columns=CSV_COLUMNS)


def ensure_sheet_header(ws) -> None:
    """Ensure the Google Sheet header row includes all CSV columns."""
    try:
        header = ws.row_values(1)
    except Exception as exc:
        log_message(f"Failed to read sheet header: {exc}", "warning")
        return

    if not header:
        try:
            ws.insert_row(CSV_COLUMNS, 1)
        except Exception as exc:
            log_message(f"Failed to initialize sheet header: {exc}", "warning")
        return

    missing = [col for col in CSV_COLUMNS if col not in header]
    if not missing:
        return
    try:
        ws.update("1:1", [header + missing])
    except Exception as exc:
        log_message(f"Failed to update sheet header: {exc}", "warning")


def append_to_google_sheet(rows: List[dict]):
    """
    Permanently store results in Google Sheets.
    Each dict in `rows` is one funding record.
    """
    try:
        ws = _get_sheet()
        ensure_sheet_header(ws)
        header = ws.row_values(1)
        if not header:
            header = list(CSV_COLUMNS)

        # Use the live sheet header order so values always land in the right column,
        # even if the header order differs from CSV_COLUMNS.
        data = []
        for r in rows:
            row = [r.get(col, "") for col in header]
            data.append(row)

        ws.append_rows(data, value_input_option="RAW")
    except Exception as e:
        log_message(f"Failed to write to Google Sheets: {e}", "error")
