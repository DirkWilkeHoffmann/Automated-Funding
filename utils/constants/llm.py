"""LLM-related constants and prompts."""

ELIGIBILITY_ORDER = [
    "Highly Eligible",
    "Eligible",
    "Possibly Eligible",
    "Low Match",
    "Not Eligible",
]

# Dimensions evaluated by the structured eligibility rubric. The five marked
# VETO are hard-fail: a `mismatch` on any of them forces "Not Eligible"
# regardless of how well other dimensions score.
RUBRIC_DIMENSIONS = [
    "geography",         # VETO — fund's geo scope ∩ org's countries+regions
    "applicant_type",    # VETO — fund's accepted types ∩ org's legal status
    "topic_focus",       # non-veto — fund's focus areas ∩ org's mission
    "beneficiary",       # non-veto — fund's intended beneficiaries ∩ org's beneficiaries
    "org_history",       # VETO — minimum-years requirement vs org's founding year
    "grant_size",        # non-veto — fund's range vs org's needed range
    "cost_share",        # VETO — matching-fund requirement vs org's capability
    "explicit_exclusion",# VETO — explicit restriction barring this org
]

VETO_DIMENSIONS = {
    "geography", "applicant_type", "org_history", "cost_share", "explicit_exclusion",
}

RUBRIC_VERDICTS = {"match", "partial", "mismatch", "unknown"}


LLM_SYSTEM_PROMPT = (
    "You are a senior grant analyst. Your evaluations are relied upon to decide which funding opportunities are worth the staff time to pursue — accuracy matters above all else. "
    "Rules you must follow: "
    "(1) For formal RFPs, NOFAs, and published grant guidelines: base conclusions only on text actually present — never invent criteria not in the text. "
    "(2) For private or community foundation websites: use stated grantmaking focus areas, geographic language, and PAST GRANTEE EXAMPLES to infer eligibility. Past grantees are first-class evidence — if the funder has supported orgs with overlapping mission and applicant type, that proves the funder accepts orgs like yours; quote one or two grantee names in your evidence. "
    "(3) EXTRACTION RULE — ALWAYS extract every field that is present in the source text, regardless of grant type. Actively SEARCH the text for: deadline dates (look for 'Deadline:', 'Closes:', 'Apply by:', 'Due date:', 'Submission deadline:', specific dates), funding ranges (look for currency symbols, 'up to', 'awards of', 'grant size'), application status (open/closed/rolling), contact info. Extraction is INDEPENDENT of rating. Only emit 'Not stated' when the field genuinely does not appear anywhere in the text. "
    "(4) RUBRIC RULE — score 7 of the 8 rubric dimensions yourself: applicant_type, topic_focus, beneficiary, org_history, grant_size, cost_share, explicit_exclusion. Use verdict ∈ {match, partial, mismatch, unknown} with a one-sentence evidence quote. Be honest — `unknown` is correct when the fund text doesn't state the requirement. "
    "(5) VETO RULE — four veto dimensions for you to score: applicant_type, org_history, cost_share, explicit_exclusion. A `mismatch` on ANY of these means 'Not Eligible'. "
    "(6) GEOGRAPHY — always emit `\"verdict\": \"unknown\"` for the geography rubric dimension. Geography is computed programmatically by the system from the geographic_scope you extract — your verdict is ignored and overridden. Focus instead on extracting the geographic_scope text accurately and completely (include province/region names AND the country name). "
    "(7) Quote or closely paraphrase phrases from the source text (including any 990 data) as evidence. "
    "(8) Always give a clear, actionable recommendation. Be country-agnostic — the org may operate in any combination of countries, and that is fully valid. "
    "(9) APPLICANT TYPE — MULTI-COUNTRY REGISTRATIONS: The org's `Applicant types` field lists its primary registration (often US-centric). Many international nonprofits hold additional country-specific registrations that appear in the `Legal registrations / accreditations` field or in the Mission text. Before scoring applicant_type: "
    "(a) Read the `Legal registrations / accreditations` field first — 'NPO' = South African Non-Profit Organisation, 'charity' = UK/AU registered charity, 'ngo' = generic international NGO, etc. "
    "(b) Cross-reference with service_countries: if the org lists 'South Africa' in service_countries AND holds 'NPO' in its registrations, it qualifies as a South African NPO for fund purposes. "
    "(c) Only score `mismatch` for hard exclusions — e.g., the fund is 'for-profit entities only', 'government agencies only', or explicitly bars foreign-registered orgs. A locale-specific type label (e.g., 'South African NPO') does NOT by itself imply mismatch when the org's registrations cover that locale."
)


