-- ============================================================
-- Phase 12 migration: pgvector RPC functions for targeting engine
-- ============================================================
-- Apply in the Supabase SQL editor (Database → SQL editor).
-- Both functions accept query_embedding as float[] so that supabase-py
-- can pass a regular JSON array of floats; Postgres casts to vector(1536).
-- ============================================================

-- match_funders: cosine-similarity search over discovery_funders
CREATE OR REPLACE FUNCTION match_funders(
    query_embedding float[],
    match_count     int     DEFAULT 50,
    funder_offset   int     DEFAULT 0,
    filter_states   text[]  DEFAULT NULL,
    min_asset_code  int     DEFAULT 1
)
RETURNS TABLE (
    ein              text,
    name             text,
    city             text,
    state            text,
    ntee_code        text,
    asset_amount     bigint,
    website          text,
    program_areas    text[],
    grantee_purposes text,
    similarity       double precision
)
LANGUAGE sql STABLE SECURITY DEFINER
AS $$
    SELECT
        ein,
        name,
        city,
        state,
        ntee_code,
        asset_amount,
        website,
        program_areas,
        grantee_purposes,
        1.0 - (embedding <=> query_embedding::vector) AS similarity
    FROM discovery_funders
    WHERE
        embedding IS NOT NULL
        AND scraped_at IS NULL
        AND asset_code >= min_asset_code
        AND (filter_states IS NULL OR state = ANY(filter_states))
    ORDER BY embedding <=> query_embedding::vector
    LIMIT  match_count
    OFFSET funder_offset;
$$;


-- match_opportunities: cosine-similarity search over grant_opportunities
CREATE OR REPLACE FUNCTION match_opportunities(
    query_embedding float[],
    match_count     int DEFAULT 25,
    opp_offset      int DEFAULT 0
)
RETURNS TABLE (
    opportunity_id text,
    title          text,
    agency         text,
    url            text,
    close_date     date,
    award_ceiling  bigint,
    cfda_number    text,
    category       text,
    similarity     double precision
)
LANGUAGE sql STABLE SECURITY DEFINER
AS $$
    SELECT
        opportunity_id,
        title,
        agency,
        url,
        close_date,
        award_ceiling,
        cfda_number,
        category,
        1.0 - (embedding <=> query_embedding::vector) AS similarity
    FROM grant_opportunities
    WHERE
        embedding IS NOT NULL
        AND close_date >= CURRENT_DATE
        AND scraped_at IS NULL
    ORDER BY embedding <=> query_embedding::vector
    LIMIT  match_count
    OFFSET opp_offset;
$$;
