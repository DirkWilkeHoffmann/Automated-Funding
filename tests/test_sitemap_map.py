"""Tests for Phase 6: sitemap-based funding URL discovery."""

import utils.discovery.sitemap_map as sm
from utils.discovery.sitemap_map import (
    _collect_locs,
    _parse_sitemap_xml,
    _sitemap_urls_from_robots,
    find_funding_urls,
)


# ── _parse_sitemap_xml ────────────────────────────────────────────────────────


_URLSET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.org/grants</loc></url>
  <url><loc>https://example.org/about</loc></url>
  <url><loc>https://example.org/apply</loc></url>
</urlset>"""

_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.org/sitemap-pages.xml</loc></sitemap>
  <sitemap><loc>https://example.org/sitemap-grants.xml</loc></sitemap>
</sitemapindex>"""

_MALFORMED_XML = "this is not xml <"


def test_parse_urlset_returns_locs():
    is_index, locs = _parse_sitemap_xml(_URLSET_XML)
    assert is_index is False
    assert "https://example.org/grants" in locs
    assert len(locs) == 3


def test_parse_sitemapindex_is_index():
    is_index, locs = _parse_sitemap_xml(_INDEX_XML)
    assert is_index is True
    assert len(locs) == 2
    assert "https://example.org/sitemap-pages.xml" in locs


def test_parse_malformed_returns_empty():
    is_index, locs = _parse_sitemap_xml(_MALFORMED_XML)
    assert locs == []


# ── _sitemap_urls_from_robots ─────────────────────────────────────────────────


def test_robots_extracts_sitemap_url(monkeypatch):
    monkeypatch.setattr(sm, "fetch_page", lambda url: "Sitemap: https://example.org/sitemap.xml\nUser-agent: *\n")
    urls = _sitemap_urls_from_robots("https://example.org")
    assert urls == ["https://example.org/sitemap.xml"]


def test_robots_extracts_multiple_sitemaps(monkeypatch):
    robots = "Sitemap: https://example.org/sm1.xml\nSitemap: https://example.org/sm2.xml\n"
    monkeypatch.setattr(sm, "fetch_page", lambda url: robots)
    urls = _sitemap_urls_from_robots("https://example.org")
    assert len(urls) == 2


def test_robots_empty_page_returns_empty(monkeypatch):
    monkeypatch.setattr(sm, "fetch_page", lambda url: None)
    assert _sitemap_urls_from_robots("https://example.org") == []


def test_robots_no_sitemap_line_returns_empty(monkeypatch):
    monkeypatch.setattr(sm, "fetch_page", lambda url: "User-agent: *\nDisallow: /admin\n")
    assert _sitemap_urls_from_robots("https://example.org") == []


# ── _collect_locs ─────────────────────────────────────────────────────────────


def test_collect_locs_urlset(monkeypatch):
    monkeypatch.setattr(sm, "fetch_page", lambda url: _URLSET_XML)
    locs = _collect_locs("https://example.org/sitemap.xml")
    assert "https://example.org/grants" in locs


def test_collect_locs_empty_page(monkeypatch):
    monkeypatch.setattr(sm, "fetch_page", lambda url: None)
    assert _collect_locs("https://example.org/sitemap.xml") == []


def test_collect_locs_index_fetches_children(monkeypatch):
    child_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.org/apply</loc></url>
</urlset>"""

    def _fetch(url):
        if "sitemap.xml" in url and "pages" not in url and "grants" not in url:
            return _INDEX_XML
        return child_xml

    monkeypatch.setattr(sm, "fetch_page", _fetch)
    locs = _collect_locs("https://example.org/sitemap.xml")
    assert "https://example.org/apply" in locs


# ── find_funding_urls ─────────────────────────────────────────────────────────


def test_find_funding_urls_returns_grant_urls(monkeypatch):
    sitemap = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://foundation.org/grants/apply</loc></url>
  <url><loc>https://foundation.org/news/2025</loc></url>
  <url><loc>https://foundation.org/funding-opportunities</loc></url>
</urlset>"""
    robots = "Sitemap: https://foundation.org/sitemap.xml\n"

    def _fetch(url):
        if url.endswith("robots.txt"):
            return robots
        return sitemap

    monkeypatch.setattr(sm, "fetch_page", _fetch)
    urls = find_funding_urls("https://foundation.org")
    assert any("grant" in u or "funding" in u for u in urls)
    assert not any("news" in u for u in urls)


def test_find_funding_urls_no_sitemap_returns_empty(monkeypatch):
    monkeypatch.setattr(sm, "fetch_page", lambda url: None)
    assert find_funding_urls("https://example.org") == []


def test_find_funding_urls_ranked_stronger_first(monkeypatch):
    # "grants/apply" has two keyword hits; "funding" has one
    sitemap = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://fdn.org/funding</loc></url>
  <url><loc>https://fdn.org/grants/apply</loc></url>
</urlset>"""
    monkeypatch.setattr(sm, "fetch_page", lambda url: sitemap if "sitemap" in url else None)
    urls = find_funding_urls("https://fdn.org")
    assert urls[0] == "https://fdn.org/grants/apply"


def test_find_funding_urls_excludes_offsite(monkeypatch):
    sitemap = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://other.org/grants</loc></url>
  <url><loc>https://fdn.org/grants</loc></url>
</urlset>"""
    monkeypatch.setattr(sm, "fetch_page", lambda url: sitemap if "sitemap" in url else None)
    urls = find_funding_urls("https://fdn.org")
    assert all("fdn.org" in u for u in urls)


def test_find_funding_urls_falls_back_to_sitemap_xml(monkeypatch):
    sitemap = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://fdn.org/apply</loc></url>
</urlset>"""

    def _fetch(url):
        if url.endswith("robots.txt"):
            return "User-agent: *\n"  # no Sitemap: line
        return sitemap

    monkeypatch.setattr(sm, "fetch_page", _fetch)
    urls = find_funding_urls("https://fdn.org")
    assert "https://fdn.org/apply" in urls
