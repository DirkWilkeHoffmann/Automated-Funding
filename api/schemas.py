"""Pydantic schemas for the FastAPI service."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl


class HealthResponse(BaseModel):
    status: str = "ok"


class ScrapeRequest(BaseModel):
    fund_url: HttpUrl = Field(..., description="Funding page to scrape")
    fund_name: Optional[str] = Field(None, description="Optional friendly name")


class ScrapeResponse(BaseModel):
    fund_url: HttpUrl
    fund_name: Optional[str]
    pages_scraped: Optional[int]
    visited_urls_count: Optional[int]
    eligibility: Optional[str]
    error: Optional[str] = None
    raw: Dict[str, Any]


class BatchScrapeRequest(BaseModel):
    fund_urls: List[HttpUrl]
    rescrape_urls: List[HttpUrl] = Field(
        default_factory=list, description="Already processed URLs to re-scrape"
    )
    rescrape_scope: Literal["stale", "any"] = Field(
        default="stale",
        description="Whether rescrape_urls are restricted to stale rows only or can target any existing row.",
    )


class JobCreatedResponse(BaseModel):
    job_id: str
    fund_urls: List[HttpUrl]
    to_scrape: List[HttpUrl]
    already_processed: List[HttpUrl] = Field(default_factory=list)
    duplicates_in_payload: List[HttpUrl] = Field(default_factory=list)
    rescrape_urls: List[HttpUrl] = Field(default_factory=list)
    rescrape_scope: Literal["stale", "any"] = "stale"


class JobError(BaseModel):
    url: str
    message: str


class UrlTiming(BaseModel):
    url: str
    duration_seconds: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None


class JobStatusResponse(BaseModel):
    job_id: str
    done: bool
    progress_percent: int
    results: List[Dict[str, Any]]
    errors: List[JobError]
    current_url: Optional[str] = None
    current_elapsed_seconds: int = 0
    total_elapsed_seconds: int = 0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    url_timings: List[UrlTiming] = Field(default_factory=list)
    total_urls: int = 0
    completed_urls: int = 0


class ResultsResponse(BaseModel):
    results: List[Dict[str, Any]]


class StaleResultsResponse(BaseModel):
    results: List[Dict[str, Any]]
    months: int = 3
    cutoff_timestamp: Optional[str] = None


class RefreshResultsResponse(BaseModel):
    status: str = "ok"
    total_results: int = 0


class PrepareUrlsRequest(BaseModel):
    fund_urls: List[HttpUrl] = Field(..., description="URLs to stage for scraping")


class PrepareUrlsResponse(BaseModel):
    to_scrape: List[HttpUrl]
    already_processed: List[HttpUrl]
    duplicates_in_payload: List[HttpUrl]
    normalized_map: Dict[str, str]


class UpdateOpenAIKeyRequest(BaseModel):
    openai_api_key: str = Field("", description="OpenAI API key to use for this runtime session")


class UpdateOpenAIKeyResponse(BaseModel):
    status: str = "ok"
    openai_api_key_set: bool = True


# ── Admin schemas ────────────────────────────────────────────────────────────


class OrgProfileRequest(BaseModel):
    name: Optional[str] = None
    ein: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    mission: Optional[str] = None
    services: Optional[List[str]] = None
    annual_income: Optional[int] = None
    staff_count: Optional[int] = None
    volunteer_count: Optional[int] = None
    website: Optional[str] = None
    ai_system_prompt: Optional[str] = None
    ai_user_prompt: Optional[str] = None


class OrgProfileResponse(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    ein: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    mission: Optional[str] = None
    services: Optional[List[str]] = None
    annual_income: Optional[int] = None
    staff_count: Optional[int] = None
    volunteer_count: Optional[int] = None
    website: Optional[str] = None
    ai_system_prompt: Optional[str] = None
    ai_user_prompt: Optional[str] = None


class UserRecord(BaseModel):
    id: str
    email: Optional[str] = None
    role: str = "user"
    created_at: Optional[str] = None


class UserRoleRequest(BaseModel):
    role: Literal["user", "superuser"]


class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: Literal["user", "superuser"] = "user"


class CreateUserResponse(BaseModel):
    id: str
    email: str
    role: str


class SetOpenAIKeyRequest(BaseModel):
    openai_api_key: str


class TokenStatusResponse(BaseModel):
    name: str
    masked: str
    updated_at: Optional[str] = None


# ── Discovery schemas ────────────────────────────────────────────────────────


class DiscoverySourcesConfig(BaseModel):
    propublica: bool = True
    grants_gov: bool = True
    sam_gov: bool = False
    web_search: bool = True
    federal_register: bool = True


class DiscoveryConfigRequest(BaseModel):
    enabled: bool = False
    cron_expression: str = "0 2 * * 1"
    states: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    sources: DiscoverySourcesConfig = Field(default_factory=DiscoverySourcesConfig)
    max_per_source: int = Field(default=100, ge=10, le=500)


class DiscoveryConfigResponse(DiscoveryConfigRequest):
    id: Optional[str] = None
    updated_at: Optional[str] = None


class DiscoveryRunResponse(BaseModel):
    id: str
    started_at: str
    finished_at: Optional[str] = None
    status: str
    trigger: str
    urls_discovered: int = 0
    urls_new: int = 0
    scrape_job_id: Optional[str] = None
    error_message: Optional[str] = None


class SetSamGovKeyRequest(BaseModel):
    sam_gov_api_key: str


class SetBraveSearchKeyRequest(BaseModel):
    brave_search_api_key: str


class BulkDeleteRequest(BaseModel):
    urls: List[str]
