"""
US Grant Discovery pipeline.

Orchestrates ProPublica foundation search and Grants.gov federal search,
then writes a to_scrape_list.csv of URLs to feed into the main scrape pipeline.

Usage:
    python -m utils.US_Grant_Discovery.pipeline \\
        --state CA \\
        --keywords "palliative care" \\
        --output output/to_scrape_list.csv

Or import and call run_pipeline() from another script.
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime
from typing import List, Optional

from utils.US_Grant_Discovery.grants_gov_search import (
    federal_grants_to_scrape_urls,
    search_federal_grants,
)
from utils.US_Grant_Discovery.prospector import (
    foundations_to_scrape_urls,
    search_foundations,
)

logger = logging.getLogger(__name__)


def run_pipeline(
    *,
    state: str,
    keywords: str,
    output_path: str = "output/to_scrape_list.csv",
    max_foundations: int = 200,
    max_federal: int = 100,
    include_federal: bool = True,
) -> List[str]:
    """
    Run the US grant discovery pipeline.

    Returns the list of URLs written to the output CSV.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    all_urls: List[str] = []

    logger.info("Searching ProPublica for foundations in state=%s keywords=%s", state, keywords)
    foundations = search_foundations(
        state=state, keywords=keywords or None, max_results=max_foundations
    )
    foundation_urls = foundations_to_scrape_urls(foundations)
    logger.info("Found %d foundation URLs", len(foundation_urls))
    all_urls.extend(foundation_urls)

    if include_federal:
        logger.info("Searching Grants.gov for federal grants with keywords=%s", keywords)
        federal_grants = search_federal_grants(
            keywords=keywords,
            eligible_applicants=["12"],  # 501(c)(3) nonprofits
            max_results=max_federal,
        )
        federal_urls = federal_grants_to_scrape_urls(federal_grants)
        logger.info("Found %d federal grant URLs", len(federal_urls))
        all_urls.extend(federal_urls)

    # Deduplicate preserving order
    seen: set = set()
    unique_urls: List[str] = []
    for url in all_urls:
        if url and url not in seen:
            seen.add(url)
            unique_urls.append(url)

    run_date = datetime.utcnow().strftime("%Y-%m-%d")
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["fund_url", "discovered_at", "source"])
        writer.writeheader()
        for url in unique_urls:
            source = "federal" if "grants.gov" in url else "foundation"
            writer.writerow({"fund_url": url, "discovered_at": run_date, "source": source})

    logger.info("Wrote %d URLs to %s", len(unique_urls), output_path)
    return unique_urls


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="US Grant Discovery pipeline")
    parser.add_argument("--state", required=True, help="Two-letter US state code (e.g. CA)")
    parser.add_argument("--keywords", default="", help="Search keywords")
    parser.add_argument("--output", default="output/to_scrape_list.csv", help="Output CSV path")
    parser.add_argument("--no-federal", action="store_true", help="Skip Grants.gov search")
    args = parser.parse_args()

    urls = run_pipeline(
        state=args.state,
        keywords=args.keywords,
        output_path=args.output,
        include_federal=not args.no_federal,
    )
    print(f"Done — {len(urls)} URLs written to {args.output}")
