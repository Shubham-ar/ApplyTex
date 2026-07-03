"""Approve / reject / pending review for keyword-tailored resumes."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from applytex.config import TAILORED_DIR
from applytex.database import get_connection
from applytex.jobs.urls import resolve_job_url

log = logging.getLogger(__name__)


def list_pending(limit: int = 50) -> list[dict]:
    """Jobs awaiting review with keyword report summaries."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT url, title, site, fit_score, keyword_report_path,
               keyword_match_before, keyword_match_after, tailored_latex_path
        FROM jobs
        WHERE review_status = 'pending'
          AND keyword_report_path IS NOT NULL
          AND (latex_compile_error IS NULL OR latex_compile_error = '')
        ORDER BY fit_score DESC NULLS LAST
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        item = dict(row)
        report_path = item.get("keyword_report_path")
        if report_path and Path(report_path).exists():
            try:
                report = json.loads(Path(report_path).read_text(encoding="utf-8"))
                item["adjustment_count"] = len(report.get("adjustments", []))
                item["skipped_gaps"] = report.get("skipped_gaps", [])
            except Exception:
                item["adjustment_count"] = 0
        out.append(item)
    return out


def approve_job(url: str) -> bool:
    """Approve a pending job — sets tailored_resume_path for auto-apply."""
    conn = get_connection()
    canonical = resolve_job_url(conn, url)
    if not canonical:
        return False

    row = conn.execute(
        "SELECT url, tailored_latex_path, keyword_report_path, latex_compile_error FROM jobs WHERE url = ?",
        (canonical,),
    ).fetchone()
    if not row:
        return False

    if row["latex_compile_error"]:
        return False

    latex_path = row["tailored_latex_path"]
    if not latex_path:
        return False

    prefix = Path(latex_path).stem
    txt_path = TAILORED_DIR / f"{prefix}.txt"
    pdf_path = Path(latex_path).with_suffix(".pdf")
    if not txt_path.exists() or not pdf_path.exists():
        return False

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE jobs SET review_status = 'approved',
                        tailored_resume_path = ?,
                        tailored_at = ?
        WHERE url = ?
        """,
        (str(txt_path), now, canonical),
    )
    conn.commit()
    return True


def reject_job(url: str) -> bool:
    """Reject a pending tailored resume."""
    conn = get_connection()
    canonical = resolve_job_url(conn, url)
    if not canonical:
        return False
    cur = conn.execute(
        "UPDATE jobs SET review_status = 'rejected' WHERE url = ? AND review_status = 'pending'",
        (canonical,),
    )
    conn.commit()
    return cur.rowcount > 0
