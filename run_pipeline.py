#!/usr/bin/env python3
"""
Run the full job analysis pipeline from a single job posting URL.

Usage:
  python run_pipeline.py https://jobs.ashbyhq.com/Crusoe/2689707b-...
"""

from __future__ import annotations

import re
import sys
from urllib.parse import urlparse


def parse_job_url(url: str) -> dict:
    """Parse a job posting URL into board, company, and job_id."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path.strip("/")

    if "ashbyhq.com" in host:
        # jobs.ashbyhq.com/{company}/{job_id}
        parts = path.split("/")
        if len(parts) >= 2:
            return {
                "board": "ashby",
                "company": parts[0].lower(),
                "job_id": parts[1],
            }

    if "greenhouse.io" in host:
        # job-boards.greenhouse.io/{company}/jobs/{job_id}
        m = re.match(r"([^/]+)/jobs/(\d+)", path)
        if m:
            return {
                "board": "greenhouse",
                "company": m.group(1).lower(),
                "job_id": m.group(2),
            }

    raise ValueError(f"Unsupported job board URL: {url}")
