"""Funder knowledge-base enrichment.

Progressively parses 990s for discovery_funders rows, persisting program areas
and past grantees, then embeds each funder so it is searchable by the targeting
engine. Geo-scoped to the org(s) actually configured — never enriches the whole
~1M-row table at once.

This module holds pure field-builders (unit-tested) + the batch job entry
point (run_funder_enrichment), wired into the scheduler.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from utils.discovery.embeddings import embed_text

logger = logging.getLogger(__name__)

_BATCH_DEFAULT = 100


# ── Pure field builders ───────────────────────────────────────────────────────


def build_grantee_purposes(summary: Dict[str, Any]) -> str:
    """Concatenate 990 program areas + grantee purposes into embeddable text."""
    parts: List[str] = []
    for area in summary.get("program_areas") or []:
        if area:
            parts.append(str(area))
    for g in summary.get("top_grantees") or []:
        if isinstance(g, dict):
            purpose = (g.get("purpose") or "").strip()
            if purpose:
                parts.append(purpose)
    return " | ".join(parts).strip()


def build_embedding_input(row: Dict[str, Any], *, grantee_purposes: str) -> str:
    """Build the text we embed for a funder.

    Always includes identity (name + NTEE + location) so funders without a
    parsed 990 are still searchable; appends grant-signal text when available.
    """
    bits: List[str] = []
    if row.get("name"):
        bits.append(str(row["name"]))
    if row.get("ntee_code"):
        bits.append(f"NTEE {row['ntee_code']}")
    loc = " ".join(str(row[k]) for k in ("city", "state") if row.get(k))
    if loc:
        bits.append(loc)
    if grantee_purposes:
        bits.append(grantee_purposes)
    return " | ".join(bits).strip()


# ── 990 lookup + enrichment ───────────────────────────────────────────────────


def select_enrichment_batch(sb, *, states: List[str], limit: int = _BATCH_DEFAULT) -> List[Dict[str, Any]]:
    """Unenriched funders in the given states, richest first."""
    q = sb.table("discovery_funders").select(
        "ein, name, city, state, ntee_code, asset_amount, website"
    ).is_("enriched_at", "null")
    if states:
        q = q.in_("state", [s.upper() for s in states])
    q = q.order("asset_amount", desc=True).limit(limit)
    try:
        return q.execute().data or []
    except Exception as exc:
        logger.warning("select_enrichment_batch failed: %s", exc)
        return []


def _fetch_990_summary(row: Dict[str, Any], sb) -> Dict[str, Any]:
    """Look up the funder's latest 990, parse it, and LLM-extract grant signals.

    Reuses irs_990_index (DB) → irs_990_zips.fetch_multiple_xmls →
    irs_990_parser.xml_to_narrative → llm_utils.extract_from_document('form_990').
    Returns {} when no filing / parse fails.
    """
    from utils.discovery.sources.irs_990_parser import xml_to_narrative
    from utils.discovery.sources.irs_990_zips import fetch_multiple_xmls
    from utils.llm_utils import extract_from_document

    ein = str(row.get("ein") or "").strip()
    if not ein:
        return {}
    try:
        rec = (
            sb.table("irs_990_index")
            .select("object_id, batch_zip, submission_year, tax_year")
            .eq("ein", ein)
            .order("tax_year", desc=True)
            .limit(1)
            .execute()
            .data or []
        )
        if not rec:
            return {}
        r0 = rec[0]
        xmls = fetch_multiple_xmls([(r0["object_id"], r0["batch_zip"], int(r0["submission_year"]))])
        xml = xmls.get(r0["object_id"])
        if not xml:
            return {}
        narrative = xml_to_narrative(xml) or ""
        if not narrative:
            return {}
        return extract_from_document(narrative, "form_990") or {}
    except Exception as exc:
        logger.debug("990 summary failed for ein=%s: %s", ein, exc)
        return {}


def enrich_one(row: Dict[str, Any], *, sb) -> Dict[str, Any]:
    """Build the update payload for a single funder (does not write)."""
    summary = _fetch_990_summary(row, sb)
    purposes = build_grantee_purposes(summary)
    now = datetime.now(timezone.utc).isoformat()
    payload: Dict[str, Any] = {
        "program_areas": summary.get("program_areas") or None,
        "top_grantees": summary.get("top_grantees") or None,
        "grantee_purposes": purposes or None,
        "enriched_at": now,
    }
    vec = embed_text(build_embedding_input(row, grantee_purposes=purposes))
    if vec is not None:
        payload["embedding"] = vec
        payload["embedded_at"] = now
    return payload


def run_funder_enrichment(*, states: List[str] | None = None, limit: int = _BATCH_DEFAULT) -> int:
    """Cron entry point. Enriches up to `limit` funders. Returns count processed."""
    from supabase import create_client
    from utils.config import get_settings
    from utils.discovery.prefilter import load_org_profile

    if states is None:
        states = load_org_profile().effective_states()

    s = get_settings()
    sb = create_client(s.supabase_url, s.supabase_service_key)
    batch = select_enrichment_batch(sb, states=states, limit=limit)
    processed = 0
    for row in batch:
        try:
            payload = enrich_one(row, sb=sb)
            sb.table("discovery_funders").update(payload).eq("ein", row["ein"]).execute()
            processed += 1
        except Exception as exc:
            logger.warning("enrich_one failed for ein=%s: %s", row.get("ein"), exc)
    logger.info("funder_enrichment processed %d funders", processed)
    return processed
