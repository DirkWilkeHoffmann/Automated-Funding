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
