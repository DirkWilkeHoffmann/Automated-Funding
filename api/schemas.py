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
    # Phase 3: org-profile filter fields used by the discovery pre-filter.
    ntee_codes: Optional[List[str]] = None        # NTEE prefixes the org operates in (e.g. ["B", "P30"])
    service_states: Optional[List[str]] = None    # States served (distinct from HQ `state`)
    applicant_types: Optional[List[str]] = None   # ["501c3", "fiscal_sponsor", ...]
    accepts_unsolicited: Optional[bool] = None    # Will the org pursue invitations-only-style grants?
    can_cost_share: Optional[bool] = None         # Can the org provide match funds?
    min_grant_size: Optional[int] = None          # Minimum useful award ceiling ($)
    max_grant_size: Optional[int] = None          # Cap when applicable ($)
    # Phase 5: per-org topic filter
    cfda_categories: Optional[List[str]] = None   # Grants.gov categories (e.g. ["ELT","ISS","ED"])
    eligible_applicant_codes: Optional[List[str]] = None  # Grants.gov codes (e.g. ["12","25"])
    category_suggestion_notes: Optional[str] = None       # LLM rationale (audit trail)
    # Phase 9: structured org profile (for richer LLM eligibility context)
    org_type_description: Optional[str] = None
    service_area_description: Optional[str] = None
    beneficiaries: Optional[List[str]] = None
    programs: Optional[List[str]] = None
    income_sources: Optional[List[str]] = None
    currency: Optional[str] = None
    founded_year: Optional[int] = None
    target_outcomes: Optional[List[str]] = None
    partner_orgs: Optional[List[str]] = None
    accreditations: Optional[List[str]] = None
    # Phase 10: geography rework
    country: Optional[str] = None
    service_countries: Optional[List[str]] = None
    service_regions: Optional[dict] = None  # {country_code: [regions]}


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
    # Phase 3 mirror fields
    ntee_codes: Optional[List[str]] = None
    service_states: Optional[List[str]] = None
    applicant_types: Optional[List[str]] = None
    accepts_unsolicited: Optional[bool] = None
    can_cost_share: Optional[bool] = None
    min_grant_size: Optional[int] = None
    max_grant_size: Optional[int] = None
    # Phase 5 mirror
    cfda_categories: Optional[List[str]] = None
    eligible_applicant_codes: Optional[List[str]] = None
    category_suggestion_notes: Optional[str] = None
    # Phase 9 mirror
    org_type_description: Optional[str] = None
    service_area_description: Optional[str] = None
    beneficiaries: Optional[List[str]] = None
    programs: Optional[List[str]] = None
    income_sources: Optional[List[str]] = None
    currency: Optional[str] = None
    founded_year: Optional[int] = None
    target_outcomes: Optional[List[str]] = None
    partner_orgs: Optional[List[str]] = None
    accreditations: Optional[List[str]] = None
    # Phase 10 mirror
    country: Optional[str] = None
    service_countries: Optional[List[str]] = None
    service_regions: Optional[dict] = None


class ProfileSuggestionResponse(BaseModel):
    """Returned by POST /admin/org/suggest-profile.

    The endpoint reads the saved org's name + mission + services and asks
    gpt-4o-mini to fill in the 10 Phase 9 structured-profile fields.
    Operator confirms/edits in the UI before saving.
    """

    org_type_description: str = ""
    service_area_description: str = ""
    beneficiaries: List[str] = []
    programs: List[str] = []
    income_sources: List[str] = []
    currency: str = "USD"
    founded_year: Optional[int] = None
    target_outcomes: List[str] = []
    partner_orgs: List[str] = []
    accreditations: List[str] = []
    notes: str = ""


class CategorySuggestionResponse(BaseModel):
    """Returned by POST /admin/org/suggest-categories.

    The endpoint reads the saved org's mission+services and asks gpt-4o-mini
    to suggest a CFDA category whitelist + applicant-code list. Operator
    confirms / edits in the UI before saving.
    """

    cfda_categories: List[str] = []
    eligible_applicant_codes: List[str] = []
    notes: str = ""


# ── Phase 11: Targeting schemas ──────────────────────────────────────────────


class TargetingDeriveRequest(BaseModel):
    mission: str = Field(..., description="Organisation mission statement")
    website: Optional[str] = None
    ein: Optional[str] = None


class TargetingSuggestion(BaseModel):
    ntee_prefixes: List[str] = []
    cfda_categories: List[str] = []
    cause_keywords: List[str] = []
    applicant_codes: List[str] = []
    notes: str = ""


class TargetingConfirmRequest(BaseModel):
    ntee_prefixes: List[str] = []
    cfda_categories: List[str] = []
    cause_keywords: List[str] = []
    applicant_codes: List[str] = []


class TargetingStatusResponse(BaseModel):
    targeting_confirmed: bool = False
    targeting_updated_at: Optional[str] = None
    client_embedding_set: bool = False
    ntee_prefixes: List[str] = []
    cfda_categories: List[str] = []
    cause_keywords: List[str] = []
    applicant_codes: List[str] = []


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
    federal_register: bool = True
    state_portals: bool = True
    candid: bool = False  # gated on paid API key
    irs_bmf: bool = True
    grants_gov_db: bool = True
    sam_cfda_db: bool = True


