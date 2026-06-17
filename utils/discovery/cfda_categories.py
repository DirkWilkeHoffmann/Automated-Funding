"""Grants.gov "Category of Funding Activity" codes.

Used by the per-org topic filter (Phase 5). The orchestrator narrows the
Grants.gov DB pool to only opportunities tagged with category codes the
operator picked in /admin/organisation.

Reference (Grants.gov XML extract: <FundingActivityCategory>):
    https://www.grants.gov/help/html/help/index.htm

These codes appear in `grant_opportunities.category` (already imported).
"""

from __future__ import annotations

from typing import Dict, List

# Code -> human-readable label. Order is the order shown to operators.
CFDA_CATEGORIES: Dict[str, str] = {
    "ACA":  "Affordable Care Act",
    "AG":   "Agriculture",
    "AR":   "Arts (cultural affairs, dance, design, theatre)",
    "BC":   "Business and Commerce",
    "CD":   "Community Development",
    "CP":   "Consumer Protection",
    "DPR":  "Disaster Prevention and Relief",
    "ED":   "Education",
    "ELT":  "Employment, Labor, and Training",
    "EN":   "Energy",
    "ENV":  "Environment",
    "FN":   "Food and Nutrition",
    "HL":   "Health",
    "HO":   "Housing",
    "HU":   "Humanities (history, philosophy, language, literature)",
    "IIJ":  "Infrastructure Investment and Jobs Act",
    "IS":   "Information and Statistics",
    "ISS":  "Income Security and Social Services",
    "LJL":  "Law, Justice and Legal Services",
    "NR":   "Natural Resources",
    "O":    "Opportunity Zone Benefits",
    "RA":   "Recovery Act",
    "RD":   "Regional Development",
    "ST":   "Science and Technology and other Research and Development",
    "T":    "Transportation",
    "OTHER":"Other / unspecified",
}

# Tuples of (code, label) for deterministic iteration / UI rendering.
CFDA_CATEGORY_CHOICES: List[Dict[str, str]] = [
    {"code": code, "label": label} for code, label in CFDA_CATEGORIES.items()
]


def label_for(code: str) -> str:
    return CFDA_CATEGORIES.get((code or "").upper(), code)


def is_valid(code: str) -> bool:
    return (code or "").upper() in CFDA_CATEGORIES
