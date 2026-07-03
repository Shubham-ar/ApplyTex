"""ApplyTex CLI — the main entry point."""

from __future__ import annotations

import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from applytex import __version__

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

app = typer.Typer(
    name="applytex",
    help="AI-powered end-to-end job application pipeline.",
    no_args_is_help=True,
)
console = Console()
log = logging.getLogger(__name__)

# Valid pipeline stages (in execution order)
VALID_STAGES = ("discover", "enrich", "score", "tailor", "latex", "cover", "pdf")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bootstrap() -> None:
    """Common setup: load env, create dirs, init DB."""
    from applytex.config import load_env, ensure_dirs
    from applytex.database import init_db

    load_env()
    ensure_dirs()
    init_db()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold]applytex[/bold] {__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """ApplyTex — AI-powered end-to-end job application pipeline."""


@app.command()
def init() -> None:
    """Run the first-time setup wizard (profile, resume, search config)."""
    from applytex.wizard.init import run_wizard

    run_wizard()


@app.command()
def run(
    stages: Optional[list[str]] = typer.Argument(
        None,
        help=(
            "Pipeline stages to run. "
            f"Valid: {', '.join(VALID_STAGES)}, all. "
            "Defaults to 'all' if omitted."
        ),
    ),
    min_score: Optional[int] = typer.Option(None, "--min-score", help="Minimum fit score for tailor/cover stages."),
    workers: int = typer.Option(1, "--workers", "-w", help="Parallel threads for discovery/enrichment stages."),
    stream: bool = typer.Option(False, "--stream", help="Run stages concurrently (streaming mode)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview stages without executing."),
    validation: str = typer.Option(
        "normal",
        "--validation",
        help=(
            "Validation strictness for tailor/cover stages. "
            "strict: banned words = errors, judge must pass. "
            "normal: banned words = warnings only (default, recommended for Gemini free tier). "
            "lenient: banned words ignored, LLM judge skipped (fastest, fewest API calls)."
        ),
    ),
) -> None:
    """Run pipeline stages: discover, enrich, score, tailor, cover, pdf."""
    _bootstrap()

    from applytex.pipeline import run_pipeline
    from applytex.config import pipeline_min_score

    stage_list = stages if stages else ["all"]
    effective_min_score = min_score if min_score is not None else pipeline_min_score()

    # Validate stage names
    for s in stage_list:
        if s != "all" and s not in VALID_STAGES:
            console.print(
                f"[red]Unknown stage:[/red] '{s}'. "
                f"Valid stages: {', '.join(VALID_STAGES)}, all"
            )
            raise typer.Exit(code=1)

    # Gate AI stages behind Tier 2
    llm_stages = {"score", "tailor", "latex", "cover"}
    if any(s in stage_list for s in llm_stages) or "all" in stage_list:
        from applytex.config import check_tier
        check_tier(2, "AI scoring/tailoring")

    # Validate the --validation flag value
    valid_modes = ("strict", "normal", "lenient")
    if validation not in valid_modes:
        console.print(
            f"[red]Invalid --validation value:[/red] '{validation}'. "
            f"Choose from: {', '.join(valid_modes)}"
        )
        raise typer.Exit(code=1)

    result = run_pipeline(
        stages=stage_list,
        min_score=effective_min_score,
        dry_run=dry_run,
        stream=stream,
        workers=workers,
        validation_mode=validation,
    )

    if result.get("errors"):
        raise typer.Exit(code=1)


@app.command()
def apply(
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max applications to submit."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of parallel browser workers."),
    min_score: Optional[int] = typer.Option(None, "--min-score", help="Minimum fit score for job selection."),
    model: str = typer.Option("haiku", "--model", "-m", help="Claude model name."),
    continuous: bool = typer.Option(False, "--continuous", "-c", help="Run forever, polling for new jobs."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview actions without submitting."),
    headless: bool = typer.Option(False, "--headless", help="Run browsers in headless mode."),
    url: Optional[str] = typer.Option(None, "--url", help="Apply to a specific job URL."),
    gen: bool = typer.Option(False, "--gen", help="Generate prompt file for manual debugging instead of running."),
    mark_applied: Optional[str] = typer.Option(None, "--mark-applied", help="Manually mark a job URL as applied."),
    mark_failed: Optional[str] = typer.Option(None, "--mark-failed", help="Manually mark a job URL as failed (provide URL)."),
    fail_reason: Optional[str] = typer.Option(None, "--fail-reason", help="Reason for --mark-failed."),
    reset_failed: bool = typer.Option(False, "--reset-failed", help="Reset all failed jobs for retry."),
) -> None:
    """Launch auto-apply to submit job applications."""
    _bootstrap()

    from applytex.config import check_tier, PROFILE_PATH as _profile_path, pipeline_min_score
    from applytex.database import get_connection

    # --- Utility modes (no Chrome/Claude needed) ---

    if mark_applied:
        from applytex.apply.launcher import mark_job
        mark_job(mark_applied, "applied")
        console.print(f"[green]Marked as applied:[/green] {mark_applied}")
        return

    if mark_failed:
        from applytex.apply.launcher import mark_job
        mark_job(mark_failed, "failed", reason=fail_reason)
        console.print(f"[yellow]Marked as failed:[/yellow] {mark_failed} ({fail_reason or 'manual'})")
        return

    if reset_failed:
        from applytex.apply.launcher import reset_failed as do_reset
        count = do_reset()
        console.print(f"[green]Reset {count} failed job(s) for retry.[/green]")
        return

    # --- Full apply mode ---

    # Check 1: Tier 3 required (Claude Code CLI + Chrome)
    check_tier(3, "auto-apply")

    # Check 2: Profile exists
    if not _profile_path.exists():
        console.print(
            "[red]Profile not found.[/red]\n"
            "Run [bold]applytex init[/bold] to create your profile first."
        )
        raise typer.Exit(code=1)

    # Check 3: Tailored resumes exist (skip for --gen with --url)
    if not (gen and url):
        conn = get_connection()
        ready = conn.execute(
            """
            SELECT COUNT(*) FROM jobs
            WHERE tailored_resume_path IS NOT NULL
              AND applied_at IS NULL
              AND application_url IS NOT NULL
              AND (review_status = 'approved' OR review_status IS NULL)
            """
        ).fetchone()[0]
        if ready == 0:
            pending = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE review_status = 'pending'"
            ).fetchone()[0]
            if pending:
                console.print(
                    "[red]No approved resumes ready to apply.[/red]\n"
                    "Run [bold]applytex review --pending[/bold], then "
                    "[bold]applytex review --approve --url URL[/bold]."
                )
            else:
                console.print(
                    "[red]No tailored resumes ready.[/red]\n"
                    "Run [bold]applytex run score latex[/bold] first to prepare applications."
                )
            raise typer.Exit(code=1)

    effective_min_score = min_score if min_score is not None else pipeline_min_score()

    if gen:
        from applytex.apply.launcher import gen_prompt, BASE_CDP_PORT
        target = url or ""
        if not target:
            console.print("[red]--gen requires --url to specify which job.[/red]")
            raise typer.Exit(code=1)
        prompt_file = gen_prompt(target, min_score=effective_min_score, model=model)
        if not prompt_file:
            console.print("[red]No matching job found for that URL.[/red]")
            raise typer.Exit(code=1)
        mcp_path = _profile_path.parent / ".mcp-apply-0.json"
        console.print(f"[green]Wrote prompt to:[/green] {prompt_file}")
        console.print(f"\n[bold]Run manually:[/bold]")
        console.print(
            f"  claude --model {model} -p "
            f"--mcp-config {mcp_path} "
            f"--permission-mode bypassPermissions < {prompt_file}"
        )
        return

    from applytex.apply.launcher import main as apply_main

    effective_limit = limit if limit is not None else (0 if continuous else 1)

    console.print("\n[bold blue]Launching Auto-Apply[/bold blue]")
    console.print(f"  Limit:    {'unlimited' if continuous else effective_limit}")
    console.print(f"  Workers:  {workers}")
    console.print(f"  Model:    {model}")
    console.print(f"  Headless: {headless}")
    console.print(f"  Dry run:  {dry_run}")
    if url:
        console.print(f"  Target:   {url}")
    console.print()

    apply_main(
        limit=effective_limit,
        target_url=url,
        min_score=effective_min_score,
        headless=headless,
        model=model,
        dry_run=dry_run,
        continuous=continuous,
        workers=workers,
    )


