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
    "topic_focus",       # VETO — fund's primary domain must overlap with org's mission
    "beneficiary",       # VETO — fund's required population must overlap with org's served population
    "org_history",       # VETO — minimum-years requirement vs org's founding year
    "grant_size",        # non-veto — fund's range vs org's needed range
    "cost_share",        # VETO — matching-fund requirement vs org's capability
    "explicit_exclusion",# VETO — explicit restriction barring this org
]

VETO_DIMENSIONS = {
    "geography", "applicant_type", "topic_focus", "beneficiary", "org_history", "cost_share", "explicit_exclusion",
}

RUBRIC_VERDICTS = {"match", "partial", "mismatch", "unknown"}


LLM_SYSTEM_PROMPT = (
    "You are a senior grant analyst. Your evaluations are relied upon to decide which funding opportunities are worth the staff time to pursue — accuracy matters above all else. "
    "Rules you must follow: "
    "(1) For formal RFPs, NOFAs, and published grant guidelines: base conclusions only on text actually present — never invent criteria not in the text. "
    "(2) For private or community foundation websites: use stated grantmaking focus areas, geographic language, and PAST GRANTEE EXAMPLES to infer eligibility. Past grantees are first-class evidence — if the funder has supported orgs with overlapping mission and applicant type, that proves the funder accepts orgs like yours; quote one or two grantee names in your evidence. "
    "(3) EXTRACTION RULE — ALWAYS extract every field that is present in the source text, regardless of grant type. Actively SEARCH the text for: deadline dates (look for 'Deadline:', 'Closes:', 'Apply by:', 'Due date:', 'Submission deadline:', specific dates), funding ranges (look for currency symbols, 'up to', 'awards of', 'grant size'), application status (open/closed/rolling), contact info. Extraction is INDEPENDENT of rating. Only emit 'Not stated' when the field genuinely does not appear anywhere in the text. "
    "(4) RUBRIC RULE — score 7 of the 8 rubric dimensions yourself: applicant_type, topic_focus, beneficiary, org_history, grant_size, cost_share, explicit_exclusion. Use verdict ∈ {match, partial, mismatch, unknown} with a one-sentence evidence quote. Be honest — `unknown` is correct when the fund text doesn't state the requirement. "
    "(5) VETO RULE — six veto dimensions for you to score: applicant_type, topic_focus, beneficiary, org_history, cost_share, explicit_exclusion. A `mismatch` on ANY of these means 'Not Eligible'. "
    "topic_focus scoring — the PRIMARY domain of the fund must be workforce development, employment, or economic mobility for this org: "
    "`mismatch` when the fund's PRIMARY subject belongs to a different field — heritage/culture/maritime, fire/disaster management, housing/homeownership rehab, healthcare/medical, arts, conservation/environment, agriculture, infrastructure. IMPORTANT: a fund that incidentally mentions 'education', 'training', or 'local employment' within an otherwise unrelated program (e.g. fire safety training, maritime heritage education, housing counseling) does NOT qualify as topic overlap — score `mismatch`. "
    "`partial` ONLY when the fund explicitly names workforce development, job placement, vocational training, or economic mobility as a CENTRAL (not peripheral) program element — e.g. a community development fund whose stated purposes include 'job training and workforce readiness programs'. "
    "`match` when workforce development, employment services, or economic opportunity for working-age adults is the fund's primary or stated purpose. "
    "beneficiary scoring: `mismatch` when the fund's required population is incompatible with the org's (e.g. maritime heritage audiences, fire-prone homeowners, housing rehab recipients, children with disabilities vs. unemployed adults). Use `partial` when populations meaningfully overlap (e.g. fund targets 'low-income adults' broadly). "
    "(6) GEOGRAPHY — always emit `\"verdict\": \"unknown\"` for the geography rubric dimension. Geography is computed programmatically by the system from the geographic_scope you extract — your verdict is ignored and overridden. Focus instead on extracting the geographic_scope text accurately and completely (include province/region names AND the country name). "
    "(7) Quote or closely paraphrase phrases from the source text (including any 990 data) as evidence. "
    "(8) Always give a clear, actionable recommendation. Be country-agnostic — the org may operate in any combination of countries, and that is fully valid. "
    "(9) APPLICANT TYPE — MULTI-COUNTRY REGISTRATIONS: The org's `Applicant types` field lists its primary registration (often US-centric). Many international nonprofits hold additional country-specific registrations that appear in the `Legal registrations / accreditations` field or in the Mission text. Before scoring applicant_type: "
    "(a) Read the `Legal registrations / accreditations` field first — 'NPO' = South African Non-Profit Organisation, 'charity' = UK/AU registered charity, 'ngo' = generic international NGO, etc. "
    "(b) Cross-reference with service_countries: if the org lists 'South Africa' in service_countries AND holds 'NPO' in its registrations, it qualifies as a South African NPO for fund purposes. "
    "(c) Only score `mismatch` for hard exclusions — e.g., the fund is 'for-profit entities only', 'government agencies only', or explicitly bars foreign-registered orgs. A locale-specific type label (e.g., 'South African NPO') does NOT by itself imply mismatch when the org's registrations cover that locale."
)


