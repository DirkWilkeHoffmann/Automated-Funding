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
