"""Shared helpers for the LaTeX tailoring pipeline."""

from __future__ import annotations

import re


def job_file_prefix(job: dict) -> str:
    """Build a safe filesystem prefix from job site + title."""
    safe_title = re.sub(r"[^\w\s-]", "", job.get("title") or "job")[:50].strip().replace(" ", "_")
    safe_site = re.sub(r"[^\w\s-]", "", job.get("site") or "unknown")[:20].strip().replace(" ", "_")
    return f"{safe_site}_{safe_title}"
