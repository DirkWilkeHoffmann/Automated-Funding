"""LLM-related constants and prompts."""

ELIGIBILITY_ORDER = [
    "Highly Eligible",
    "Eligible",
    "Possibly Eligible",
    "Low Match",
    "Not Eligible",
]

LLM_SYSTEM_PROMPT = (
    "You are a senior grant analyst specialising in US nonprofit workforce development and economic empowerment funding. "
    "Your evaluations are relied upon to decide which opportunities are worth the staff time to pursue — accuracy matters above all else. "
    "Rules you must follow: "
    "(1) For formal RFPs, NOFAs, and published grant guidelines: base conclusions only on text actually present — never invent criteria not in the text. "
    "(2) For private or community foundation websites WITHOUT published grant guidelines: use their stated grantmaking focus areas, geographic language, and past grantee examples to infer eligibility. "
    "If the foundation funds nonprofits in a relevant topic area AND the geography aligns, rate 'Possibly Eligible' or higher — NOT 'Low Match'. "
    "Reserve 'Not Eligible' only for explicit exclusions (e.g. 'schools only', 'government agencies only', 'no nonprofits'). "
    "'Low Match' means the topical focus clearly does not align — not merely that criteria are unstated. "
    "(3) Apply the eligibility scale consistently using the exact definitions given. "
    "(4) Quote or closely paraphrase phrases from the source text (including any 990 data provided) as evidence. "
    "(5) Always give a clear, actionable recommendation."
)

LLM_PROMPT = """Evaluate the funding opportunity below against the organisation profile provided. Extract structured data and assess eligibility using the calibrated rubric.

=== APPLICANT ORGANISATION ===
{org_profile}

=== ELIGIBILITY SCALE — use EXACTLY one of these five values ===

"Highly Eligible"   — Org type is explicitly accepted, geographic scope matches, and mission is a primary focus of the funder. No significant barriers. Strong fit on 3 or more criteria.
"Eligible"          — Org fits on most criteria (2+) with only minor concerns or ambiguity. Worth pursuing with standard effort.
"Possibly Eligible" — Some alignment exists but there are notable gaps, ambiguous requirements, or only 1 key criterion is met. Verify before investing time.
"Low Match"         — Funding focus, geography, or applicant type is a poor fit, though no explicit exclusion bars the org from applying.
"Not Eligible"      — An explicit restriction, requirement, or exclusion clearly bars this organisation from applying.

IMPORTANT — foundation websites vs. formal RFPs:
Most private and community foundation websites do NOT publish explicit eligibility criteria.
For these pages, infer eligibility from: (a) stated grantmaking focus areas, (b) geographic scope language, (c) past grantee names or types, (d) any IRS Form 990 data included below.
Do NOT rate a foundation "Low Match" or "Not Eligible" simply because explicit criteria are absent.
If the foundation's focus areas overlap with the org's mission and geography plausibly aligns, use "Possibly Eligible" or "Eligible".
Only use "Not Eligible" when text explicitly restricts applicants in a way that bars this org.

=== EVALUATION CRITERIA (in priority order) ===
1. Applicant type: Does the funder explicitly accept 501(c)(3) nonprofits or workforce/employment organisations? For foundations, do past grantees suggest nonprofits are welcome?
2. Geographic scope: Does the grant/foundation cover the organisation's location or service area? If the grant restricts to US-only beneficiaries, assess whether the organisation's US operations qualify rather than treating it as an automatic exclusion.
3. Mission alignment: Does the funder's focus match workforce development, employment training, or economic empowerment?
4. Size and scale: Is the funding range, required budget, or organisational size a fit?
5. Explicit exclusions: Is there any restriction that clearly bars this organisation?

=== GRANT PAGE TEXT (may include IRS 990 structured data) ===
{text}
=== END OF GRANT PAGE TEXT ===

=== OUTPUT ===
Return ONLY a valid JSON object. All 12 fields are required. Use "Not stated" for any field whose value cannot be found in the text above — do not guess or invent values.

{{
  "applicant_types": ["501(c)(3) nonprofits", "workforce development organisations"],
  "geographic_scope": "geographic region funded (e.g., Nationwide, Georgia, Southeast US, or Not stated)",
  "us_state_scope": ["GA", "FL"],
  "beneficiary_focus": ["unemployed adults", "low-income individuals"],
  "funding_range": "$10,000 - $100,000 per award, or Not stated",
  "restrictions": ["must be US-based only", "no faith-based organisations"],
  "application_status": "open|closed|paused|rolling|seasonal|unclear",
  "deadline": "date if stated, Rolling if ongoing, Not stated if absent",
  "notes": "application process, required attachments, contact details, or other requirements not captured in the fields above",
  "grant_type": "federal|foundation|corporate|community|other",
  "eligibility": "Highly Eligible|Eligible|Possibly Eligible|Low Match|Not Eligible",
  "evidence": "VERDICT: [one sentence — eligibility level and primary reason]\\nMATCH:\\n- [factor that aligns — quote from grant text where possible]\\n- [second matching factor]\\nCONCERNS:\\n- [gap, exclusion, or uncertainty — or None identified]\\nRECOMMENDATION: [one actionable sentence]"
}}

Return ONLY the JSON object. No text before or after it."""
