"""Resume registry — tailored variants linked to jobs."""

from __future__ import annotations

import json
from pathlib import Path

from applytex.database import get_connection


def _variant_name(row: dict) -> str:
    path = row.get("tailored_latex_path") or row.get("tailored_resume_path") or ""
    if path:
        return Path(path).stem
    return "—"


def _flag_summary(report_path: str | None) -> str:
    if not report_path or not Path(report_path).exists():
        return "—"
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        n = len(report.get("adjustments", []))
        gaps = len(report.get("skipped_gaps", []))
        if n == 0 and gaps == 0:
            return "none"
        parts = []
        if n:
            parts.append(f"{n} adj")
        if gaps:
            parts.append(f"{gaps} gaps")
        return ", ".join(parts)
    except Exception:
        return "?"


def list_registry(
    *,
    limit: int = 100,
    review_status: str | None = None,
) -> list[dict]:
    """List jobs with tailored resume artifacts."""
    conn = get_connection()
    where = "WHERE (keyword_report_path IS NOT NULL OR tailored_resume_path IS NOT NULL)"
    params: list = []
    if review_status:
        where += " AND review_status = ?"
        params.append(review_status)

    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT url, title, site, fit_score, review_status,
               keyword_match_before, keyword_match_after,
               tailored_latex_path, tailored_resume_path, keyword_report_path,
               tailored_at, latex_compile_error
        FROM jobs
        {where}
        ORDER BY fit_score DESC NULLS LAST, tailored_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    out: list[dict] = []
    for row in rows:
        item = dict(row)
        item["variant"] = _variant_name(item)
        item["flags"] = _flag_summary(item.get("keyword_report_path"))
        tex = item.get("tailored_latex_path")
        txt = item.get("tailored_resume_path")
        item["pdf_path"] = str(Path(tex).with_suffix(".pdf")) if tex else None
        item["match"] = None
        before = item.get("keyword_match_before")
        after = item.get("keyword_match_after")
        if before is not None and after is not None:
            item["match"] = f"{before:.0%}→{after:.0%}"
        out.append(item)
    return out


def load_keyword_report(report_path: str | None) -> dict:
    if not report_path or not Path(report_path).exists():
        return {}
    return json.loads(Path(report_path).read_text(encoding="utf-8"))
