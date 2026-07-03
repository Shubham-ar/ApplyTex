"""Aggregate resume gap insights across job score ranges.

Analyzes all jobs in a score range (default 5-6) to find what skills
and technologies job descriptions commonly ask for that the resume
doesn't have. Helps identify high-impact additions to the base resume.

Design:
  - Tier 1: keyword-based gap scan using existing classify_terms() (free)
  - Tier 2: single LLM call for smart recommendations (--llm flag)

This is an analytical tool — it does NOT modify the scoring or tailoring pipeline.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from typing import Any

from rich.console import Console
from rich.table import Table

from applytex.config import RESUME_PATH, load_profile, load_skill_adjacency
from applytex.database import get_connection
from applytex.latex.keywords import classify_terms, extract_from_jd, normalize_term
from applytex.llm import get_client

log = logging.getLogger(__name__)
console = Console()

# -- Data fetching -----------------------------------------------------------

def fetch_jobs_in_range(
    conn,
    min_score: int = 5,
    max_score: int = 6,
    limit: int = 0,
) -> list[dict]:
    """Fetch jobs with fit_score in [min_score, max_score] and full_description."""
    query = """
        SELECT url, title, site, fit_score, full_description
        FROM jobs
        WHERE fit_score >= ? AND fit_score <= ?
          AND full_description IS NOT NULL
          AND full_description != ''
        ORDER BY fit_score DESC
    """
    if limit > 0:
        query += f" LIMIT {limit}"
    rows = conn.execute(query, (min_score, max_score)).fetchall()
    if not rows:
        return []
    columns = rows[0].keys()
    return [dict(zip(columns, row)) for row in rows]


# -- Per-job classification --------------------------------------------------

def _classify_single_job(
    job: dict,
    resume_text: str,
    profile: dict,
    clusters: dict,
) -> dict:
    """Classify one job's JD keywords and return gap/blocked terms only.

    Uses heuristic keyword extraction (fast, no LLM calls). The heuristic
    catches common tech keywords — sufficient for aggregate insight.

    Args:
        job: Job dict with url, title, full_description.
        resume_text: The candidate's full resume text.
        profile: User profile from load_profile().
        clusters: Adjacency clusters from load_skill_adjacency().

    Returns:
        {"title": str, "url": str, "score": int,
         "term_count": int, "gaps": list[dict]}
    """
    jd = job.get("full_description") or ""
    if not jd:
        return {"title": job.get("title", "?"), "url": job.get("url", ""),
                "score": job.get("fit_score", 0), "term_count": 0, "gaps": []}

    jd_terms = extract_from_jd(jd, client=None)

    if not jd_terms:
        return {"title": job.get("title", "?"), "url": job.get("url", ""),
                "score": job.get("fit_score", 0), "term_count": 0, "gaps": []}

    classifications = classify_terms(jd_terms, resume_text, profile, clusters)

    gaps = [
        c for c in classifications
        if c.get("status") in ("gap", "blocked")
    ]

    return {
        "title": job.get("title", "?"),
        "url": job.get("url", ""),
        "score": job.get("fit_score", 0),
        "term_count": len(jd_terms),
        "gaps": gaps,
    }


# -- Aggregation -------------------------------------------------------------

def _aggregate_gap_counts(job_gaps: list[dict]) -> dict[str, Any]:
    """Aggregate gap/blocked terms across all analyzed jobs.

    Args:
        job_gaps: Output of _classify_single_job() for each job.

    Returns:
        dict with total_jobs, total_terms, unique_gaps, top_gaps[].
    """
    gap_counter: Counter = Counter()
    term_to_titles: dict[str, set[str]] = defaultdict(set)
    total_terms_count = 0

    for entry in job_gaps:
        for gap in entry.get("gaps", []):
            term = gap.get("jd", "")
            norm = normalize_term(term)
            gap_counter[norm] += 1
            term_to_titles[norm].add(entry.get("title", "?"))
        total_terms_count += entry.get("term_count", 0)

    total_jobs = len(job_gaps)
    top = []
    for term, count in gap_counter.most_common(50):
        original_terms = set()
        for entry in job_gaps:
            for gap in entry.get("gaps", []):
                if normalize_term(gap.get("jd", "")) == term:
                    original_terms.add(gap["jd"])
        display_term = next(iter(original_terms), term)
        top.append({
            "term": display_term,
            "count": count,
            "pct": round(count / total_jobs * 100, 1) if total_jobs else 0,
            "sample_titles": sorted(term_to_titles[term])[:5],
        })

    return {
        "total_jobs": total_jobs,
        "total_terms": total_terms_count,
        "unique_gaps": len(gap_counter),
        "top_gaps": top,
    }


# -- LLM recommendations -----------------------------------------------------

_RECOMMEND_PROMPT = """You are a career advisor helping someone improve their tech resume.

Across {total_jobs} jobs scoring {min_score}-{max_score} (decent match, not perfect),
these are the most frequently requested skills that the candidate's resume is missing:

{term_table}

For each skill, the number shows how many jobs out of {total_jobs} requested it.

Give 3-5 concise, actionable recommendations:
- Which 1-2 skills would have the HIGHEST impact if added to the resume?
- Are any of these niche or role-specific (low priority)?
- Any patterns in the missing skills?

