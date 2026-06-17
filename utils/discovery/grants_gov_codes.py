"""Grants.gov EligibleApplicants code lookup.

The Grants.gov XML extract stores eligibility as numeric codes (e.g. "25",
"11") in the `EligibleApplicants` field — repeating element, so we persist
as TEXT[]. This module is the canonical mapping from those codes to:

  * human-readable labels (for UI display)
  * normalized applicant-type buckets used by the org profile's
    `applicant_types` field, so the pre-filter can do set intersection

Reference (official Grants.gov data dictionary):
  00  Unrestricted
  01  County governments
  02  City or township governments
  04  Special district governments
  05  Independent school districts
  06  Public and State controlled institutions of higher education
  07  Native American tribal governments (Federally recognized)
  08  Public housing authorities/Indian housing authorities
  10  Other Native American tribal organizations (other than Federally recognized
       tribal governments)
  11  Others (see text field entitled "Additional Information on Eligibility"
       for clarification)
  12  Nonprofits having a 501(c)(3) status with the IRS, other than institutions
       of higher education
  13  Nonprofits that do not have a 501(c)(3) status with the IRS, other than
       institutions of higher education
  20  Private institutions of higher education
  21  Individuals
  22  For-profit organizations other than small businesses
  23  Small businesses
  25  Others (see text field entitled "Additional Information on Eligibility"
       for clarification)
  99  Unrestricted (i.e. open to any type of organization)
"""

from __future__ import annotations

from typing import Dict, List, Set

# code → human-readable label
ELIGIBLE_APPLICANTS_LABELS: Dict[str, str] = {
    "00": "Unrestricted",
    "01": "County governments",
    "02": "City or township governments",
    "04": "Special district governments",
    "05": "Independent school districts",
    "06": "Public and State controlled institutions of higher education",
    "07": "Federally recognized Native American tribal governments",
    "08": "Public housing authorities / Indian housing authorities",
    "10": "Other Native American tribal organizations",
    "11": "Others (see eligibility text)",
    "12": "Nonprofits with 501(c)(3) status",
    "13": "Nonprofits without 501(c)(3) status",
    "20": "Private institutions of higher education",
    "21": "Individuals",
    "22": "For-profit organizations (other than small businesses)",
    "23": "Small businesses",
    "25": "Others (see eligibility text)",
    "99": "Unrestricted",
}

# code → set of normalized applicant-type buckets that match this code.
# An org with `applicant_types = ["501c3"]` should match grants tagged with
# any of the codes in CODE_TO_TYPES that include "501c3".
CODE_TO_TYPES: Dict[str, Set[str]] = {
    "00": {"any"},
    "01": {"government", "local_government", "county"},
    "02": {"government", "local_government", "municipality"},
    "04": {"government", "local_government", "special_district"},
    "05": {"government", "school"},
    "06": {"higher_education", "public_higher_education", "government"},
    "07": {"government", "tribal", "tribal_government"},
    "08": {"government", "housing_authority"},
    "10": {"tribal", "tribal_nonprofit"},
    "11": {"any"},  # broad catch-all; eligibility_text decides
    "12": {"501c3", "nonprofit"},
    "13": {"nonprofit", "non_501c3"},
    "20": {"higher_education", "private_higher_education"},
    "21": {"individual"},
    "22": {"for_profit"},
    "23": {"for_profit", "small_business"},
    "25": {"any"},  # catch-all
    "99": {"any"},
}

# Reverse: human-set applicant types we expose in the UI.
# (For multi-select widgets — keep this list shorter than CODE_TO_TYPES'
# union so the operator doesn't see internal buckets like "municipality".)
SELECTABLE_APPLICANT_TYPES: List[str] = [
    "501c3",
    "nonprofit",
    "fiscal_sponsor",
    "government",
    "tribal",
    "school",
    "higher_education",
    "faith_based",
    "for_profit",
    "individual",
]


def applies_to_org(eligible_codes: List[str], org_applicant_types: List[str]) -> bool:
    """Return True when at least one Grants.gov code maps to a bucket the org claims.

    Args:
        eligible_codes:      list from grant_opportunities.eligible_applicants
        org_applicant_types: list from organizations.applicant_types

    Logic:
        * Org with no `applicant_types` set → accept everything (don't filter)
        * Code "00", "11", "25", "99" → "any" bucket → always matches
        * Otherwise: at least one code's bucket-set must intersect org's types
    """
    if not org_applicant_types:
        return True
    if not eligible_codes:
        # If grant has no eligibility codes at all, fall through to the text
        # filter rather than dropping it.
        return True
    org_set = {t.lower() for t in org_applicant_types}
    for code in eligible_codes:
        buckets = CODE_TO_TYPES.get(str(code).zfill(2), set())
        if "any" in buckets:
            return True
        if buckets & org_set:
            return True
    return False
