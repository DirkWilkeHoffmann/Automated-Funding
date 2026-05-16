"""Global configuration and settings management."""

import logging
from typing import Callable, Optional

from utils.models import ToolSettings

logger = logging.getLogger(__name__)

_SETTINGS = ToolSettings()


def configure_tools(
    *,
    openai_api_key: Optional[str] = None,
    google_service_account: Optional[dict] = None,
    google_sheet_id: Optional[str] = None,
    log_callback: Optional[Callable[[str, str], None]] = None,
):
    """Update runtime settings used by the scraping utilities."""

    if openai_api_key is not None:
        _SETTINGS.openai_api_key = openai_api_key
    if google_service_account is not None:
        _SETTINGS.google_service_account = google_service_account
    if google_sheet_id is not None:
        _SETTINGS.google_sheet_id = google_sheet_id
    if log_callback is not None:
        _SETTINGS.log_callback = log_callback


def get_settings() -> ToolSettings:
    """Get the current tool settings."""
    return _SETTINGS