class ImportConfig(BaseModel):
    bmf_min_asset_code: int = Field(default=7, ge=1, le=9)
    bmf_ntee_prefixes: List[str] = Field(default_factory=list)
    bmf_batch_size: int = Field(default=50, ge=10, le=500)
    grants_gov_close_days: int = Field(default=90, ge=7, le=365)
    grants_gov_nonprofit_filter: bool = True  # was missing from the schema; runtime read it directly
    # Per-dataset refresh cron expressions (UTC). Defaults stagger Sunday morning.
    bmf_cron: str = "0 3 * * 0"
    irs_990_index_cron: str = "0 4 * * 0"
    grants_gov_cron: str = "0 5 * * *"
    sam_cfda_cron: str = "0 6 * * 0"
    # Last-imported timestamps — read-only on PUT (importers write these directly).
    bmf_last_imported_at: Optional[str] = None
    grants_gov_last_imported_at: Optional[str] = None
    sam_cfda_last_imported_at: Optional[str] = None
    irs_990_index_last_imported_at: Optional[str] = None


class DiscoveryConfigRequest(BaseModel):
    enabled: bool = False
    cron_expression: str = "0 2 * * 1"
    states: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    sources: DiscoverySourcesConfig = Field(default_factory=DiscoverySourcesConfig)
    max_per_source: int = Field(default=100, ge=10, le=500)
    documents_per_run: int = Field(default=200, ge=0, le=1000)
    import_config: ImportConfig = Field(default_factory=ImportConfig)


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
    progress_snapshot: Optional[Dict[str, Any]] = None


class DiscoverySourceProgress(BaseModel):
    name: str
    status: str = "pending"
    urls_found: int = 0
    urls_new: int = 0
    documents_found: int = 0
    current_action: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


class DiscoveryProgressResponse(BaseModel):
    run_id: str
    status: str
    sources: Dict[str, DiscoverySourceProgress] = Field(default_factory=dict)
    urls_discovered: int = 0
    urls_new: int = 0
    documents_submitted: int = 0
    documents_downloaded: int = 0
    documents_extracted: int = 0
    documents_skipped_dedup: int = 0
    documents_errors: int = 0
    scrape_job_id: Optional[str] = None
    latest_results: List[Dict[str, Any]] = Field(default_factory=list)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    elapsed_seconds: int = 0
    live: bool = False  # true when read from in-memory registry, false when from DB snapshot


class DiscoveryImportStatusResponse(BaseModel):
    bmf_last_imported_at: Optional[str] = None
    grants_gov_last_imported_at: Optional[str] = None
    sam_cfda_last_imported_at: Optional[str] = None
    irs_990_index_last_imported_at: Optional[str] = None
    bmf_funders_total: int = 0
    bmf_funders_unscraped: int = 0
    grant_opportunities_total: int = 0
    grant_opportunities_open: int = 0
    sam_cfda_total: int = 0
    irs_990_index_total: int = 0


class APIKeyHealth(BaseModel):
    name: str               # e.g. "openai", "brave_search", "sam_gov", "candid"
    status: str             # "ok" | "missing" | "invalid" | "unknown"
    detail: Optional[str] = None


class DiscoveryHealthResponse(BaseModel):
    keys: List[APIKeyHealth]
    org_profile_complete: bool = False
    org_profile_missing: List[str] = Field(default_factory=list)


class PreFilterFunnelStage(BaseModel):
    label: str
    count: int


class PreFilterFunnel(BaseModel):
    name: str
    stages: List[PreFilterFunnelStage]


class PreFilterPreviewResponse(BaseModel):
    funders: PreFilterFunnel
    opportunities: PreFilterFunnel


class DatasetBrowseResponse(BaseModel):
    dataset: str
    rows: List[Dict[str, Any]]
    total: int                  # total rows matching filters (not just this page)
    limit: int
    offset: int


class SetSamGovKeyRequest(BaseModel):
    sam_gov_api_key: str


class SetBraveSearchKeyRequest(BaseModel):
    brave_search_api_key: str


class SetCandidKeyRequest(BaseModel):
    """Phase 7: Candid Essentials API key (paid, optional)."""

    candid_api_key: str


class BulkDeleteRequest(BaseModel):
    urls: List[str]


# ── Listing-page preview schemas ─────────────────────────────────────────────


class ScrapePreviewRequest(BaseModel):
    url: str = Field(..., description="URL to inspect for listing-page detection")


class ScrapePreviewItem(BaseModel):
    url: str
    title: str


class ScrapePreviewResponse(BaseModel):
    type: Literal["listing", "single"]
    items: List[ScrapePreviewItem] = Field(default_factory=list)
    count: int = 0


# ── Pending URLs schemas ─────────────────────────────────────────────────────


class PendingUrlItem(BaseModel):
    id: str
    url: str
    title: Optional[str] = None
    source_url: Optional[str] = None
    status: str
    created_at: Optional[str] = None


class ApprovePendingRequest(BaseModel):
    ids: List[str]


class RejectPendingRequest(BaseModel):
    ids: List[str]