LLM_PROMPT_STAGE1 = """Extract structured facts from the funding opportunity text below.

YOUR ONLY JOB IS EXTRACTION. Do not evaluate eligibility. Do not reference any applicant organisation.

=== GRANT PAGE TEXT ===
{text}
=== END OF GRANT PAGE TEXT ===

Return ONLY a valid JSON object with EXACTLY these keys:

{{
  "fund_name": "Name of this specific grant or fund programme (not the funder organisation name). Empty string if not stated.",
  "funder_name": "Name of the organisation offering the grant. Empty string if not found.",
  "geographic_scope": "Full geographic scope including BOTH sub-region names AND country name when both appear. Examples: 'Eastern Cape, Western Cape, South Africa' | 'Georgia, United States' | 'Global' | 'Not stated'. Never drop the country name when it appears.",
  "us_state_scope": ["TX", "CA"],
  "applicant_types": ["registered charities", "NGOs"],
  "topic_areas": ["education", "vocational training", "economic development"],
  "beneficiaries": ["unemployed youth", "low-income families"],
  "funding_range": "Explicit amounts if stated (e.g. '$10,000-$50,000', 'up to R500,000'). 'Not stated' ONLY if no amount appears.",
  "deadline": "Application deadline if stated (e.g. '30-Apr-2026', 'rolling'). 'Not stated' ONLY if no date appears.",
  "application_status": "MUST be one of: open|closed|paused|rolling|seasonal|unclear",
  "restrictions": ["must be locally registered", "no faith-based organisations"],
  "grant_type": "federal | foundation | corporate | community | other",
  "application_process": "How to apply — portal, LOI, email, invitation only, etc. Empty string if not stated.",
  "notes": "Any other relevant facts. Empty string if none."
}}

RULES:
- Extract ONLY what is EXPLICITLY STATED in the text above.
- If a field does not appear, use an empty string or empty array. Do NOT guess or infer.
- The example values above are ILLUSTRATIVE ONLY — replace every field with what the text actually says.
- Do NOT include any information about an applicant organisation.
- Return ONLY the JSON object. No explanation."""