# Phase 2 fires for any tier in this set. "Not Eligible" is excluded — hard
# vetoes (geography, for-profit-only, etc.) don't need enrichment. Everything
# else gets the full details pass so operators always see the rich evidence
# panel regardless of how the fund scored.
PHASE2_PROMOTE_TIERS = {"Highly Eligible", "Eligible", "Possibly Eligible", "Low Match"}


LLM_PROMPT = """Evaluate the funding opportunity below against the organisation profile provided. Extract structured data, score each rubric dimension, then assess overall eligibility.

=== APPLICANT ORGANISATION ===
{org_profile}

=== ELIGIBILITY SCALE — use EXACTLY one of these five values ===

"Highly Eligible"   — All veto dimensions match AND ≥6 of 8 total match. Strong fit; pursue confidently.
"Eligible"          — All veto dimensions match AND ≥3 of 8 total match. Worth pursuing with standard effort.
"Possibly Eligible" — All veto dimensions match AND only 2 of 8 match (rest partial/unknown). Worth verifying before investing time.
"Low Match"         — No veto mismatch, but fewer than 2 dimensions match. Topical fit is weak.
"Not Eligible"      — ANY veto dimension (geography, applicant_type, org_history, cost_share, explicit_exclusion) is `mismatch`.

IMPORTANT — extraction vs. rubric (two SEPARATE concerns):

A. EXTRACTION (always do this, regardless of grant type):
   You MUST extract the deadline, funding_range, application_status, applicant_types, restrictions, etc. whenever those values appear in the source text. If the page contains "Deadline: 28-Aug-2025" you MUST emit deadline="28-Aug-2025". Use "Not stated" ONLY when the value genuinely does not appear anywhere.

B. RUBRIC SCORING (score 7 dimensions yourself; geography is auto-computed):
   Score applicant_type, topic_focus, beneficiary, org_history, grant_size, cost_share, explicit_exclusion.
   For geography: always emit `"unknown"` — the system overrides this with a programmatic check.
   Be honest — `unknown` is correct when the fund text doesn't state the requirement.

=== GEOGRAPHIC SCOPE EXTRACTION (critical for the system's geography check) ===
Extract the fund's geographic scope as completely as possible into the `geographic_scope` field.
Include BOTH the province/region names AND the country name when both appear.
Examples of good extraction:
  • "Eastern Cape, Northern Cape, and Western Cape, South Africa" ← include the country
  • "Georgia and Florida, United States" ← include the country
  • "South Africa" ← country-level is fine when no regions specified
  • "Nationwide" / "Global" / "Not stated" ← for broad or unstated scope
Do NOT drop the country name. Do NOT omit region names.

=== EVALUATION CRITERIA (these feed the rubric) ===
1. Applicant type — fund's accepted applicant types ∩ org's legal status (501c3, charity, NPO, etc.)
2. Geography — auto-computed by system; emit "unknown" in the rubric.
3. Topic / focus — fund's stated topic areas ∩ org's mission / programs / CFDA categories.
4. Beneficiary — fund's target beneficiaries ∩ org's beneficiaries served.
5. Org history / age — does the fund require minimum years of operation? Does the org meet it? (Use 'unknown' if fund doesn't say.)
6. Grant size — fund's grant range vs org's needed range (if both stated).
7. Cost-share — does the fund require matching funds? Can the org provide?
8. Explicit exclusion — any explicit restriction barring this org (e.g., "no faith-based", "schools only").

=== GRANT PAGE TEXT (may include IRS 990 structured data) ===
{text}
=== END OF GRANT PAGE TEXT ===

=== OUTPUT ===
Return ONLY a valid JSON object. ALL 13 fields are required.

{{
  "applicant_types": ["501(c)(3) nonprofits", "workforce development organisations"],
  "geographic_scope": "EXTRACT the full geographic scope including region AND country names (e.g. 'Eastern Cape, Northern Cape, South Africa' or 'Georgia, United States' or 'South Africa' or 'Nationwide'). Never drop the country name when it appears.",
  "us_state_scope": ["GA", "FL"],
  "beneficiary_focus": ["unemployed adults", "low-income individuals"],
  "funding_range": "EXTRACT explicit amounts when present (e.g. '$10,000-$100,000', 'up to £50,000', 'R 24,000,000'). 'Not stated' ONLY if no amount appears anywhere.",
  "restrictions": ["must be US-based only", "no faith-based organisations"],
  "application_status": "MUST be one of: open|closed|paused|rolling|seasonal|unclear. Use 'unclear' if no signal.",
  "deadline": "EXTRACT the date when it appears (e.g. '28-Aug-2025', '2026-06-01'). 'Rolling' for ongoing. 'Not stated' ONLY if no date appears anywhere.",
  "notes": "application process, required attachments, contact details, or other requirements not captured above",
  "grant_type": "federal | foundation | corporate | community | other",
  "rubric": {{
    "geography":          {{"verdict": "unknown", "evidence": "system-computed — always emit unknown here"}},
    "applicant_type":     {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}},
    "topic_focus":        {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}},
    "beneficiary":        {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}},
    "org_history":        {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}},
    "grant_size":         {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}},
    "cost_share":         {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}},
    "explicit_exclusion": {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}}
  }},
  "eligibility": "Highly Eligible | Eligible | Possibly Eligible | Low Match | Not Eligible",
  "evidence": "VERDICT: [eligibility tier] — [one sentence reason citing the most decisive rubric dimension(s)]"
}}

Rules for the rubric:
- geography verdict MUST always be "unknown" — system overrides it.
- VETO (your 4 veto dimensions): if ANY of applicant_type, org_history, cost_share, explicit_exclusion is `mismatch` → eligibility MUST be "Not Eligible".
- `unknown` is correct when the fund text doesn't state the requirement. Never guess.
- Quote source text in evidence when possible.

Return ONLY the JSON object. Keep the evidence field to a SINGLE LINE — detailed analysis happens in a separate pass."""


