"""LLM-related constants and prompts."""

ELIGIBILITY_ORDER = [
    "Highly Eligible",
    "Eligible",
    "Possibly Eligible",
    "Low Match",
    "Not Eligible",
]

LLM_PROMPT = """
You are a precise information extractor for charity funding opportunities, specifically evaluating eligibility for ellenor Hospice.

=== ELLENOR HOSPICE PROFILE ===
- Name: ellenor Hospice
- Location: Gravesend, Kent, UK (serves Dartford, Gravesham, Swanley, Bexley)
- Services: Palliative and end-of-life care for babies, children, young people, adults, and families
- Core activities: Inpatient Ward, Hospice at Home, Living Well programme, Children's Hospice at Home, Bereavement support, Music/play therapy, Complementary therapies
- Staff: 152 | Volunteers: 333
- Annual income: £8.2M (donations, charitable activities, trading, government grants)
- Type: Registered UK charity providing hospice and palliative care services

=== YOUR TASK ===
Extract funding information AND determine eligibility for ellenor Hospice.

Return ONLY valid JSON with this exact structure:

{
  "applicant_types": ["list", "of", "eligible", "applicant", "types"],
  "geographic_scope": "geographic area covered (e.g., UK, England, Kent, London)",
  "beneficiary_focus": ["target", "beneficiary", "groups"],
  "funding_range": "minimum and maximum amounts if stated (e.g., £1,000 - £10,000)",
  "restrictions": ["explicit", "exclusions", "or", "restrictions"],
  "application_status": "open|closed|paused|rolling|seasonal|unclear",
  "deadline": "application deadline if mentioned",
  "notes": "any other critical eligibility requirements",
  "eligibility": "Highly Eligible|Eligible|Possibly Eligible|Low Match|Not Eligible",
  "evidence": "detailed explanation of eligibility determination with specific reasons"
}

=== EVIDENCE GUIDELINES ===
In the "evidence" field, provide a clear explanation including:
1. Key matching factors
2. Concerns or limitations
3. Specific quotes or facts from the page that support your assessment
4. Overall recommendation

=== PAGE TEXT START ===
{text}
=== PAGE TEXT END ===

Return ONLY the JSON object, no additional text.
"""
