"""Global configuration and settings management."""

import logging
import os
from typing import Callable, Optional

from utils.models import ToolSettings

logger = logging.getLogger(__name__)

_SETTINGS = ToolSettings(
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
    supabase_service_key=os.getenv("SUPABASE_SERVICE_KEY"),
)


def configure_tools(
    *,
    openai_api_key: Optional[str] = None,
    supabase_url: Optional[str] = None,
    supabase_service_key: Optional[str] = None,
    log_callback: Optional[Callable[[str, str], None]] = None,
):
    """Update runtime settings used by the scraping utilities."""

    if openai_api_key is not None:
        _SETTINGS.openai_api_key = openai_api_key
    if supabase_url is not None:
        _SETTINGS.supabase_url = supabase_url
    if supabase_service_key is not None:
        _SETTINGS.supabase_service_key = supabase_service_key
    if log_callback is not None:
        _SETTINGS.log_callback = log_callback


def get_settings() -> ToolSettings:
    """Get the current tool settings."""
    return _SETTINGS
