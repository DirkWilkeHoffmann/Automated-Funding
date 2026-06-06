-- Automated Funding — Supabase schema
-- Run this in the Supabase SQL editor to set up all tables.

-- ------------------------------------------------------------
-- funds: one row per scrape result (direct migration from Google Sheets)
-- All scraped fields stored as TEXT to match existing behaviour;
-- proper types can be added in a later optimisation phase.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS funds (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fund_url            TEXT,
    fund_name           TEXT,
    applicant_types     TEXT,
    geographic_scope    TEXT,
    beneficiary_focus   TEXT,
    funding_range       TEXT,
    restrictions        TEXT,
    application_status  TEXT,
    deadline            TEXT,
    notes               TEXT,
    eligibility         TEXT,
    evidence            TEXT,
    pages_scraped       TEXT,
    visited_urls_count  TEXT,
    pdf_read            TEXT,
    pdf_url             TEXT,
    pdf_pages           TEXT,
    pdf_text            TEXT,
    extraction_timestamp TEXT,
    error               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS funds_fund_url_idx ON funds (fund_url);
CREATE INDEX IF NOT EXISTS funds_eligibility_idx ON funds (eligibility);
CREATE INDEX IF NOT EXISTS funds_extraction_timestamp_idx ON funds (extraction_timestamp);

-- ------------------------------------------------------------
-- scrape_jobs: one row per batch scrape job
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scrape_jobs (
    id               TEXT PRIMARY KEY,
    urls             TEXT[] NOT NULL DEFAULT '{}',
    done             BOOLEAN NOT NULL DEFAULT FALSE,
    progress_percent INT NOT NULL DEFAULT 0,
    current_url      TEXT,
    total_urls       INT NOT NULL DEFAULT 0,
    completed_urls   INT NOT NULL DEFAULT 0,
    started_at       TIMESTAMPTZ DEFAULT NOW(),
    finished_at      TIMESTAMPTZ
);

-- ------------------------------------------------------------
-- scrape_job_urls: per-URL tracking within a job
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scrape_job_urls (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id           TEXT NOT NULL REFERENCES scrape_jobs(id) ON DELETE CASCADE,
    url              TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    error            TEXT,
    duration_seconds FLOAT,
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS scrape_job_urls_job_id_idx ON scrape_job_urls (job_id);

-- ------------------------------------------------------------
-- organizations: single org profile (SaaS-ready via org_id FKs)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS organizations (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name           TEXT NOT NULL,
    ein            TEXT,
    mission        TEXT,
    location       TEXT,
    services       TEXT[],
    annual_income  BIGINT,
    staff_count    INT,
    volunteer_count INT,
    website        TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ------------------------------------------------------------
-- user_profiles: extends Supabase auth.users with role + org
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_profiles (
    id         UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    role       TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'superuser')),
    org_id     UUID REFERENCES organizations(id),
    full_name  TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ------------------------------------------------------------
-- api_tokens: AI service keys managed by superusers
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_tokens (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service       TEXT NOT NULL,
    key_value     TEXT,
    org_id        UUID REFERENCES organizations(id),
    updated_by    UUID REFERENCES auth.users(id),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS api_tokens_service_org_idx ON api_tokens (service, org_id);

-- ------------------------------------------------------------
-- Phase 2 migration: new US-market fields on funds
-- Run these if the funds table was already created without them.
-- ------------------------------------------------------------
ALTER TABLE funds ADD COLUMN IF NOT EXISTS us_state_scope TEXT;
ALTER TABLE funds ADD COLUMN IF NOT EXISTS grant_type TEXT;

-- ------------------------------------------------------------
-- Discovery v2 migration: live per-source progress snapshot
-- Populated by the orchestrator while a run is in flight so the
-- frontend can recover state after a refresh.
-- ------------------------------------------------------------
ALTER TABLE discovery_runs ADD COLUMN IF NOT EXISTS progress_snapshot JSONB;

-- Per-run document cap (Form 990s, RFP attachments, Federal Register PDFs).
-- Document fetcher honours this to bound LLM cost per run.
ALTER TABLE discovery_config ADD COLUMN IF NOT EXISTS documents_per_run INT DEFAULT 200;

-- ------------------------------------------------------------
-- IRS 990 e-file index — maps EIN to which annual ZIP holds its filing.
-- Refreshed on demand (weekly check) from
-- https://apps.irs.gov/pub/epostcard/990/xml/{year}/index_{year}.csv
-- The actual XML lives inside a ~70MB ZIP bundle on apps.irs.gov.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS irs_990_index (
    ein              TEXT NOT NULL,
    tax_year         INT  NOT NULL,
    object_id        TEXT NOT NULL,
    batch_zip        TEXT NOT NULL,
    return_type      TEXT,
    tax_period       TEXT,
    submission_year  INT  NOT NULL,
    taxpayer_name    TEXT,
    indexed_at       TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (ein, tax_year)
);

CREATE INDEX IF NOT EXISTS irs_990_index_ein_idx ON irs_990_index (ein);
CREATE INDEX IF NOT EXISTS irs_990_index_batch_idx ON irs_990_index (batch_zip);

CREATE TABLE IF NOT EXISTS irs_990_index_refresh (
    submission_year INT PRIMARY KEY,
    refreshed_at    TIMESTAMPTZ DEFAULT NOW(),
    row_count       INT
);

-- ------------------------------------------------------------
-- documents: PDFs / attachments harvested by discovery sources
-- (Form 990s, RFP attachments, Federal Register notices, etc.)
-- Deduplicated by document_url so re-runs skip already-extracted docs.
-- llm_summary holds grant signals pulled out by extract_from_document.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name     TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    document_url    TEXT NOT NULL UNIQUE,
    kind            TEXT NOT NULL,
    filing_year     INT,
    text_content    TEXT,
    page_count      INT,
    file_size       INT,
    llm_summary     JSONB,
    fund_url        TEXT,
    fetched_at      TIMESTAMPTZ DEFAULT NOW(),
    extracted_at    TIMESTAMPTZ,
    extraction_error TEXT
);

CREATE INDEX IF NOT EXISTS documents_fund_url_idx ON documents (fund_url);
CREATE INDEX IF NOT EXISTS documents_source_kind_idx ON documents (source_name, kind);
CREATE INDEX IF NOT EXISTS documents_filing_year_idx ON documents (filing_year DESC);

-- ------------------------------------------------------------
-- discovery_funders: IRS BMF private foundations
-- Populated monthly by utils/discovery/importers/irs_bmf.py
-- ~90K rows (FOUNDATION='04' private non-operating foundations)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discovery_funders (
  ein                  TEXT PRIMARY KEY,
  name                 TEXT NOT NULL,
  city                 TEXT,
  state                TEXT,
  zip                  TEXT,
  ntee_code            TEXT,
  foundation_type      TEXT,
  asset_code           INT,
  asset_amount         BIGINT,
  income_amount        BIGINT,
  website              TEXT,
  website_resolved_at  TIMESTAMPTZ,
  scraped_at           TIMESTAMPTZ,
  created_at           TIMESTAMPTZ DEFAULT NOW(),
  updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS discovery_funders_state_asset_idx ON discovery_funders (state, asset_code DESC);
CREATE INDEX IF NOT EXISTS discovery_funders_ntee_idx ON discovery_funders (ntee_code);
CREATE INDEX IF NOT EXISTS discovery_funders_unscraped_idx ON discovery_funders (scraped_at) WHERE scraped_at IS NULL;

-- ------------------------------------------------------------
-- grant_opportunities: Grants.gov XML extract
-- Populated daily by utils/discovery/importers/grants_gov_xml.py
-- ~10-15K active opportunities
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS grant_opportunities (
  opportunity_id    TEXT PRIMARY KEY,
  title             TEXT,
  agency            TEXT,
  opportunity_number TEXT,           -- human-readable FON, e.g. "W9126G262SOI9383"
  posted_date       DATE,
  close_date        DATE,
  award_ceiling     BIGINT,
  award_floor       BIGINT,
  category          TEXT,
  cfda_number       TEXT,            -- CFDA/Assistance Listings, e.g. "12.005"
  eligibility_text  TEXT,            -- AdditionalInformationOnEligibility from XML
  description       TEXT,            -- synopsis / description from XML
  url               TEXT,
  scraped_at        TIMESTAMPTZ,
  content_hash      TEXT,
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  updated_at        TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS opportunity_number TEXT;
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS cfda_number TEXT;
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS eligibility_text TEXT;
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS description TEXT;

CREATE INDEX IF NOT EXISTS grant_opportunities_close_date_idx ON grant_opportunities (close_date);
CREATE INDEX IF NOT EXISTS grant_opportunities_unscraped_idx ON grant_opportunities (scraped_at) WHERE scraped_at IS NULL;

-- ------------------------------------------------------------
-- Phase 3 migration: content-hash change detection + import config
-- ------------------------------------------------------------
ALTER TABLE funds ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE funds ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ;
ALTER TABLE funds ADD COLUMN IF NOT EXISTS discovery_funder_ein TEXT;
ALTER TABLE discovery_config ADD COLUMN IF NOT EXISTS import_config JSONB DEFAULT '{}';

-- ============================================================
-- Phase 0 migration: widen existing bulk-data tables
-- ============================================================
-- Brings discovery_funders, grant_opportunities, irs_990_index to
-- feature parity with the upstream datasets — capturing columns
-- that were previously dropped on the floor.

-- ------------------------------------------------------------
-- discovery_funders: 18 additional BMF columns
-- ------------------------------------------------------------
-- Source: IRS BMF eo[1-4].csv has 28 columns; we previously captured 11.
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS ico               TEXT;       -- IRS "in care of"
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS street            TEXT;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS group_code        TEXT;       -- BMF GROUP field (renamed: SQL keyword)
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS subsection        TEXT;       -- "03" for 501(c)(3), etc.
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS affiliation       TEXT;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS classification    TEXT;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS ruling            TEXT;       -- YYYYMM ruling date
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS deductibility     TEXT;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS activity          TEXT;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS organization      TEXT;       -- 1=corp, 2=trust, etc.
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS status            TEXT;       -- 01=active, etc.
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS tax_period        TEXT;       -- YYYYMM
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS income_cd         INT;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS filing_req_cd     TEXT;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS pf_filing_req_cd  TEXT;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS acct_pd           TEXT;       -- accounting period
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS revenue_amount    BIGINT;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS sort_name         TEXT;

-- Helpful indexes for the widened ingest (~1M rows after dropping FOUNDATION='04' filter)
CREATE INDEX IF NOT EXISTS discovery_funders_subsection_idx ON discovery_funders (subsection);
CREATE INDEX IF NOT EXISTS discovery_funders_revenue_idx ON discovery_funders (revenue_amount DESC NULLS LAST);

-- ------------------------------------------------------------
-- grant_opportunities: 13 additional XML fields
-- ------------------------------------------------------------
-- Source: GrantsDBExtract XML has 25 fields per OpportunitySynopsisDetail_1_0;
-- we previously captured 12.
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS opportunity_category               TEXT;  -- D (discretionary), M (mandatory), etc.
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS funding_instrument_type            TEXT;  -- G (grant), CA (cooperative agreement)
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS category_explanation               TEXT;
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS eligible_applicants                TEXT[]; -- Grants.gov numeric codes (e.g. ['25', '11'])
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS agency_code                        TEXT;  -- e.g. "DOS-SA"
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS estimated_total_program_funding    BIGINT;
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS expected_number_of_awards          INT;
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS cost_sharing_or_matching_required  BOOLEAN;
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS archive_date                       DATE;
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS last_updated_date                  DATE;
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS version                            TEXT;  -- "Synopsis 2" etc.
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS grantor_contact_email              TEXT;
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS grantor_contact_email_description  TEXT;
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS grantor_contact_text               TEXT;

CREATE INDEX IF NOT EXISTS grant_opportunities_cfda_idx ON grant_opportunities (cfda_number);
CREATE INDEX IF NOT EXISTS grant_opportunities_award_ceiling_idx ON grant_opportunities (award_ceiling DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS grant_opportunities_agency_code_idx ON grant_opportunities (agency_code);
CREATE INDEX IF NOT EXISTS grant_opportunities_cost_share_idx ON grant_opportunities (cost_sharing_or_matching_required);

-- ------------------------------------------------------------
-- irs_990_index: support querying by submission year (e.g. "show me 2024-filed orgs")
-- ------------------------------------------------------------
-- The existing batch_zip column already holds the XML_BATCH_ID (e.g.
-- "2024_TEOS_XML_01A") for 2024 rows — the importer maps the CSV's
-- XML_BATCH_ID column into batch_zip and the ZIP URL is built from it.
-- The only new index we need is on submission_year for the "filed
-- since X" queries that Phase 4 dataset browse views will expose.
CREATE INDEX IF NOT EXISTS irs_990_index_submission_year_idx ON irs_990_index (submission_year DESC);

-- ============================================================
-- Phase 1 migration: SAM.gov Assistance Listings (CFDA catalog)
-- ============================================================
-- The federal "Assistance Listings" (formerly CFDA) catalog — every
-- federal grant program with its objectives, eligibility text, funding
-- range, and examples of funded projects. ~8,000 programs.
-- Used as an ENRICHMENT join against grant_opportunities.cfda_number
-- (see Phase 3) so the LLM extractor sees program-level context.
--
-- Source CSV: AssistanceListings_DataGov_PUBLIC_CURRENT.csv
-- The free-text fields are large (some 30k+ chars) so all kept as TEXT.
CREATE TABLE IF NOT EXISTS sam_cfda_listings (
  program_number                    TEXT PRIMARY KEY,
  program_title                     TEXT,
  popular_name                      TEXT,
  federal_agency                    TEXT,
  parent_shortname                  TEXT,
  authorization_text                TEXT,
  objectives                        TEXT,
  types_of_assistance               TEXT,
  uses_and_restrictions             TEXT,
  applicant_eligibility             TEXT,
  beneficiary_eligibility           TEXT,
  credentials_documentation         TEXT,
  preapplication_coordination       TEXT,
  application_procedures            TEXT,
  award_procedure                   TEXT,
  deadlines                         TEXT,
  range_of_approval_time            TEXT,
  appeals                           TEXT,
  renewals                          TEXT,
  formula_and_matching_requirements TEXT,
  length_and_time_phasing           TEXT,
  reports                           TEXT,
  audits                            TEXT,
  records                           TEXT,
  account_identification            TEXT,
  obligations                       TEXT,
  range_and_average_assistance      TEXT,
  program_accomplishments           TEXT,
  regulations_guidelines_literature TEXT,
  regional_or_local_office          TEXT,
  headquarters_office               TEXT,
  website_address                   TEXT,
  related_programs                  TEXT,
  examples_of_funded_projects       TEXT,
  criteria_for_selecting_proposals  TEXT,
  recovery                          TEXT,
  url                               TEXT,
  published_date                    DATE,
  imported_at                       TIMESTAMPTZ DEFAULT NOW(),
  updated_at                        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS sam_cfda_federal_agency_idx ON sam_cfda_listings (federal_agency);
CREATE INDEX IF NOT EXISTS sam_cfda_parent_shortname_idx ON sam_cfda_listings (parent_shortname);

-- ============================================================
-- Phase 3 migration: org-profile filter fields
-- ============================================================
-- New columns let the discovery pre-filter narrow the ~1M discovery_funders /
-- 4.6k grant_opportunities pool down to a candidate set that matches the
-- organisation's geographic scope, sector, applicant type, grant-size window,
-- and policy on unsolicited proposals.
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS ntee_codes          TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS service_states      TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS applicant_types     TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS accepts_unsolicited BOOLEAN DEFAULT TRUE;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS can_cost_share      BOOLEAN DEFAULT TRUE;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS min_grant_size      BIGINT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS max_grant_size      BIGINT;

-- ============================================================
-- Phase 5 migration (auto-discovery quality rebuild — 2026-05-29)
-- ============================================================
-- Per-org topic filter selectors used by filter_opportunities() and the
-- per-foundation gate state cache used by the rebuilt foundation pipeline.

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS cfda_categories          TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS eligible_applicant_codes TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS category_suggestion_notes TEXT;

ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS accepts_unsolicited BOOLEAN;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS no_grants_page      BOOLEAN DEFAULT FALSE;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS grants_page_url     TEXT;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS gate_reason         TEXT;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS gate_evaluated_at   TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_discovery_funders_no_grants_page
    ON discovery_funders (no_grants_page)
    WHERE no_grants_page IS TRUE;

-- ============================================================
-- Phase 9 migration (structured organisation profile — 2026-05-30)
-- ============================================================
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS org_type_description     TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS service_area_description TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS beneficiaries            TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS programs                 TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS income_sources           TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS currency                 TEXT DEFAULT 'USD';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS founded_year             INT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS target_outcomes          TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS partner_orgs             TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS accreditations           TEXT[] DEFAULT '{}';

-- ============================================================
-- Phase 10 migration (geography rework + eligibility rubric — 2026-06-01)
-- ============================================================
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS country           TEXT DEFAULT 'US';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS service_countries TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS service_regions   JSONB DEFAULT '{}';
ALTER TABLE funds         ADD COLUMN IF NOT EXISTS match_rubric      JSONB;

-- ============================================================
-- Security: enable Row-Level Security on all public tables (2026-06-01)
-- ============================================================
-- Resolves the Supabase Security Advisor "rls_disabled_in_public" warnings.
-- Enabling RLS with no policies = deny-all for the public `anon` /
-- `authenticated` roles, so the public anon key (shipped in the frontend
-- bundle) can no longer read/write/delete tables via the Data API
-- (PostgREST). The backend uses the SERVICE_ROLE key (BYPASSRLS), so all
-- server-side queries are unaffected; the frontend only uses supabase.auth
-- and never touches tables directly. See config/migration_rls.sql for the
-- full rationale. Idempotent + existence-guarded.
DO $$
DECLARE
    tbl TEXT;
    target_tables TEXT[] := ARRAY[
        'funds', 'scrape_jobs', 'scrape_job_urls', 'organizations',
        'user_profiles', 'api_tokens', 'irs_990_index',
        'irs_990_index_refresh', 'documents', 'discovery_funders',
        'grant_opportunities', 'sam_cfda_listings'
    ];
BEGIN
    FOREACH tbl IN ARRAY target_tables
    LOOP
        IF to_regclass(format('public.%I', tbl)) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', tbl);
        END IF;
    END LOOP;
END
$$;