Output as bullet points, plain text, no markdown."""


def _generate_recommendations(
    top_gaps: list[dict],
    total_jobs: int,
    min_score: int,
    max_score: int,
) -> str:
    """Generate a single LLM response with actionable recommendations."""
    term_lines = "\n".join(
        f"  - {g['term']}: requested in {g['count']}/{total_jobs} jobs ({g['pct']}%)"
        for g in top_gaps[:15]
    )

    prompt = _RECOMMEND_PROMPT.format(
        total_jobs=total_jobs,
        min_score=min_score,
        max_score=max_score,
        term_table=term_lines,
    )

    client = get_client()
    try:
        raw = client.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0.3,
        )
        return raw.strip()
    except Exception as e:
        log.warning("LLM recommendations failed: %s", e)
        return "(LLM call failed — no recommendations generated)"


# -- Main analysis -----------------------------------------------------------

def analyze_gaps(
    min_score: int = 5,
    max_score: int = 6,
    limit: int = 0,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Run gap analysis across all jobs in a score range.

    Args:
        min_score: Lower bound of score range (default 5).
        max_score: Upper bound of score range (default 6).
        limit: Max jobs to analyze (0 = all).
        use_llm: If True, generate AI recommendations from the gap data
                 (1 LLM call). Keyword extraction is always heuristic (fast).

    Returns:
        dict with score_range, jobs_analyzed, total_terms, unique_gaps,
        top_gaps[], and optionally llm_recommendations.
    """
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    profile = load_profile()
    adjacency = load_skill_adjacency()
    clusters = adjacency.get("clusters", {})
    conn = get_connection()
    jobs = fetch_jobs_in_range(conn, min_score, max_score, limit)

    if not jobs:
        return {
            "score_range": (min_score, max_score),
            "jobs_analyzed": 0,
            "total_terms": 0,
            "unique_gaps": 0,
            "top_gaps": [],
        }

    log.info("Analyzing %d jobs in score range %d-%d...", len(jobs), min_score, max_score)

    job_results = []
    for i, job in enumerate(jobs, 1):
        result = _classify_single_job(job, resume_text, profile, clusters)
        job_results.append(result)
        if i % 20 == 0:
            log.info("  Progress: %d/%d jobs classified", i, len(jobs))

    aggregated = _aggregate_gap_counts(job_results)

    result = {
        "score_range": (min_score, max_score),
        "jobs_analyzed": len(jobs),
        "total_terms": aggregated["total_terms"],
        "unique_gaps": aggregated["unique_gaps"],
        "top_gaps": aggregated["top_gaps"],
    }

    if use_llm and aggregated["top_gaps"]:
        result["llm_recommendations"] = _generate_recommendations(
            aggregated["top_gaps"],
            len(jobs),
            min_score,
            max_score,
        )

    return result


# -- Output formatting -------------------------------------------------------

def format_gap_report(result: dict[str, Any], json_out: bool = False) -> None:
    """Print the gap analysis report to console (or as JSON).

    Args:
        result: The dict returned by analyze_gaps().
        json_out: If True, print raw JSON instead of a Rich table.
    """
    if json_out:
        # Serialize with score_range as a list for clean JSON
        output = dict(result)
        output["score_range"] = list(result.get("score_range", ()))
        console.print(json.dumps(output, indent=2))
        return

    score_range = result.get("score_range", (5, 6))
    total = result.get("jobs_analyzed", 0)
    top = result.get("top_gaps", [])

    if total == 0:
        console.print(
            f"\n[yellow]No jobs found in score range {score_range[0]}-{score_range[1]}.[/yellow]"
        )
        return

    console.print(
        f"\n[bold]Resume Gap Insights[/bold] "
        f"(score range: [cyan]{score_range[0]}-{score_range[1]}[/cyan], "
        f"[cyan]{total}[/cyan] jobs analyzed)"
    )
    console.print()

    if not top:
        console.print("[green]No gaps found — all keywords are already covered![/green]")
        console.print()
        return

    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("Missing Skill", style="bold", width=20)
    table.add_column("Jobs", justify="right", width=6)
    table.add_column("Bar", width=30)
    table.add_column("Sample Roles", width=50, overflow="fold")

    max_count = top[0]["count"] if top else 1
    for gap in top[:20]:
        bar_len = int(gap["count"] / max_count * 28) if max_count else 0
        bar = "█" * max(bar_len, 1)
        roles = ", ".join(gap.get("sample_titles", [])[:3])
        table.add_row(
            gap["term"],
            f"{gap['count']} ({gap['pct']}%)",
            bar,
            roles,
        )

    console.print(table)
    console.print()

    unique = result.get("unique_gaps", 0)
    total_terms = result.get("total_terms", 0)
    console.print(
        f"  [dim]{unique} unique missing terms across {total_terms} total JD keywords[/dim]"
    )
    console.print()

    # LLM recommendations
    recommendations = result.get("llm_recommendations")
    if recommendations:
        console.print("[bold]Recommendations:[/bold]")
        for line in recommendations.split("\n"):
            line = line.strip()
            if line:
                console.print(f"  {line}")
        console.print()
