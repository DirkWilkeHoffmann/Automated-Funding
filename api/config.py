"""Application configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass(slots=True)
class AppConfig:
    openai_api_key: Optional[str]
    supabase_url: str
    supabase_service_key: str
    log_level: str = "INFO"

    @classmethod
    def load(cls) -> "AppConfig":
        """Load configuration from environment variables."""

        def _clean(value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            cleaned = value.strip()
            if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
                cleaned = cleaned[1:-1].strip()
            return cleaned or None

        supabase_url = (_clean(os.getenv("SUPABASE_URL")) or "").strip()
        supabase_service_key = (_clean(os.getenv("SUPABASE_SERVICE_KEY")) or "").strip()

        if not supabase_url:
            raise ValueError("SUPABASE_URL environment variable is required.")
        if not supabase_service_key:
            raise ValueError("SUPABASE_SERVICE_KEY environment variable is required.")

        return cls(
            openai_api_key=_clean(os.getenv("OPENAI_API_KEY")),
            supabase_url=supabase_url,
            supabase_service_key=supabase_service_key,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


settings = AppConfig.load()
