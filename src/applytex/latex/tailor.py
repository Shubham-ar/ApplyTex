"""Keyword Match LaTeX tailoring orchestration."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from applytex.config import (
    MASTER_TEX_PATH,
    RESUME_PATH,
    TAILORED_DIR,
    keyword_auto_release,
    load_profile,
    load_skill_adjacency,
)
from applytex.database import get_connection, get_jobs_by_stage
from applytex.latex.compiler import compile_tex
from applytex.latex.keywords import (
    classify_terms,
    compute_match_score,
    extract_from_jd,
)
from applytex.latex.patch import apply_patch
from applytex.latex.placement import detect_zones
from applytex.latex.tailor_plan import build_keyword_plan
from applytex.latex.text_export import master_to_resume_txt
from applytex.latex.utils import job_file_prefix
from applytex.latex.validator import validate_patch
from applytex.llm import get_client

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


def _match_after_patch(
    patched_tex: str,
    plan_terms: list,
    profile: dict,
    clusters: dict,
) -> float:
    """Re-score keyword match on patched tex (via plain-text export)."""
    jd_terms = [t["jd"] for t in plan_terms if t.get("jd")]
    if not jd_terms:
        return 0.0
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tex", delete=False, encoding="utf-8") as tmp:
        tmp.write(patched_tex)
        tmp_path = Path(tmp.name)
    try:
        plain = master_to_resume_txt(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    reclassified = classify_terms(jd_terms, plain, profile, clusters)
    return compute_match_score(reclassified, strict=True)


def tailor_job(master_tex: str, resume_text: str, job: dict, profile: dict) -> dict:
    """Run Keyword Match pipeline for a single job.

    Returns:
        Result dict with paths, report, status.
    """
    adjacency = load_skill_adjacency()
    clusters = adjacency.get("clusters", {})
    placement = adjacency.get("placement", {})

    jd = job.get("full_description") or job.get("description") or ""
    client = get_client()
    jd_terms = extract_from_jd(jd, client=client)

    before_classes = classify_terms(jd_terms, resume_text, profile, clusters)
    match_before = compute_match_score(before_classes, strict=True)

    zones = detect_zones(master_tex, placement)
    plan = build_keyword_plan(job, before_classes, zones, adjacency)

    prefix = job_file_prefix(job)
    TAILORED_DIR.mkdir(parents=True, exist_ok=True)

    plan_path = TAILORED_DIR / f"{prefix}_KEYWORD_PLAN.json"
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    errors: list[str] = []
    patched_tex = master_tex
    adjustments: list = []
    validation: dict = {"passed": False, "errors": [], "warnings": []}

    # Early exit: skip LLM call if plan has nothing to add (no adjacent terms)
    has_adjacent = any(
        t.get("action") in ("append_adjacent", "swap_label")
        for t in plan.get("terms", [])
    )
    if has_adjacent:
        for attempt in range(MAX_ATTEMPTS):
            try:
                patched_tex, adjustments = apply_patch(master_tex, plan, profile)
                validation = validate_patch(
                    master_tex, patched_tex, plan, profile,
                    sacred_texts=zones.get("sacred_text", []),
                )
                if validation["passed"]:
                    break
                errors = validation["errors"]
                log.warning("Patch validation failed (attempt %d): %s", attempt + 1, errors)
            except Exception as exc:
                errors = [str(exc)]
                log.warning("Patch failed (attempt %d): %s", attempt + 1, exc)
        else:
            return {
                "status": "failed_validation",
                "prefix": prefix,
                "errors": errors,
                "plan_path": str(plan_path),
            }
    else:
        log.info(
            "[%s] No adjacent terms to add — skipping LLM patch (%d already exact, %d gaps)",
            prefix,
            sum(1 for t in plan.get("terms", []) if t.get("status") == "exact"),
            sum(1 for t in plan.get("terms", []) if t.get("status") in ("gap", "blocked")),
        )

    tex_path = TAILORED_DIR / f"{prefix}.tex"
    tex_path.write_text(patched_tex, encoding="utf-8")

    for asset in MASTER_TEX_PATH.parent.glob("*"):
        if asset.suffix.lower() in {".cls", ".sty", ".bib", ".png", ".jpg", ".jpeg", ".pdf"}:
            dest = TAILORED_DIR / asset.name
            if not dest.exists():
                try:
                    shutil.copy2(asset, dest)
                except OSError:
                    pass

    compile_error = None
    pdf_path = None
    try:
        pdf_path = compile_tex(tex_path, work_dir=TAILORED_DIR)
    except Exception as exc:
        compile_error = str(exc)
        log.error("Compile failed for %s: %s", tex_path, exc)

    txt_path = TAILORED_DIR / f"{prefix}.txt"
    txt_path.write_text(master_to_resume_txt(tex_path), encoding="utf-8")

    match_after = _match_after_patch(patched_tex, plan["terms"], profile, clusters)
    skipped_gaps = [t["jd"] for t in plan["terms"] if t.get("status") == "gap"]

    report = {
        "job_url": job.get("url"),
        "adjustments": adjustments,
        "skipped_gaps": skipped_gaps,
        "match_before": match_before,
        "match_after": match_after,
        "validation_warnings": validation.get("warnings", []),
        "compile_error": compile_error,
    }
    report_path = TAILORED_DIR / f"{prefix}_KEYWORD_REPORT.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    job_path = TAILORED_DIR / f"{prefix}_JOB.txt"
    job_path.write_text(
        f"Title: {job.get('title')}\n"
        f"Company: {job.get('site')}\n"
        f"Location: {job.get('location', 'N/A')}\n"
        f"Score: {job.get('fit_score', 'N/A')}\n"
        f"URL: {job.get('url')}\n\n"
        f"{jd}",
        encoding="utf-8",
    )

    auto = keyword_auto_release()
    if compile_error:
        review_status = None
    else:
        review_status = "approved" if auto else "pending"

    return {
        "status": "ok" if not compile_error else "compile_error",
        "prefix": prefix,
        "tex_path": str(tex_path),
        "pdf_path": str(pdf_path) if pdf_path else None,
        "txt_path": str(txt_path),
        "plan_path": str(plan_path),
        "report_path": str(report_path),
        "review_status": review_status,
        "match_before": match_before,
        "match_after": match_after,
        "compile_error": compile_error,
        "tailored_resume_path": str(txt_path) if review_status == "approved" else None,
    }


def _latex_worker(
    master_tex: str,
    resume_text: str,
    profile: dict,
    jobs: list[dict],
    worker_id: int,
) -> dict:
    """Process a batch of jobs for LaTeX tailoring in a single thread.

    Each thread gets its own DB connection (thread-local) and processes jobs
    sequentially within the batch. Returns aggregated stats for the batch.
    """
    stats: dict[str, int] = {"ok": 0, "failed": 0, "compile_error": 0, "error": 0, "total": len(jobs)}

    for i, job in enumerate(jobs, 1):
        try:
            result = tailor_job(master_tex, resume_text, job, profile)
            status = result.get("status", "error")
            stats[status] = stats.get(status, 0) + 1

            if status in ("failed_validation", "compile_error"):
                review_status = None
            else:
                review_status = result.get("review_status")

            now = datetime.now(timezone.utc).isoformat()
            report_path = None if status == "compile_error" else result.get("report_path")

            conn = get_connection()
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
                    report_path,
                    result.get("match_before"),
                    result.get("match_after"),
                    review_status,
                    result.get("compile_error"),
                    result.get("tailored_resume_path"),
                    result.get("tailored_resume_path"),
                    now,
                    job["url"],
                ),
            )
            conn.commit()

            log.info(
                "[W%d] %d/%d [%s] %s | match %.0f%% -> %.0f%%",
                worker_id,
                i,
                len(jobs),
                status,
                (job.get("title") or "")[:40],
                (result.get("match_before") or 0) * 100,
                (result.get("match_after") or 0) * 100,
            )
        except Exception as exc:
            stats["error"] += 1
            conn = get_connection()
            conn.execute(
                "UPDATE jobs SET tailor_attempts = COALESCE(tailor_attempts, 0) + 1 WHERE url = ?",
                (job["url"],),
            )
            conn.commit()
            log.error("[W%d] [ERROR] %s — %s", worker_id, job.get("title", "")[:40], exc)

    return stats


def run_latex_tailoring(
    min_score: int = 7,
    limit: int = 0,
    workers: int = 1,
) -> dict:
    """Batch Keyword Match tailoring for high-scoring jobs.

    Args:
        min_score: Minimum fit_score to tailor for.
        limit: Maximum number of jobs to process.
        workers: Number of parallel threads. Default 1 (sequential).
    """
    if not MASTER_TEX_PATH.exists():
        raise FileNotFoundError(
            f"master.tex not found at {MASTER_TEX_PATH}. Run `applytex init` with LaTeX."
        )

    profile = load_profile()
    master_tex = MASTER_TEX_PATH.read_text(encoding="utf-8")
    resume_text = RESUME_PATH.read_text(encoding="utf-8") if RESUME_PATH.exists() else master_to_resume_txt(MASTER_TEX_PATH)

    conn = get_connection()
    jobs = get_jobs_by_stage(conn=conn, stage="pending_latex", min_score=min_score, limit=limit)

    if not jobs:
        log.info("No jobs pending LaTeX tailor with score >= %d.", min_score)
        return {"ok": 0, "failed": 0, "errors": 0, "elapsed": 0.0}

    log.info(
        "LaTeX Keyword Match for %d jobs (score >= %d, workers=%d)...",
        len(jobs), min_score, workers,
    )
    t0 = time.time()
    merged: dict[str, int] = {"ok": 0, "failed": 0, "compile_error": 0, "error": 0}

    if workers > 1 and len(jobs) > 1:
        # Parallel mode — split into batches, one per worker thread
        batch_size = max(1, len(jobs) // workers)
        batches = [jobs[i : i + batch_size] for i in range(0, len(jobs), batch_size)]
        log.info("Split into %d batches of ~%d jobs each", len(batches), batch_size)

        with ThreadPoolExecutor(max_workers=min(workers, len(batches))) as executor:
            futures = {
                executor.submit(_latex_worker, master_tex, resume_text, profile, batch, wid): wid
                for wid, batch in enumerate(batches)
            }
            for future in as_completed(futures):
                batch_stats = future.result()
                for k in ("ok", "failed", "compile_error", "error"):
                    merged[k] += batch_stats.get(k, 0)
    else:
        # Sequential mode (default)
        batch_stats = _latex_worker(master_tex, resume_text, profile, jobs, 0)
        for k in ("ok", "failed", "compile_error", "error"):
            merged[k] += batch_stats.get(k, 0)

    elapsed = time.time() - t0
    log.info(
        "LaTeX Keyword Match done in %.1fs: %d ok, %d failed, %d compile_error, %d errors",
        elapsed,
        merged.get("ok", 0),
        merged.get("failed_validation", 0) + merged.get("failed", 0),
        merged.get("compile_error", 0),
        merged.get("error", 0),
    )
    return {
        "ok": merged.get("ok", 0),
        "failed": merged.get("failed", 0) + merged.get("failed_validation", 0),
        "compile_error": merged.get("compile_error", 0),
        "errors": merged.get("error", 0),
        "elapsed": elapsed,
    }
