# tests/test_geography.py
"""Unit tests for _compute_geography_verdict with W4AL's org profile."""
import pytest
from utils.llm_utils import _compute_geography_verdict

W4AL_COUNTRIES = [
    "United States", "South Africa", "Kenya",
    "Namibia", "Ethiopia", "Honduras", "Mexico",
]
W4AL_REGIONS = {
    "South Africa": ["Eastern Cape", "Western Cape"],
    "United States": ["Georgia", "Oregon", "Pennsylvania"],
}


@pytest.fixture
def geo():
    return {"service_countries": W4AL_COUNTRIES, "service_regions": W4AL_REGIONS}


def test_global_match(geo):
    assert _compute_geography_verdict("Global", **geo)["verdict"] == "match"


def test_worldwide_match(geo):
    assert _compute_geography_verdict("Worldwide", **geo)["verdict"] == "match"


def test_international_match(geo):
    assert _compute_geography_verdict("International", **geo)["verdict"] == "match"


def test_africa_continental_match(geo):
    assert _compute_geography_verdict("Africa", **geo)["verdict"] == "match"


def test_east_africa_continental_match(geo):
    assert _compute_geography_verdict("East Africa", **geo)["verdict"] == "match"


def test_sub_saharan_africa_match(geo):
    assert _compute_geography_verdict("Sub-Saharan Africa", **geo)["verdict"] == "match"


def test_southern_africa_match(geo):
    assert _compute_geography_verdict("Southern Africa", **geo)["verdict"] == "match"


def test_latin_america_match(geo):
    assert _compute_geography_verdict("Latin America", **geo)["verdict"] == "match"


def test_central_america_match(geo):
    assert _compute_geography_verdict("Central America", **geo)["verdict"] == "match"


def test_europe_unknown(geo):
    """No W4AL countries are in Europe."""
    assert _compute_geography_verdict("Europe", **geo)["verdict"] == "unknown"


def test_south_africa_country_match(geo):
    assert _compute_geography_verdict("South Africa", **geo)["verdict"] == "match"


def test_kenya_country_match(geo):
    assert _compute_geography_verdict("Kenya", **geo)["verdict"] == "match"


def test_eastern_cape_sa_match(geo):
    result = _compute_geography_verdict("Eastern Cape, South Africa", **geo)
    assert result["verdict"] == "match"


def test_western_cape_sa_match(geo):
    result = _compute_geography_verdict("Western Cape, South Africa", **geo)
    assert result["verdict"] == "match"


def test_kwazulu_natal_sa_partial(geo):
    """KZN is a real SA province not in org's listed regions."""
    result = _compute_geography_verdict("KwaZulu-Natal, South Africa", **geo)
    assert result["verdict"] == "partial"


def test_london_northern_ireland_south_africa_match(geo):
    """London/NI are UK regions, not SA sub-regions — should be match for SA."""
    result = _compute_geography_verdict("London, Northern Ireland, South Africa", **geo)
    assert result["verdict"] == "match"


def test_georgia_usa_match(geo):
    result = _compute_geography_verdict("Georgia, United States", **geo)
    assert result["verdict"] == "match"


def test_california_usa_partial(geo):
    """California is a real US state not in org's listed states."""
    result = _compute_geography_verdict("California, United States", **geo)
    assert result["verdict"] == "partial"


def test_united_kingdom_unknown(geo):
    result = _compute_geography_verdict("United Kingdom", **geo)
    assert result["verdict"] == "unknown"


def test_empty_scope_unknown(geo):
    assert _compute_geography_verdict("", **geo)["verdict"] == "unknown"


def test_not_stated_unknown(geo):
    assert _compute_geography_verdict("not stated", **geo)["verdict"] == "unknown"


def test_not_applicable_unknown(geo):
    assert _compute_geography_verdict("N/A", **geo)["verdict"] == "unknown"