@app.command()
def status() -> None:
    """Show pipeline statistics from the database."""
    _bootstrap()

    from applytex.database import get_stats

    stats = get_stats()

    console.print("\n[bold]ApplyTex Pipeline Status[/bold]\n")

    # Summary table
    summary = Table(title="Pipeline Overview", show_header=True, header_style="bold cyan")
    summary.add_column("Metric", style="bold")
    summary.add_column("Count", justify="right")

    summary.add_row("Total jobs discovered", str(stats["total"]))
    summary.add_row("With full description", str(stats["with_description"]))
    summary.add_row("Pending enrichment", str(stats["pending_detail"]))
    summary.add_row("Enrichment errors", str(stats["detail_errors"]))
    summary.add_row("Scored by LLM", str(stats["scored"]))
    summary.add_row("Pending scoring", str(stats["unscored"]))
    summary.add_row("Tailored resumes", str(stats["tailored"]))
    summary.add_row("Pending tailoring (7+)", str(stats["untailored_eligible"]))
    summary.add_row("Pending review", str(stats.get("pending_review", 0)))
    summary.add_row("LaTeX approved", str(stats.get("latex_ready", 0)))
    summary.add_row("Cover letters", str(stats["with_cover_letter"]))
    summary.add_row("Ready to apply", str(stats["ready_to_apply"]))
    summary.add_row("Applied", str(stats["applied"]))
    summary.add_row("Apply errors", str(stats["apply_errors"]))

    console.print(summary)

    # Score distribution
    if stats["score_distribution"]:
        dist_table = Table(title="\nScore Distribution", show_header=True, header_style="bold yellow")
        dist_table.add_column("Score", justify="center")
        dist_table.add_column("Count", justify="right")
        dist_table.add_column("Bar")

        max_count = max(count for _, count in stats["score_distribution"]) or 1
        for score, count in stats["score_distribution"]:
            bar_len = int(count / max_count * 30)
            if score >= 7:
                color = "green"
            elif score >= 5:
                color = "yellow"
            else:
                color = "red"
            bar = f"[{color}]{'=' * bar_len}[/{color}]"
            dist_table.add_row(str(score), str(count), bar)

        console.print(dist_table)

    # By site
    if stats["by_site"]:
        site_table = Table(title="\nJobs by Source", show_header=True, header_style="bold magenta")
        site_table.add_column("Site")
        site_table.add_column("Count", justify="right")

        for site, count in stats["by_site"]:
            site_table.add_row(site or "Unknown", str(count))

        console.print(site_table)

    console.print()


