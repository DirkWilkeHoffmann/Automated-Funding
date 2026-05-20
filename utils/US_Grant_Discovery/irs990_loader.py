"""
IRS 990 bulk data loader (stub).

The IRS publishes 990 filings as JSON on AWS S3:
  s3://irs-form-990/index_<year>.json  — annual index
  s3://irs-form-990/<object_id>_public.xml — individual filings

This module is a stub. Full implementation requires:
  1. Download the annual index (several hundred MB, no auth required via HTTP):
       https://s3.amazonaws.com/irs-form-990/index_2023.json
  2. Filter for Schedule I (grants paid) filers in the desired state.
  3. Cross-reference with ProPublica to get foundation websites.

Because the index is large and changes annually, this is best run as a
one-time or quarterly batch job rather than inline.

See: https://docs.opendata.aws/irs-990/readme.html
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

IRS_INDEX_URL_TEMPLATE = "https://s3.amazonaws.com/irs-form-990/index_{year}.json"


def build_index_url(year: int) -> str:
    return IRS_INDEX_URL_TEMPLATE.format(year=year)


def load_index(year: int) -> List[Dict[str, Any]]:
    """
    Download and parse the IRS 990 annual filing index for `year`.

    WARNING: the index is ~500 MB. Stream it rather than loading into memory.
    This stub raises NotImplementedError — implement with ijson or similar.
    """
    raise NotImplementedError(
        "IRS 990 bulk loading is not yet implemented. "
        "Use prospector.py (ProPublica) or grants_gov_search.py for immediate discovery. "
        f"For bulk 990 data, download {build_index_url(year)} and implement streaming with ijson."
    )
