-- ============================================================
-- Phase 11 migration: Match-Quality & Targeting Engine
-- ============================================================
-- Demand-driven discovery foundation: enables pgvector, enriches the funder
-- knowledge base with 990 program-areas/grantees, adds embeddings for vector
-- search, the per-client targeting profile, and pending_urls maybe-bucket
-- metadata. See docs/superpowers/specs/2026-06-09-match-quality-targeting-engine-design.md
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Funder knowledge base enrichment ─────────────────────────────────────────
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS program_areas    TEXT[];
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS top_grantees     JSONB;     -- [{name, amount, purpose}]
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS grantee_purposes TEXT;      -- concatenated purpose text (embedded)
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS embedding        vector(1536);
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS enriched_at      TIMESTAMPTZ;  -- 990 parsed + fields set
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS embedded_at      TIMESTAMPTZ;  -- embedding computed

CREATE INDEX IF NOT EXISTS discovery_funders_embedding_idx
  ON discovery_funders USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS discovery_funders_enrich_queue_idx
  ON discovery_funders (enriched_at) WHERE enriched_at IS NULL;

-- ── Federal opportunity embeddings ───────────────────────────────────────────
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS embedding   vector(1536);
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS grant_opportunities_embedding_idx
  ON grant_opportunities USING hnsw (embedding vector_cosine_ops);

-- ── Client targeting profile ─────────────────────────────────────────────────
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS cause_keywords       TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS targeting_confirmed  BOOLEAN DEFAULT FALSE;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS client_embedding     vector(1536);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS targeting_updated_at TIMESTAMPTZ;

-- ── pending_urls maybe-bucket metadata ───────────────────────────────────────
ALTER TABLE pending_urls ADD COLUMN IF NOT EXISTS funder_name      TEXT;
ALTER TABLE pending_urls ADD COLUMN IF NOT EXISTS discovery_source TEXT;
ALTER TABLE pending_urls ADD COLUMN IF NOT EXISTS match_score      REAL;
ALTER TABLE pending_urls ADD COLUMN IF NOT EXISTS match_reason     TEXT;