@app.command()
def add(
    url: str = typer.Argument(..., help="Job posting URL to add."),
    min_score: int = typer.Option(None, "--min-score", help="Minimum score to run LaTeX tailor."),
) -> None:
    """Add a single job URL → enrich → score → latex Keyword Match."""
    _bootstrap()

    from applytex.config import check_tier, is_latex_enabled

    check_tier(2, "add (score + latex)")

    from applytex.jobs.add import add_job_from_url, status_hint

    try:
        summary = add_job_from_url(url, min_score=min_score)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        console.print("[dim]Run: applytex init[/dim]")
        raise typer.Exit(code=1)

    status = summary.get("status", "—")
    failed = status in (
        "enrich_failed", "no_resume", "no_master_tex", "not_found", "latex_failed",
    )

    console.print(f"\n[bold]Job added[/bold] — {summary.get('url', url)[:70]}")
    console.print(f"  Enrich:  {summary.get('enrich', '—')}")
    console.print(f"  Score:   {summary.get('score', '—')}")
    console.print(f"  LaTeX:   {summary.get('latex', '—')}")
    if summary.get("match_before") is not None:
        console.print(
            f"  Match:   {summary['match_before']:.0%} → {summary.get('match_after', 0):.0%}"
        )
    console.print(f"  Status:  {status}")

    hint = summary.get("hint") or status_hint(status, summary)
    if hint:
        style = "yellow" if status == "pending_review" else ("red" if failed else "dim")
        console.print(f"\n[{style}]{hint}[/{style}]")

    if summary.get("review_status") == "pending":
        console.print("\n[yellow]Pending review.[/yellow] Run:")
        console.print(f"  [bold]applytex review --approve --url \"{url}\"[/bold]")
    elif status == "below_threshold":
        console.print(f"\n[dim]Score below threshold ({summary.get('min_score')}).[/dim]")

    if failed:
        raise typer.Exit(code=1)