LLM_PROMPT_PHASE2 = """You previously evaluated this funding opportunity for the applicant organisation below and reached the verdict shown. Your job NOW is to produce the detailed analysis a fundraiser needs to actually pursue this grant. Do not contradict or re-rate the verdict — this pass adds depth, it does not re-judge.

=== APPLICANT ORGANISATION ===
{org_profile}

=== GRANT PAGE TEXT (may include IRS 990 structured data) ===
{text}
=== END OF GRANT PAGE TEXT ===

=== YOUR PRIOR VERDICT ===
{phase1_verdict_line}

=== TASK ===
Return ONLY a JSON object with EXACTLY these keys:

{{
  "why_it_fits": [
    "[match #1 — quote verbatim from the source text where possible]",
    "[match #2 — quote where possible]",
    "[match #3 — only if a genuine third reason exists; otherwise omit]"
  ],
  "past_grantees": [
    {{"name": "Grantee Name", "amount": "$1,500,000 or 'amount not stated'", "project": "one-line description of their funded project"}}
  ],
  "typical_grant_size": "string — explicit range if stated, otherwise inferred from past grantees, e.g. 'Grants $500K-$7M based on listed past awards'. Use 'Not inferable from page' if no signal.",
  "application_process": "1-3 sentences. What does the applicant actually DO to apply? LOI first? Online portal? Pre-call required? Any specific limits? If process not stated, say so and suggest contacting the funder directly.",
  "strategic_angle": "1-2 sentences. How should THIS applicant position their proposal given the funder's stated priorities and past-grantee patterns?",
  "concerns": [
    "[real mismatch concern only — wrong applicant type, geography, topic, or explicit exclusion. NEVER list 'funding range not stated' or 'application details not stated' as a concern for foundation pages.]"
  ],
  "next_step": "ONE specific actionable sentence the applicant can do today. Avoid vague advice like 'review the guidelines'."
}}

Rules:
- Quote verbatim phrases from the grant text where it makes the evidence credible.
- For past_grantees, return up to 3 entries most similar to the applicant. Return [] if no comparable past grantees are visible.
- For concerns, return [] if there are no real mismatches.
- Be CONCRETE. Every sentence should be actionable.

Return ONLY the JSON object."""
