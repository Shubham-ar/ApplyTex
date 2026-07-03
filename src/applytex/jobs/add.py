"""Add a single job URL and run enrich → score → latex pipeline."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from applytex.config import RESUME_PATH, is_latex_enabled, load_app_config
from applytex.database import get_connection, init_db
from applytex.enrichment.detail import UA, scrape_detail_page
from applytex.jobs.urls import normalize_job_url
from applytex.scoring.scorer import score_job

log = logging.getLogger(__name__)

_STATUS_HINTS: dict[str, str] = {
    "enrich_failed": "Could not scrape job page. Check URL and network; try again or paste description manually.",
    "no_resume": "Missing resume.txt for scoring. Run: applytex init",
    "no_master_tex": "Missing latex/master.tex. Run: applytex init with your LaTeX resume",
    "below_threshold": "Job scored below your min_score — not tailored. Lower --min-score or skip.",
    "not_found": "Job row missing after insert — database error.",
    "latex_disabled": "LaTeX pipeline disabled. Set latex.enabled: true in ~/.applytex/config.yaml",
    "latex_failed": "Keyword Match or PDF compile failed. Check applytex doctor and logs.",
}


def status_hint(status: str, summary: dict | None = None) -> str | None:
    """Human-readable next step for add_job_from_url status."""
    if status in _STATUS_HINTS:
        return _STATUS_HINTS[status]
    if summary and status == "enrich_failed":
        err = summary.get("enrich_error")
        if err:
            return f"Enrich error: {err}"
    return None


def _site_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    mapping = {
        "boards.greenhouse.io": "Greenhouse",
        "jobs.lever.co": "Lever",
        "myworkdayjobs.com": "Workday",
        "linkedin.com": "linkedin",
        "indeed.com": "indeed",
    }
    for key, name in mapping.items():
        if key in host:
            return name
    return host.split(".")[0].title() if host else "manual"


def _upsert_job(conn, url: str, site: str, title: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            """
            INSERT INTO jobs (url, title, site, strategy, discovered_at)
            VALUES (?, ?, ?, 'manual_add', ?)
            """,
            (url, title, site, now),
        )
    except sqlite3.IntegrityError:
        conn.execute(
            "UPDATE jobs SET title = COALESCE(NULLIF(title, ''), ?), site = ? WHERE url = ?",
            (title, site, url),
        )
    conn.commit()


def enrich_single_url(url: str) -> dict:
    """Scrape full description + apply URL for one job posting."""
    conn = init_db()
    result: dict = {"status": "error", "title": None}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=UA)
            try:
                page.goto(url, timeout=45000, wait_until="domcontentloaded")
                scraped = scrape_detail_page(page, url)
                result.update(scraped)
                result["title"] = (page.title() or "").strip()[:200] or None
            finally:
                browser.close()
    except Exception as exc:
        log.exception("Enrich failed for %s", url)
        result["status"] = "error"
        result["error"] = str(exc)[:500]

    now = datetime.now(timezone.utc).isoformat()
    if result.get("status") in ("ok", "partial"):
        conn.execute(
            """
            UPDATE jobs SET full_description = ?, application_url = ?,
                            detail_scraped_at = ?, detail_error = NULL,
                            title = COALESCE(?, title)
            WHERE url = ?
            """,
            (
                result.get("full_description"),
                result.get("application_url") or url,
                now,
                result.get("title"),
                url,
            ),
        )
    else:
        conn.execute(
            "UPDATE jobs SET detail_error = ?, detail_scraped_at = ? WHERE url = ?",
            (result.get("error", "scrape failed"), now, url),
        )
    conn.commit()
    return result


def add_job_from_url(url: str, min_score: int | None = None) -> dict:
    """Insert URL, enrich, score, and optionally run LaTeX Keyword Match.

    Returns:
        Summary dict with stage outcomes.
    """
    url = normalize_job_url(url)
    if not url.startswith("http"):
        raise ValueError(f"Invalid URL: {url}")

    cfg = load_app_config()
    threshold = min_score if min_score is not None else int(cfg.get("pipeline", {}).get("min_score", 8))

    conn = init_db()
    site = _site_from_url(url)
    _upsert_job(conn, url, site, title="Job posting")

    summary: dict = {"url": url, "site": site, "min_score": threshold}

    if not RESUME_PATH.exists():
        summary["status"] = "no_resume"
        summary["hint"] = status_hint("no_resume")
        return summary

    log.info("Enriching %s", url)
    enrich_result = enrich_single_url(url)
    summary["enrich"] = enrich_result.get("status")
    if enrich_result.get("status") not in ("ok", "partial"):
        summary["status"] = "enrich_failed"
        summary["enrich_error"] = enrich_result.get("error", "scrape failed")
        summary["hint"] = status_hint("enrich_failed", summary)
        return summary

    row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
    if not row:
        summary["status"] = "not_found"
        summary["hint"] = status_hint("not_found")
        return summary
    job = dict(row)

    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    log.info("Scoring %s", job.get("title", url)[:50])
    score_result = score_job(resume_text, job)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET fit_score = ?, score_reasoning = ?, scored_at = ? WHERE url = ?",
        (score_result["score"], f"{score_result['keywords']}\n{score_result['reasoning']}", now, url),
    )
    conn.commit()
    summary["score"] = score_result["score"]

    if score_result["score"] < threshold:
        summary["status"] = "below_threshold"
        summary["latex"] = "skipped"
        summary["hint"] = status_hint("below_threshold")
        return summary

    if not is_latex_enabled():
        summary["status"] = "latex_disabled"
        summary["latex"] = "disabled"
        summary["hint"] = status_hint("latex_disabled")
        return summary

    from applytex.config import MASTER_TEX_PATH, load_profile
    from applytex.latex.tailor import tailor_job

    if not MASTER_TEX_PATH.exists():
        summary["status"] = "no_master_tex"
        summary["hint"] = status_hint("no_master_tex")
        return summary

    profile = load_profile()
    master_tex = MASTER_TEX_PATH.read_text(encoding="utf-8")
    row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
    job = dict(row)

    log.info("LaTeX Keyword Match for score=%d", score_result["score"])
    result = tailor_job(master_tex, resume_text, job, profile)

    latex_status = result.get("status", "error")
    if latex_status in ("failed_validation", "compile_error"):
        review_status = None
    else:
        review_status = result.get("review_status")

    conn.execute(
        """
        UPDATE jobs SET
            tailored_latex_path = ?,
            keyword_report_path = ?,
            keyword_match_before = ?,
            keyword_match_after = ?,
            review_status = ?,
            latex_compile_error = ?,
            tailor_attempts = COALESCE(tailor_attempts, 0) + 1,
            tailored_resume_path = COALESCE(?, tailored_resume_path),
            tailored_at = CASE WHEN ? IS NOT NULL THEN ? ELSE tailored_at END
        WHERE url = ?
        """,
        (
            result.get("tex_path"),
            result.get("report_path"),
            result.get("match_before"),
            result.get("match_after"),
            review_status,
            result.get("compile_error"),
            result.get("tailored_resume_path"),
            result.get("tailored_resume_path"),
            now,
            url,
        ),
    )
    conn.commit()

    summary["latex"] = latex_status
    summary["review_status"] = review_status
    summary["match_before"] = result.get("match_before")
    summary["match_after"] = result.get("match_after")
    summary["report_path"] = result.get("report_path")
    if latex_status in ("failed_validation", "compile_error"):
        summary["status"] = "latex_failed"
        summary["hint"] = status_hint("latex_failed")
        if latex_status == "failed_validation":
            summary["latex_errors"] = result.get("errors", [])
        elif result.get("compile_error"):
            summary["latex_error"] = result["compile_error"]
        return summary

    summary["status"] = "pending_review" if review_status == "pending" else "ready"
    if summary["status"] == "pending_review":
        summary["hint"] = "Review flagged adjustments, then: applytex review --approve --url <URL>"
    return summary