@app.command()
def registry(
    pending: bool = typer.Option(False, "--pending", help="Only pending review."),
    approved: bool = typer.Option(False, "--approved", help="Only approved variants."),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON."),
    limit: int = typer.Option(50, "--limit", "-n", help="Max rows."),
) -> None:
    """Resume registry — tailored variants linked to jobs."""
    _bootstrap()

    from applytex.registry import list_registry
    import json as json_mod

    status_filter = None
    if pending:
        status_filter = "pending"
    elif approved:
        status_filter = "approved"

    rows = list_registry(limit=limit, review_status=status_filter)
    if json_out:
        console.print(json_mod.dumps(rows, indent=2))
        raise typer.Exit()

    if not rows:
        console.print("[dim]No tailored resumes in registry yet.[/dim]")
        console.print("[dim]Run: applytex add URL  or  applytex run latex[/dim]")
        raise typer.Exit()

    table = Table(title="ApplyTex Resume Registry", show_header=True, header_style="bold cyan")
    table.add_column("Variant")
    table.add_column("Score", justify="right")
    table.add_column("Match", justify="center")
    table.add_column("Flags")
    table.add_column("Status")
    table.add_column("Title")
    table.add_column("Job URL", overflow="fold")

    for row in rows:
        table.add_row(
            row.get("variant", "—"),
            str(row.get("fit_score") or ""),
            row.get("match") or "—",
            row.get("flags", "—"),
            row.get("review_status") or "—",
            (row.get("title") or "")[:35],
            (row.get("url") or "")[:55],
        )

    console.print(table)
    console.print(f"\n[dim]{len(rows)} entries · PDFs in ~/.applytex/tailored_resumes/[/dim]")


@app.command()
def review(
    url: Optional[str] = typer.Option(None, "--url", help="Job URL to approve or reject."),
    approve: bool = typer.Option(False, "--approve", help="Approve a pending tailored resume."),
    reject: bool = typer.Option(False, "--reject", help="Reject a pending tailored resume."),
    pending: bool = typer.Option(False, "--pending", help="List jobs awaiting review."),
) -> None:
    """Review keyword-tailored resumes before they are apply-ready."""
    _bootstrap()

    from applytex.latex.review import approve_job, list_pending, reject_job
    from applytex.registry import load_keyword_report

    if pending:
        jobs = list_pending()
        if not jobs:
            console.print("[dim]No jobs pending review.[/dim]")
            raise typer.Exit()
        table = Table(title="Pending Review", show_header=True, header_style="bold yellow")
        table.add_column("Score", justify="right")
        table.add_column("Match", justify="center")
        table.add_column("Flags", justify="right")
        table.add_column("Title")
        table.add_column("Company")
        table.add_column("URL", overflow="fold")
        for job in jobs:
            before = job.get("keyword_match_before")
            after = job.get("keyword_match_after")
            match = (
                f"{before:.0%}→{after:.0%}"
                if before is not None and after is not None
                else "—"
            )
            table.add_row(
                str(job.get("fit_score", "")),
                match,
                str(job.get("adjustment_count", 0)),
                (job.get("title") or "")[:40],
                (job.get("site") or "")[:20],
                job.get("url", "")[:60],
            )
        console.print(table)
        for job in jobs:
            report = load_keyword_report(job.get("keyword_report_path"))
            for adj in report.get("adjustments", [])[:3]:
                console.print(
                    f"  [dim]• {adj.get('jd_term', '?')}: {adj.get('change', adj.get('note', ''))}[/dim]"
                )
        console.print("\n[dim]Approve: applytex review --approve --url URL[/dim]")
        raise typer.Exit()

    if not url:
        console.print("[red]Provide --url with --approve or --reject, or use --pending.[/red]")
        raise typer.Exit(code=1)

    if approve and reject:
        console.print("[red]Use only one of --approve or --reject.[/red]")
        raise typer.Exit(code=1)

    if approve:
        if approve_job(url):
            console.print(f"[green]Approved[/green] — job is ready to apply.")
        else:
            console.print("[red]Could not approve.[/red] Check URL and review_status=pending.")
            raise typer.Exit(code=1)
    elif reject:
        if reject_job(url):
            console.print(f"[yellow]Rejected[/yellow] {url}")
        else:
            console.print("[red]Could not reject.[/red]")
            raise typer.Exit(code=1)
    else:
        console.print("[red]Specify --approve or --reject with --url.[/red]")
        raise typer.Exit(code=1)


