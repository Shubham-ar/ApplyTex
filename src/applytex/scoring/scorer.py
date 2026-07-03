"""Job fit scoring: LLM-powered evaluation of candidate-job match quality.

Scores jobs on a 1-10 scale by comparing the user's resume against each
job description. Supports parallel scoring via thread pool executor.
"""

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from applytex.config import RESUME_PATH, load_profile
from applytex.database import get_connection, get_jobs_by_stage
from applytex.llm import LLMClient, _detect_provider

log = logging.getLogger(__name__)


# ── Scoring Prompt ────────────────────────────────────────────────────────

SCORE_PROMPT = """You are a job fit evaluator. Given a candidate's resume and a job description, score how well the candidate fits the role.

SCORING CRITERIA:
- 9-10: Perfect match. Candidate has direct experience in nearly all required skills and qualifications.
- 7-8: Strong match. Candidate has most required skills, minor gaps easily bridged.
- 5-6: Moderate match. Candidate has some relevant skills but missing key requirements.
- 3-4: Weak match. Significant skill gaps, would need substantial ramp-up.
- 1-2: Poor match. Completely different field or experience level.

IMPORTANT FACTORS:
- Weight technical skills heavily (programming languages, frameworks, tools)
- Consider transferable experience (automation, scripting, API work)
- Factor in the candidate's project experience
- Be realistic about experience level vs. job requirements (years of experience, seniority)

RESPOND IN EXACTLY THIS FORMAT (no other text, no chain-of-thought):
SCORE: [1-10]
KEYWORDS: [comma-separated ATS keywords from the job description that match or could match the candidate]
REASONING: [1 short sentence explaining the score]"""


def _parse_score_response(response: str) -> dict:
    """Parse the LLM's score response into structured data.

    Args:
        response: Raw LLM response text.

    Returns:
        {"score": int, "keywords": str, "reasoning": str}
    """
    score = 0
    keywords = ""
    reasoning = response

    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("SCORE:"):
            try:
                score = int(re.search(r"\d+", line).group())
                score = max(1, min(10, score))
            except (AttributeError, ValueError):
                score = 0
        elif line.startswith("KEYWORDS:"):
            keywords = line.replace("KEYWORDS:", "").strip()
        elif line.startswith("REASONING:"):
            reasoning = line.replace("REASONING:", "").strip()

    return {"score": score, "keywords": keywords, "reasoning": reasoning}


def score_job(resume_text: str, job: dict, client: LLMClient | None = None) -> dict:
    """Score a single job against the resume.

    Args:
        resume_text: The candidate's full resume text.
        job: Job dict with keys: title, site, location, full_description.
        client: LLM client instance (created per-thread if not provided).

    Returns:
        {"score": int, "keywords": str, "reasoning": str, "url": str}
    """
    job_text = (
        f"TITLE: {job['title']}\n"
        f"COMPANY: {job['site']}\n"
        f"LOCATION: {job.get('location', 'N/A')}\n\n"
        f"DESCRIPTION:\n{(job.get('full_description') or '')[:6000]}"
    )

    messages = [
        {"role": "system", "content": SCORE_PROMPT},
        {"role": "user", "content": f"RESUME:\n{resume_text}\n\n---\n\nJOB POSTING:\n{job_text}"},
    ]

    own_client = client is None
    if own_client:
        base_url, model, api_key, provider = _detect_provider()
        client = LLMClient(base_url, model, api_key, provider)

    try:
        response = client.chat(messages, max_tokens=2048, temperature=0.2)
        result = _parse_score_response(response)
        result["url"] = job["url"]
        return result
    except Exception as e:
        log.error("LLM error scoring job '%s': %s", job.get("title", "?"), e)
        return {"score": 0, "keywords": "", "reasoning": f"LLM error: {e}", "url": job["url"]}
    finally:
        if own_client:
            client.close()


def _score_worker(resume_text: str, jobs: list[dict]) -> list[dict]:
    """Score a batch of jobs in a single thread with a shared LLM client."""
    base_url, model, api_key, provider = _detect_provider()
    client = LLMClient(base_url, model, api_key, provider)
    results = []
    try:
        for job in jobs:
            result = score_job(resume_text, job, client=client)
            results.append(result)
            log.info(
                "score=%d  %s",
                result["score"], job.get("title", "?")[:60],
            )
    finally:
        client.close()
    return results


def run_scoring(limit: int = 0, rescore: bool = False, workers: int = 5) -> dict:
    """Score unscored jobs that have full descriptions.

    Uses a thread pool for parallel scoring. Each thread gets its own LLM
    client and a batch of jobs.

    Args:
        limit: Maximum number of jobs to score in this run.
        rescore: If True, re-score all jobs (not just unscored ones).
        workers: Number of parallel scoring threads.

    Returns:
        {"scored": int, "errors": int, "elapsed": float, "distribution": list}
    """
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    conn = get_connection()

    if rescore:
        query = "SELECT * FROM jobs WHERE full_description IS NOT NULL"
        if limit > 0:
            query += f" LIMIT {limit}"
        jobs = conn.execute(query).fetchall()
    else:
        jobs = get_jobs_by_stage(conn=conn, stage="pending_score", limit=limit)

    if not jobs:
        log.info("No unscored jobs with descriptions found.")
        return {"scored": 0, "errors": 0, "elapsed": 0.0, "distribution": []}

    # Convert sqlite3.Row to dicts if needed
    if jobs and not isinstance(jobs[0], dict):
        columns = jobs[0].keys()
        jobs = [dict(zip(columns, row)) for row in jobs]

    log.info("Scoring %d jobs with %d workers...", len(jobs), workers)

    # Split jobs into batches — one per worker thread
    batch_size = max(1, len(jobs) // workers)
    batches = [jobs[i:i + batch_size] for i in range(0, len(jobs), batch_size)]
    log.info("Split into %d batches of ~%d jobs each", len(batches), batch_size)

    t0 = time.time()
    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_score_worker, resume_text, batch): i
            for i, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            try:
                batch_results = future.result()
                results.extend(batch_results)
            except Exception as e:
                log.error("Batch worker failed: %s", e)

    # Sort results back by original order (optional, for predictability)
    all_urls = {j["url"] for j in jobs}
    ordered = [r for r in results if r["url"] in all_urls]

    # Write scores to DB
    now = datetime.now(timezone.utc).isoformat()
    for r in ordered:
        conn.execute(
            "UPDATE jobs SET fit_score = ?, score_reasoning = ?, scored_at = ? WHERE url = ?",
            (r["score"], f"{r['keywords']}\n{r['reasoning']}", now, r["url"]),
        )
    conn.commit()

    elapsed = time.time() - t0
    scored_count = len([r for r in ordered if r["score"] > 0])
    error_count = len([r for r in ordered if r["score"] == 0])
    log.info("Done: %d scored + %d errors in %.1fs (%.1f jobs/sec)",
             scored_count, error_count, elapsed, len(ordered) / elapsed if elapsed > 0 else 0)

    # Score distribution
    dist = conn.execute("""
        SELECT fit_score, COUNT(*) FROM jobs
        WHERE fit_score IS NOT NULL
        GROUP BY fit_score ORDER BY fit_score DESC
    """).fetchall()
    distribution = [(row[0], row[1]) for row in dist]

    return {
        "scored": len(ordered),
        "errors": error_count,
        "elapsed": elapsed,
        "distribution": distribution,
    }