LLM_PROMPT_STAGE2 = """Evaluate whether the funding opportunity described below is a good fit for the applicant organisation. You have been given pre-extracted fund facts — do NOT attempt to re-extract from raw text.

=== APPLICANT ORGANISATION ===
{org_profile}

=== APPLICANT TYPE RULES ===
The org holds these registrations: 501(c)(3) [US federal nonprofit] and NPO [South African Non-Profit Organisation].
When scoring applicant_type:
- A fund open to "nonprofits", "501(c)(3)", "charities", "NGOs", "civil society", or "NPOs" → org QUALIFIES (match).
- Score `mismatch` ONLY for hard exclusions: "for-profit only", "government agencies only", or explicit bars on foreign-registered orgs.
- A locale-specific label (e.g. "South African NPO") does NOT by itself imply mismatch when the org's accreditations cover that locale.

=== PRE-EXTRACTED FUND FACTS ===
Fund name: {fund_name}
Funder: {funder_name}
Geographic scope (raw text): {geographic_scope}
Geography verdict (system-computed — copy verbatim into rubric): {geo_verdict_text}
Applicant types accepted: {applicant_types}
Topic areas: {topic_areas}
Beneficiaries: {beneficiaries}
Funding range: {funding_range}
Application status: {application_status}
Restrictions: {restrictions}
Grant type: {grant_type}
=== END OF FUND FACTS ===

=== ELIGIBILITY SCALE ===
"Highly Eligible"   — No veto mismatch AND ≥6 of 8 dimensions match.
"Eligible"          — No veto mismatch AND ≥3 match (≤1 non-veto mismatch).
"Possibly Eligible" — No veto mismatch AND 2 match.
"Low Match"         — No veto mismatch, fewer than 2 match.
"Not Eligible"      — ANY veto dimension is `mismatch`.
Veto dimensions: geography, applicant_type, topic_focus, beneficiary, org_history, cost_share, explicit_exclusion.
Note on topic_focus: `mismatch` when the fund's PRIMARY domain is NOT workforce development — heritage/culture, fire/disaster management, housing rehab, healthcare, arts, conservation, agriculture. A fund that incidentally mentions 'training', 'education', or 'local employment' within an otherwise unrelated program (fire safety training, maritime education, housing counseling) is NOT a match — score `mismatch`. Use `partial` ONLY when the fund explicitly names job training, workforce development, or economic mobility as a CENTRAL program element. Use `match` when the fund's primary purpose is employment or economic opportunity.
Note on beneficiary: `mismatch` when the fund's REQUIRED population is incompatible with the org's (maritime heritage audiences, fire-prone homeowners, housing rehab recipients vs. unemployed adults). Use `partial` when populations meaningfully overlap (e.g. 'low-income adults broadly').

Score EXACTLY 7 rubric dimensions. Geography verdict is pre-computed above — emit it verbatim.

Return ONLY a valid JSON object:

{{
  "rubric": {{
    "geography":          {{"verdict": "unknown", "evidence": "system-computed — see geography verdict above"}},
    "applicant_type":     {{"verdict": "match|partial|mismatch|unknown", "evidence": "one-sentence quote from fund facts"}},
    "topic_focus":        {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}},
    "beneficiary":        {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}},
    "org_history":        {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}},
    "grant_size":         {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}},
    "cost_share":         {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}},
    "explicit_exclusion": {{"verdict": "match|partial|mismatch|unknown", "evidence": "..."}}
  }},
  "eligibility": "Highly Eligible | Eligible | Possibly Eligible | Low Match | Not Eligible",
  "evidence": "VERDICT: [tier] — [one sentence citing the most decisive rubric dimension(s)]"
}}

Return ONLY the JSON object."""


# Phase 2 enrichment fires only for tiers worth pursuing.
# "Low Match" and "Not Eligible" are excluded — not worth the API cost.
PHASE2_PROMOTE_TIERS = {"Highly Eligible", "Eligible", "Possibly Eligible"}


LLM_PROMPT = """Evaluate the funding opportunity below against the organisation profile provided. Extract structured data, score each rubric dimension, then assess overall eligibility.

=== APPLICANT ORGANISATION ===
{org_profile}

=== ELIGIBILITY SCALE — use EXACTLY one of these five values ===

"Highly Eligible"   — All veto dimensions match AND ≥6 of 8 total match. Strong fit; pursue confidently.
"Eligible"          — All veto dimensions match AND ≥3 of 8 total match. Worth pursuing with standard effort.
"Possibly Eligible" — All veto dimensions match AND only 2 of 8 match (rest partial/unknown). Worth verifying before investing time.
"Low Match"         — No veto mismatch, but fewer than 2 dimensions match. Topical fit is weak.
"Not Eligible"      — ANY veto dimension (geography, applicant_type, topic_focus, beneficiary, org_history, cost_share, explicit_exclusion) is `mismatch`.

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
- VETO (your 6 veto dimensions): if ANY of applicant_type, topic_focus, beneficiary, org_history, cost_share, explicit_exclusion is `mismatch` → eligibility MUST be "Not Eligible".
- topic_focus: `mismatch` when the fund's PRIMARY domain is NOT workforce development — this includes heritage/maritime/culture, fire/disaster management, housing/homeownership rehab, healthcare, arts, conservation, agriculture, infrastructure. A fund that incidentally mentions 'education', 'training', or 'employment' within a program about fire safety, maritime history, or housing rehab is NOT a topic match — score `mismatch`. Use `partial` ONLY when workforce development, job placement, or vocational training is an explicit named program element (not a side-effect). Use `match` when the fund's primary purpose is workforce development, employment, or economic opportunity.
- beneficiary: `mismatch` when the fund's REQUIRED beneficiary population is incompatible with the org's (e.g. maritime heritage audiences, fire-prone homeowners, housing rehab recipients vs. unemployed adults seeking employment). Use `partial` when populations meaningfully overlap (e.g. 'low-income adults broadly').
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