@app.command()
def dashboard() -> None:
    """Generate and open the HTML dashboard in your browser."""
    _bootstrap()

    from applytex.view import open_dashboard

    open_dashboard()


@app.command()
def doctor() -> None:
    """Check your setup and diagnose missing requirements."""
    import shutil
    from pathlib import Path
    from applytex.config import (
        load_env, PROFILE_PATH, RESUME_PATH, RESUME_PDF_PATH,
        SEARCH_CONFIG_PATH, ENV_PATH, get_chrome_path,
        is_latex_enabled, MASTER_TEX_PATH, MASTER_CLS_PATH,
        latex_engine, find_latex_compiler, DB_PATH, LEGACY_DB_PATH,
        get_db_path,
    )

    load_env()

    ok_mark = "[green]OK[/green]"
    fail_mark = "[red]MISSING[/red]"
    warn_mark = "[yellow]WARN[/yellow]"

    old_applypilot = Path.home() / ".applypilot"
    new_applytex = Path.home() / ".applytex"
    if old_applypilot.exists() and not new_applytex.exists():
        console.print(
            "[yellow]Found ~/.applypilot but not ~/.applytex.[/yellow]\n"
            "  Run: [bold]mv ~/.applypilot ~/.applytex[/bold]\n"
            "  Or:  [bold]export APPLYTEX_DIR=~/.applypilot[/bold]\n"
        )

    if LEGACY_DB_PATH.exists() and not DB_PATH.exists():
        console.print(
            "[yellow]Found legacy applypilot.db (jobs not in applytex.db).[/yellow]\n"
            f"  Run: [bold]mv {LEGACY_DB_PATH} {DB_PATH}[/bold]\n"
            f"  [dim]Until then, ApplyTex uses {get_db_path()}[/dim]\n"
        )

    results: list[tuple[str, str, str]] = []  # (check, status, note)

    # --- Tier 1 checks ---
    # Profile
    if PROFILE_PATH.exists():
        results.append(("profile.json", ok_mark, str(PROFILE_PATH)))
    else:
        results.append(("profile.json", fail_mark, "Run 'applytex init' to create"))

    # Resume
    if RESUME_PATH.exists():
        results.append(("resume.txt", ok_mark, str(RESUME_PATH)))
    elif RESUME_PDF_PATH.exists():
        results.append(("resume.txt", warn_mark, "Only PDF found — plain-text needed for AI stages"))
    else:
        results.append(("resume.txt", fail_mark, "Run 'applytex init' to add your resume"))

    # Search config
    if SEARCH_CONFIG_PATH.exists():
        try:
            from applytex.config import load_search_config
            sc = load_search_config()
            sites_note = ", ".join(sc.get("sites", []))
            country_note = sc.get("defaults", {}).get("country_indeed", "?")
            results.append((
                "searches.yaml",
                ok_mark,
                f"{SEARCH_CONFIG_PATH} (sites: {sites_note}; country_indeed: {country_note})",
            ))
        except Exception as exc:
            results.append(("searches.yaml", warn_mark, f"Parse error: {exc}"))
    else:
        results.append(("searches.yaml", warn_mark, "Will use example config — run 'applytex init'"))

    # LaTeX (when enabled)
    if is_latex_enabled():
        if MASTER_TEX_PATH.exists():
            results.append(("latex/master.tex", ok_mark, str(MASTER_TEX_PATH)))
        else:
            results.append(("latex/master.tex", fail_mark, "Run 'applytex init' with LaTeX resume"))
        from applytex.latex.import_source import documentclass_name, validate_latex_assets

        cls_name = documentclass_name(MASTER_TEX_PATH) if MASTER_TEX_PATH.exists() else None
        needs_custom_cls = bool(cls_name and cls_name not in {"article", "report", "book", "letter", "beamer"})
        if MASTER_CLS_PATH.exists():
            results.append(("latex/resume.cls", ok_mark, str(MASTER_CLS_PATH)))
        elif needs_custom_cls:
            results.append((
                "latex/class file",
                fail_mark,
                f"Missing {cls_name}.cls for \\documentclass{{{cls_name}}} — re-run init with full folder/zip",
            ))
        else:
            results.append(("latex/resume.cls", ok_mark, "Not required for standard document class"))
        if MASTER_TEX_PATH.exists():
            try:
                validate_latex_assets(MASTER_TEX_PATH, MASTER_TEX_PATH.parent)
            except FileNotFoundError as exc:
                results.append(("latex/assets", fail_mark, str(exc)))

        engine = latex_engine()
        compiler = find_latex_compiler()
        if compiler:
            results.append((f"LaTeX ({engine})", ok_mark, compiler))
        else:
            results.append(
                (f"LaTeX ({engine})", fail_mark, f"Install {engine} (needed for PDF compile in Phase 2)"),
            )
    else:
        results.append(("latex mode", "[dim]off[/dim]", "legacy plain-text tailor (latex.enabled: false)"))

    # jobspy (discovery dep installed separately)
    try:
        import jobspy  # noqa: F401
        results.append(("python-jobspy", ok_mark, "Job board scraping available"))
    except ImportError:
        results.append(("python-jobspy", warn_mark,
                        "pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex"))

    # Playwright (enrichment + applytex add)
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        results.append(("Playwright", ok_mark, "Browser automation for enrich / add"))
    except ImportError:
        results.append(("Playwright", fail_mark, "pip install playwright && playwright install chromium"))

    # --- Tier 2 checks ---
    import os
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    has_local = bool(os.environ.get("LLM_URL"))
    if has_gemini:
        model = os.environ.get("LLM_MODEL", "gemini-2.0-flash")
        results.append(("LLM API key", ok_mark, f"Gemini ({model})"))
    elif has_openai:
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        results.append(("LLM API key", ok_mark, f"OpenAI ({model})"))
    elif has_anthropic:
        model = os.environ.get("LLM_MODEL") or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-20250514")
        results.append(("LLM API key", ok_mark, f"Anthropic ({model})"))
    elif has_local:
        results.append(("LLM API key", ok_mark, f"Local: {os.environ.get('LLM_URL')}"))
    else:
        results.append(("LLM API key", fail_mark,
                        "Set GEMINI_API_KEY in ~/.applytex/.env (run 'applytex init')"))

    # --- Tier 3 checks ---
    # Claude Code CLI
    claude_bin = shutil.which("claude")
    if claude_bin:
        results.append(("Claude Code CLI", ok_mark, claude_bin))
    else:
        results.append(("Claude Code CLI", fail_mark,
                        "Install from https://claude.ai/code (needed for auto-apply)"))

    # Chrome
    try:
        chrome_path = get_chrome_path()
        results.append(("Chrome/Chromium", ok_mark, chrome_path))
    except FileNotFoundError:
        results.append(("Chrome/Chromium", fail_mark,
                        "Install Chrome or set CHROME_PATH env var (needed for auto-apply)"))

    # Node.js / npx (for Playwright MCP)
    npx_bin = shutil.which("npx")
    if npx_bin:
        results.append(("Node.js (npx)", ok_mark, npx_bin))
    else:
        results.append(("Node.js (npx)", fail_mark,
                        "Install Node.js 18+ from nodejs.org (needed for auto-apply)"))

    # CapSolver (optional)
    capsolver = os.environ.get("CAPSOLVER_API_KEY")
    if capsolver:
        results.append(("CapSolver API key", ok_mark, "CAPTCHA solving enabled"))
    else:
        results.append(("CapSolver API key", "[dim]optional[/dim]",
                        "Set CAPSOLVER_API_KEY in .env for CAPTCHA solving"))

    # --- Render results ---
    console.print()
    console.print("[bold]ApplyTex Doctor[/bold]\n")

    col_w = max(len(r[0]) for r in results) + 2
    for check, status, note in results:
        pad = " " * (col_w - len(check))
        console.print(f"  {check}{pad}{status}  [dim]{note}[/dim]")

    console.print()

    # Tier summary
    from applytex.config import get_tier, TIER_LABELS
    tier = get_tier()
    console.print(f"[bold]Current tier: Tier {tier} — {TIER_LABELS[tier]}[/bold]")

    if tier == 1:
        console.print("[dim]  → Tier 2 unlocks: scoring, tailoring, cover letters (needs LLM API key)[/dim]")
        console.print("[dim]  → Tier 3 unlocks: auto-apply (needs Claude Code CLI + Chrome + Node.js)[/dim]")
    elif tier == 2:
        console.print("[dim]  → Tier 3 unlocks: auto-apply (needs Claude Code CLI + Chrome + Node.js)[/dim]")

    console.print()


if __name__ == "__main__":
    app()
