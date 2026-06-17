"""Parse IRS Form 990 / 990-PF / 990-EZ XML for grant-seeker signals.

The IRS e-File XML namespace is `http://www.irs.gov/efile`. We extract the
elements most useful to a nonprofit researching a funder:

  • Mission and program accomplishments (narrative)
  • Grants paid this year (recipient name, amount, purpose)
  • Officers / directors / key employees
  • Application submission info (990-PF only — explicit "how to apply" text)
  • Contact info + address

Output is a plain-text narrative — easy to feed to the LLM downstream.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

_NS = {"e": "http://www.irs.gov/efile"}
_NS_URI = "{http://www.irs.gov/efile}"


def _text(el: Optional[ET.Element], path: str) -> str:
    """Find the first descendant matching `path` and return its text."""
    if el is None:
        return ""
    found = el.find(path, _NS)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _find_all(el: Optional[ET.Element], path: str) -> List[ET.Element]:
    if el is None:
        return []
    return el.findall(path, _NS)


def _money(s: str) -> str:
    if not s:
        return ""
    try:
        n = int(float(s))
        return f"${n:,}"
    except (TypeError, ValueError):
        return s


def parse_990_narrative(xml_text: str) -> Dict[str, Any]:
    """Return a structured dict of grant-relevant signals from a 990 XML."""
    if not xml_text:
        return {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("Could not parse 990 XML: %s", exc)
        return {}

    header = root.find("e:ReturnHeader", _NS)
    data = root.find("e:ReturnData", _NS)
    if header is None or data is None:
        return {}

    # Identify return type — drives which sub-elements to look at
    return_type = _text(header, "e:ReturnTypeCd")
    filer = header.find("e:Filer", _NS)
    filer_name = (
        _text(filer, "e:BusinessName/e:BusinessNameLine1Txt")
        or _text(filer, "e:BusinessNameLine1Txt")
    )
    ein = _text(filer, "e:EIN")
    address = _address(filer)

    out: Dict[str, Any] = {
        "return_type": return_type,
        "filer_name": filer_name,
        "ein": ein,
        "address": address,
    }

    # The substantive payload lives in one of these depending on return type
    irs990 = data.find("e:IRS990", _NS)
    irs990pf = data.find("e:IRS990PF", _NS)
    irs990ez = data.find("e:IRS990EZ", _NS)

    if irs990pf is not None:
        out.update(_parse_990pf(irs990pf))
    elif irs990 is not None:
        out.update(_parse_990(irs990, data))
    elif irs990ez is not None:
        out.update(_parse_990ez(irs990ez))

    return out


def _address(filer: Optional[ET.Element]) -> str:
    if filer is None:
        return ""
    us = filer.find("e:USAddress", _NS) or filer.find("e:ForeignAddress", _NS)
    if us is None:
        return ""
    parts = [
        _text(us, "e:AddressLine1Txt"),
        _text(us, "e:CityNm"),
        _text(us, "e:StateAbbreviationCd") or _text(us, "e:ProvinceOrStateNm"),
        _text(us, "e:ZIPCd") or _text(us, "e:ForeignPostalCd"),
    ]
    return ", ".join(p for p in parts if p)


def _parse_990(irs990: ET.Element, data: ET.Element) -> Dict[str, Any]:
    """Form 990 — operating charities; mission + program accomplishments + grants."""
    out: Dict[str, Any] = {}
    out["mission"] = (
        _text(irs990, "e:MissionDesc")
        or _text(irs990, "e:ActivityOrMissionDesc")
        or _text(irs990, "e:DescriptionProgramSrvcAccomTxt")
    )

    # Program service accomplishments (top 3)
    accomplishments: List[Dict[str, str]] = []
    for grp in _find_all(irs990, "e:ProgramServiceAccomplishmentGrp")[:3]:
        accomplishments.append({
            "description": _text(grp, "e:Desc") or _text(grp, "e:ActivityCd"),
            "expenses": _money(_text(grp, "e:ExpenseAmt")),
            "grants": _money(_text(grp, "e:GrantAmt")),
            "revenue": _money(_text(grp, "e:RevenueAmt")),
        })
    out["program_accomplishments"] = accomplishments

    # Officers / directors
    officers: List[Dict[str, str]] = []
    for grp in _find_all(irs990, "e:Form990PartVIISectionAGrp")[:8]:
        name = _text(grp, "e:PersonNm") or _text(grp, "e:BusinessName/e:BusinessNameLine1Txt")
        title = _text(grp, "e:TitleTxt")
        if name:
            officers.append({"name": name, "title": title})
    out["officers"] = officers

    # Grants — Schedule I lives as a sibling of IRS990 under ReturnData
    out["grants"] = _parse_schedule_i_grants(data)

    return out


def _parse_990pf(irs990pf: ET.Element) -> Dict[str, Any]:
    """Form 990-PF — private foundations; richest source of grant signals.

    The "how to apply" instructions live here in plain text — uniquely valuable.
    """
    out: Dict[str, Any] = {}

    # Mission / activity summary
    out["mission"] = (
        _text(irs990pf, "e:ActivityOrMissionDesc")
        or _text(irs990pf, "e:StatementsRegardingActyTxt")
    )

    # Application submission info — these are the four sub-elements that tell
    # an applicant exactly how to approach this foundation
    app = irs990pf.find("e:OnlyContriToPreSelectInd/..", _NS) or irs990pf
    application_info: Dict[str, str] = {}
    for sub in (
        ("e:OnlyContriToPreSelectInd", "only_contributes_to_preselected"),
        ("e:GrantApplicationProcedureGrp/e:ApplicationFormatRequirementsTxt", "application_format"),
        ("e:GrantApplicationProcedureGrp/e:RequiredApplicationInformationTxt", "required_information"),
        ("e:GrantApplicationProcedureGrp/e:SubmissionDeadlinesTxt", "submission_deadlines"),
        ("e:GrantApplicationProcedureGrp/e:RestrictionsOnAwardsTxt", "award_restrictions"),
        ("e:GrantApplicationProcedureGrp/e:RecipientNm", "send_application_to_name"),
        ("e:GrantApplicationProcedureGrp/e:PhoneNum", "send_application_to_phone"),
    ):
        val = _text(irs990pf, sub[0])
        if val:
            application_info[sub[1]] = val
    out["application_info"] = application_info

    # Grants paid this year — the headline data for grant-seekers
    grants: List[Dict[str, str]] = []
    for grp in _find_all(irs990pf, "e:SupplementaryInformationGrp/e:GrantOrContributionPdDurYrGrp")[:20]:
        recipient = (
            _text(grp, "e:RecipientBusinessName/e:BusinessNameLine1Txt")
            or _text(grp, "e:RecipientPersonNm")
        )
        if not recipient:
            continue
        grants.append({
            "recipient": recipient,
            "amount": _money(_text(grp, "e:Amt") or _text(grp, "e:GrantOrContributionAmt")),
            "purpose": _text(grp, "e:GrantOrContributionPurposeTxt") or _text(grp, "e:PurposeOfGrantTxt"),
            "recipient_status": _text(grp, "e:RecipientFoundationStatusTxt"),
        })
    out["grants"] = grants

    # Officers
    officers: List[Dict[str, str]] = []
    for grp in _find_all(irs990pf, "e:OfficerDirTrstKeyEmplInfoGrp/e:OfficerDirTrstKeyEmplGrp")[:8]:
        name = _text(grp, "e:PersonNm")
        title = _text(grp, "e:TitleTxt")
        if name:
            officers.append({"name": name, "title": title})
    out["officers"] = officers

    return out


def _parse_990ez(irs990ez: ET.Element) -> Dict[str, Any]:
    """Form 990-EZ — small charities; lighter version of 990."""
    out: Dict[str, Any] = {}
    out["mission"] = (
        _text(irs990ez, "e:PrimaryExemptPurposeTxt")
        or _text(irs990ez, "e:DescriptionProgramSrvcAccomTxt")
    )
    return out


def _parse_schedule_i_grants(data: ET.Element) -> List[Dict[str, str]]:
    """Schedule I lists grants paid to other US organizations (990 only)."""
    sched_i = data.find("e:IRS990ScheduleI", _NS)
    if sched_i is None:
        return []
    grants: List[Dict[str, str]] = []
    for grp in _find_all(sched_i, "e:RecipientTable")[:20]:
        recipient = (
            _text(grp, "e:RecipientBusinessName/e:BusinessNameLine1Txt")
            or _text(grp, "e:RecipientEIN")
        )
        if not recipient:
            continue
        grants.append({
            "recipient": recipient,
            "amount": _money(_text(grp, "e:CashGrantAmt")),
            "purpose": _text(grp, "e:PurposeOfGrantTxt"),
        })
    return grants


def narrative_from_parsed(parsed: Dict[str, Any]) -> str:
    """Render the parsed 990 dict as plain text for the LLM.

    Order matters — leading lines set context, trailing lines provide
    structured detail for the model to pull from.
    """
    if not parsed:
        return ""
    lines: List[str] = []
    return_type = parsed.get("return_type", "")
    lines.append(f"IRS Form {return_type or '990'} narrative — {parsed.get('filer_name','')}")
    if parsed.get("ein"):
        lines.append(f"EIN: {parsed['ein']}")
    if parsed.get("address"):
        lines.append(f"Address: {parsed['address']}")
    if parsed.get("mission"):
        lines.append(f"\nMission / activity statement:\n{parsed['mission']}")

    app = parsed.get("application_info") or {}
    if app:
        lines.append("\nApplication procedure (verbatim from the filing):")
        for k, v in app.items():
            lines.append(f"  {k.replace('_', ' ').title()}: {v}")

    accomp = parsed.get("program_accomplishments") or []
    if accomp:
        lines.append("\nProgram service accomplishments:")
        for a in accomp:
            lines.append(
                f"  - {a.get('description','(no description)')}"
                + (f"  (expenses: {a['expenses']})" if a.get("expenses") else "")
                + (f"  (grants: {a['grants']})" if a.get("grants") else "")
            )

    grants = parsed.get("grants") or []
    if grants:
        lines.append(f"\nGrants paid this year (showing {len(grants)}):")
        for g in grants:
            line = f"  - {g.get('recipient','(no recipient)')}"
            if g.get("amount"):
                line += f": {g['amount']}"
            if g.get("purpose"):
                purpose = g["purpose"][:160]
                line += f" — {purpose}"
            lines.append(line)

    officers = parsed.get("officers") or []
    if officers:
        lines.append("\nOfficers / key personnel:")
        for o in officers[:5]:
            line = f"  - {o.get('name','')}"
            if o.get("title"):
                line += f", {o['title']}"
            lines.append(line)

    return "\n".join(lines)


def xml_to_narrative(xml_text: str) -> str:
    """Convenience: parse + render in one call."""
    parsed = parse_990_narrative(xml_text)
    return narrative_from_parsed(parsed)


def extract_website_from_xml(xml_text: str) -> str:
    """Return the filer's website URL extracted from a 990 XML filing.

    Checks the standard IRS schema location (`WebsiteAddressTxt`) in all
    three return types (990, 990-PF, 990-EZ) before falling back to the
    header-level Filer element.  Returns an empty string if nothing useful
    is found (including placeholder values like 'N/A' or 'NONE').
    """
    if not xml_text:
        return ""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""

    _BAD = {"n/a", "na", "none", "www.n/a", "http://n/a", "not applicable", ""}

    def _clean(raw: str) -> str:
        if not raw:
            return ""
        raw = raw.strip()
        if raw.lower() in _BAD:
            return ""
        if not raw.startswith("http"):
            raw = "https://" + raw
        return raw

    # Primary: ReturnData → IRS990 / IRS990PF / IRS990EZ
    data = root.find("e:ReturnData", _NS)
    if data is not None:
        for form_key in ("e:IRS990", "e:IRS990PF", "e:IRS990EZ"):
            form = data.find(form_key, _NS)
            if form is not None:
                ws = _clean(_text(form, "e:WebsiteAddressTxt"))
                if ws:
                    return ws

    # Fallback: ReturnHeader → Filer
    header = root.find("e:ReturnHeader", _NS)
    if header is not None:
        filer = header.find("e:Filer", _NS)
        if filer is not None:
            ws = _clean(_text(filer, "e:WebsiteAddressTxt"))
            if ws:
                return ws

    return ""
