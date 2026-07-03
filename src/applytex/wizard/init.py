"""ApplyTex first-time setup wizard.

Interactive flow that creates ~/.applytex/ with:
  - resume.txt (and optionally resume.pdf)
  - profile.json
  - searches.yaml
  - .env (LLM API key)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from applytex.config import (
    APP_DIR,
    ENV_PATH,
    MASTER_CLS_PATH,
    PROFILE_PATH,
    RESUME_PATH,
    RESUME_PDF_PATH,
    SEARCH_CONFIG_PATH,
    ensure_dirs,
    write_default_config,
)

console = Console()


# ---------------------------------------------------------------------------
# Resume (LaTeX-first or legacy plain text)
# ---------------------------------------------------------------------------

def _setup_resume_latex() -> None:
    """Copy LaTeX source into ~/.applytex/latex/ and derive resume.txt for scoring."""
    from applytex.latex.import_source import import_latex_source
    from applytex.latex.text_export import master_to_resume_txt

    console.print(
        Panel(
            "[bold]Step 1: LaTeX Resume[/bold]\n"
            "Point to your resume source:\n"
            "  • [bold]Unzipped folder[/bold] (best) — contains .tex + .cls (e.g. resume.cls)\n"
            "  • [bold].zip[/bold] Overleaf export\n"
            "  • [bold]Single .tex[/bold] — only if .cls/.sty sit in the [italic]same folder[/italic]\n"
            "ApplyTex copies to [cyan]~/.applytex/latex/master.tex[/cyan] (+ class files)."
        )
    )

    while True:
        path_str = Prompt.ask("LaTeX path (.tex file, folder, or .zip)")
        src = Path(path_str.strip().strip('"').strip("'")).expanduser()

        if not src.exists():
            console.print(f"[red]Path not found:[/red] {src}")
            continue

        main_tex: str | None = None
        if src.is_dir():
            tex_files = sorted(src.glob("*.tex"))
            if len(tex_files) > 1 and not (src / "main.tex").exists():
                console.print(
                    "[yellow]Multiple .tex files found:[/yellow] "
                    + ", ".join(f.name for f in tex_files)
                )
                main_tex = Prompt.ask("Main .tex filename", default=tex_files[0].name)

        try:
            master_path = import_latex_source(src, main_tex=main_tex or None)
            console.print(f"[green]Copied to {master_path}[/green]")
            from applytex.latex.import_source import documentclass_name

            cls_name = documentclass_name(master_path)
            if MASTER_CLS_PATH.exists():
                console.print(f"[green]Class file: {MASTER_CLS_PATH.name}[/green]")
            elif cls_name and cls_name not in {"article", "report", "book"}:
                console.print(
                    f"[yellow]Warning:[/yellow] \\documentclass{{{cls_name}}} but no {cls_name}.cls copied."
                )
            break
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            continue

    plain = master_to_resume_txt(master_path)
    if len(plain) < 80:
        console.print(
            "[yellow]LaTeX text export looks too short — scorer may not work well.[/yellow]"
        )
        txt_path_str = Prompt.ask(
            "Plain-text resume for scoring (.txt) — leave blank to keep export",
            default="",
        )
        if txt_path_str.strip():
            txt_src = Path(txt_path_str.strip().strip('"').strip("'")).expanduser().resolve()
            if txt_src.exists():
                shutil.copy2(txt_src, RESUME_PATH)
                console.print(f"[green]Copied to {RESUME_PATH}[/green]")
            else:
                console.print("[red]File not found.[/red]")
                RESUME_PATH.write_text(plain, encoding="utf-8")
                console.print(f"[yellow]Saved short export to {RESUME_PATH}[/yellow]")
        else:
            RESUME_PATH.write_text(plain, encoding="utf-8")
            console.print(f"[green]Derived {RESUME_PATH} from LaTeX[/green]")
    else:
        RESUME_PATH.write_text(plain, encoding="utf-8")
        console.print(f"[green]Derived {RESUME_PATH} from LaTeX ({len(plain.split())} words)[/green]")


def _setup_resume_legacy() -> None:
    """Prompt for resume file and copy into APP_DIR."""
    console.print(Panel("[bold]Step 1: Resume[/bold]\nPoint to your master resume file (.txt or .pdf)."))

    while True:
        path_str = Prompt.ask("Resume file path")
        src = Path(path_str.strip().strip('"').strip("'")).expanduser().resolve()

        if not src.exists():
            console.print(f"[red]File not found:[/red] {src}")
            continue

        suffix = src.suffix.lower()
        if suffix not in (".txt", ".pdf"):
            console.print("[red]Unsupported format.[/red] Provide a .txt or .pdf file.")
            continue

        if suffix == ".txt":
            shutil.copy2(src, RESUME_PATH)
            console.print(f"[green]Copied to {RESUME_PATH}[/green]")
        elif suffix == ".pdf":
            shutil.copy2(src, RESUME_PDF_PATH)
            console.print(f"[green]Copied to {RESUME_PDF_PATH}[/green]")

            # Also ask for a plain-text version for LLM consumption
            txt_path_str = Prompt.ask(
                "Plain-text version of your resume (.txt)",
                default="",
            )
            if txt_path_str.strip():
                txt_src = Path(txt_path_str.strip().strip('"').strip("'")).expanduser().resolve()
                if txt_src.exists():
                    shutil.copy2(txt_src, RESUME_PATH)
                    console.print(f"[green]Copied to {RESUME_PATH}[/green]")
                else:
                    console.print("[yellow]File not found, skipping plain-text copy.[/yellow]")
        break


def _setup_resume() -> bool:
    """Choose LaTeX-first (default) or legacy plain-text resume setup.

    Returns:
        True if LaTeX mode, False if legacy.
    """
    console.print(
        Panel(
            "[bold]Step 1: Resume source[/bold]\n"
            "[bold]LaTeX[/bold] (recommended): copy your .tex + compile tailored PDFs per job.\n"
            "[bold]Legacy[/bold]: plain .txt or .pdf only (upstream ApplyPilot behavior)."
        )
    )
    use_latex = Confirm.ask("Use LaTeX resume (master.tex)?", default=True)
    if use_latex:
        _setup_resume_latex()
    else:
        _setup_resume_legacy()
    return use_latex


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def _setup_profile() -> dict:
    """Walk through profile questions and return a nested profile dict."""
    console.print(Panel("[bold]Step 2: Profile[/bold]\nTell ApplyTex about yourself. This powers scoring, tailoring, and auto-fill."))

    profile: dict = {}

    # -- Personal --
    console.print("\n[bold cyan]Personal Information[/bold cyan]")
    full_name = Prompt.ask("Full name")
    profile["personal"] = {
        "full_name": full_name,
        "preferred_name": Prompt.ask("Preferred/nickname (leave blank to use first name)", default=""),
        "email": Prompt.ask("Email address"),
        "phone": Prompt.ask("Phone number", default=""),
        "city": Prompt.ask("City"),
        "province_state": Prompt.ask("Province/State (e.g. Ontario, California)", default=""),
        "country": Prompt.ask("Country"),
        "postal_code": Prompt.ask("Postal/ZIP code", default=""),
        "address": Prompt.ask("Street address (optional, used for form auto-fill)", default=""),
        "linkedin_url": Prompt.ask("LinkedIn URL", default=""),
        "github_url": Prompt.ask("GitHub URL (optional)", default=""),
        "portfolio_url": Prompt.ask("Portfolio URL (optional)", default=""),
        "website_url": Prompt.ask("Personal website URL (optional)", default=""),
        "password": Prompt.ask("Job site password (used for login walls during auto-apply)", password=True, default=""),
    }

    # -- Work Authorization --
    console.print("\n[bold cyan]Work Authorization[/bold cyan]")
    profile["work_authorization"] = {
        "legally_authorized_to_work": Confirm.ask("Are you legally authorized to work in your target country?"),
        "require_sponsorship": Confirm.ask("Will you now or in the future need sponsorship?"),
        "work_permit_type": Prompt.ask("Work permit type (e.g. Citizen, PR, Open Work Permit — leave blank if N/A)", default=""),
    }

    # -- Compensation --
    console.print("\n[bold cyan]Compensation[/bold cyan]")
    salary = Prompt.ask("Expected annual salary (number)", default="")
    salary_currency = Prompt.ask("Currency", default="USD")
    salary_range = Prompt.ask("Acceptable range (e.g. 80000-120000)", default="")
    range_parts = salary_range.split("-") if "-" in salary_range else [salary, salary]
    profile["compensation"] = {
        "salary_expectation": salary,
        "salary_currency": salary_currency,
        "salary_range_min": range_parts[0].strip(),
        "salary_range_max": range_parts[1].strip() if len(range_parts) > 1 else range_parts[0].strip(),
    }

    # -- Experience --
    console.print("\n[bold cyan]Experience[/bold cyan]")
    current_title = Prompt.ask("Current/most recent job title", default="")
    target_role = Prompt.ask("Target role (what you're applying for, e.g. 'Senior Backend Engineer')", default=current_title)
    profile["experience"] = {
        "years_of_experience_total": Prompt.ask("Years of professional experience", default=""),
        "education_level": Prompt.ask("Highest education (e.g. Bachelor's, Master's, PhD, Self-taught)", default=""),
        "current_title": current_title,
        "target_role": target_role,
    }

    # -- Skills Boundary --
    console.print("\n[bold cyan]Skills[/bold cyan] (comma-separated)")
    langs = Prompt.ask("Programming languages", default="")
    frameworks = Prompt.ask("Frameworks & libraries", default="")
    tools = Prompt.ask("Tools & platforms (e.g. Docker, AWS, Git)", default="")
    profile["skills_boundary"] = {
        "programming_languages": [s.strip() for s in langs.split(",") if s.strip()],
        "frameworks": [s.strip() for s in frameworks.split(",") if s.strip()],
        "tools": [s.strip() for s in tools.split(",") if s.strip()],
    }

    # -- Resume Facts (preserved truths for tailoring) --
    console.print("\n[bold cyan]Resume Facts[/bold cyan]")
    console.print("[dim]These are preserved exactly during resume tailoring — the AI will never change them.[/dim]")
    companies = Prompt.ask("Companies to always keep (comma-separated)", default="")
    projects = Prompt.ask("Projects to always keep (comma-separated)", default="")
    school = Prompt.ask("School name(s) to preserve", default="")
    metrics = Prompt.ask("Real metrics to preserve (e.g. '99.9% uptime, 50k users')", default="")
    profile["resume_facts"] = {
        "preserved_companies": [s.strip() for s in companies.split(",") if s.strip()],
        "preserved_projects": [s.strip() for s in projects.split(",") if s.strip()],
        "preserved_school": school.strip(),
        "real_metrics": [s.strip() for s in metrics.split(",") if s.strip()],
    }

    # -- EEO Voluntary (defaults) --
    profile["eeo_voluntary"] = {
        "gender": "Decline to self-identify",
        "race_ethnicity": "Decline to self-identify",
        "veteran_status": "Decline to self-identify",
        "disability_status": "Decline to self-identify",
    }

    # -- Availability --
    profile["availability"] = {
        "earliest_start_date": Prompt.ask("Earliest start date", default="Immediately"),
    }

    # Save
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"\n[green]Profile saved to {PROFILE_PATH}[/green]")
    return profile


# ---------------------------------------------------------------------------
# Search config
# ---------------------------------------------------------------------------

def _setup_searches() -> None:
    """Generate a searches.yaml from user input."""
    import json
    import yaml

    from applytex.discovery.search_config import (
        build_wizard_search_config,
        normalize_country_indeed,
    )

    console.print(Panel("[bold]Step 3: Job Search Config[/bold]\nDefine what you're looking for."))

    personal: dict = {}
    if PROFILE_PATH.exists():
        try:
            personal = json.loads(PROFILE_PATH.read_text(encoding="utf-8")).get("personal", {})
        except json.JSONDecodeError:
            personal = {}

    default_location = personal.get("city") or personal.get("country") or "Remote"
    if personal.get("city") and personal.get("province_state"):
        default_location = f"{personal['city']}, {personal['province_state']}"

    location = Prompt.ask(
        "Primary search location (e.g. 'Toronto, ON', 'Canada', 'Remote')",
        default=default_location,
    )
    distance_str = Prompt.ask("Search radius in miles (0 for remote-only)", default="50")
    try:
        distance = int(distance_str)
    except ValueError:
        distance = 50

    country_raw = personal.get("country") or Prompt.ask(
        "Country for Indeed searches (JobSpy country_indeed)",
        default="Canada",
    )
    country_indeed = normalize_country_indeed(country_raw)

    roles_raw = Prompt.ask(
        "Target job titles (comma-separated, e.g. 'Backend Engineer, Full Stack Developer')"
    )
    roles = [r.strip() for r in roles_raw.split(",") if r.strip()]

    if not roles:
        console.print("[yellow]No roles provided. Using a default set.[/yellow]")
        roles = ["Software Engineer"]

    include_country_remote = distance > 0 and Confirm.ask(
        f"Also search remote jobs in {country_indeed.title()}?",
        default=True,
    )

    search_cfg = build_wizard_search_config(
        search_location=location,
        distance=distance,
        roles=roles,
        country_indeed=country_indeed,
        city=str(personal.get("city") or ""),
        province_state=str(personal.get("province_state") or ""),
        include_country_remote=include_country_remote,
    )

    header = (
        "# ApplyTex search configuration\n"
        "# Generated by applytex init — edit to refine queries, sites, and location filters.\n\n"
    )
    body = yaml.dump(
        search_cfg,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    SEARCH_CONFIG_PATH.write_text(header + body, encoding="utf-8")
    console.print(f"[green]Search config saved to {SEARCH_CONFIG_PATH}[/green]")
    console.print(
        f"[dim]Job boards: {', '.join(search_cfg['sites'])} | "
        f"Indeed country: {search_cfg['defaults']['country_indeed']}[/dim]"
    )


# ---------------------------------------------------------------------------
# AI Features
# ---------------------------------------------------------------------------

def _setup_ai_features() -> None:
    """Ask about AI scoring/tailoring — optional LLM configuration."""
    console.print(Panel(
        "[bold]Step 4: AI Features (optional)[/bold]\n"
        "An LLM powers job scoring, resume tailoring, and cover letters.\n"
        "Without this, you can still discover and enrich jobs."
    ))

    if not Confirm.ask("Enable AI scoring and resume tailoring?", default=True):
        console.print("[dim]Discovery-only mode. You can configure AI later with [bold]applytex init[/bold].[/dim]")
        return

    console.print("Supported providers: [bold]Gemini[/bold] (recommended, free tier), OpenAI, local (Ollama/llama.cpp)")
    provider = Prompt.ask(
        "Provider",
        choices=["gemini", "openai", "local"],
        default="gemini",
    )

    env_lines = ["# ApplyTex configuration", ""]

    if provider == "gemini":
        api_key = Prompt.ask("Gemini API key (from aistudio.google.com)")
        model = Prompt.ask("Model", default="gemini-2.0-flash")
        env_lines.append(f"GEMINI_API_KEY={api_key}")
        env_lines.append(f"LLM_MODEL={model}")
    elif provider == "openai":
        api_key = Prompt.ask("OpenAI API key")
        model = Prompt.ask("Model", default="gpt-4o-mini")
        env_lines.append(f"OPENAI_API_KEY={api_key}")
        env_lines.append(f"LLM_MODEL={model}")
    elif provider == "local":
        url = Prompt.ask("Local LLM endpoint URL", default="http://localhost:8080/v1")
        model = Prompt.ask("Model name", default="local-model")
        env_lines.append(f"LLM_URL={url}")
        env_lines.append(f"LLM_MODEL={model}")

    env_lines.append("")
    ENV_PATH.write_text("\n".join(env_lines), encoding="utf-8")
    console.print(f"[green]AI configuration saved to {ENV_PATH}[/green]")


# ---------------------------------------------------------------------------
# Auto-Apply
# ---------------------------------------------------------------------------

def _setup_auto_apply() -> None:
    """Configure autonomous job application (requires Claude Code CLI)."""
    console.print(Panel(
        "[bold]Step 5: Auto-Apply (optional)[/bold]\n"
        "ApplyTex can autonomously fill and submit job applications\n"
        "using Claude Code as the browser agent."
    ))

    if not Confirm.ask("Enable autonomous job applications?", default=True):
        console.print("[dim]You can apply manually using the tailored resumes ApplyTex generates.[/dim]")
        return

    # Check for Claude Code CLI
    if shutil.which("claude"):
        console.print("[green]Claude Code CLI detected.[/green]")
    else:
        console.print(
            "[yellow]Claude Code CLI not found on PATH.[/yellow]\n"
            "Install it from: [bold]https://claude.ai/code[/bold]\n"
            "Auto-apply won't work until Claude Code is installed."
        )

    # Optional: CapSolver for CAPTCHAs
    console.print("\n[dim]Some job sites use CAPTCHAs. CapSolver can handle them automatically.[/dim]")
    if Confirm.ask("Configure CapSolver API key? (optional)", default=False):
        capsolver_key = Prompt.ask("CapSolver API key")
        # Append to existing .env or create
        if ENV_PATH.exists():
            existing = ENV_PATH.read_text(encoding="utf-8")
            if "CAPSOLVER_API_KEY" not in existing:
                ENV_PATH.write_text(
                    existing.rstrip() + f"\nCAPSOLVER_API_KEY={capsolver_key}\n",
                    encoding="utf-8",
                )
        else:
            ENV_PATH.write_text(f"# ApplyTex configuration\nCAPSOLVER_API_KEY={capsolver_key}\n", encoding="utf-8")
        console.print("[green]CapSolver key saved.[/green]")
    else:
        console.print("[dim]Skipped. Add CAPSOLVER_API_KEY to .env later if needed.[/dim]")


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_wizard() -> None:
    """Run the full interactive setup wizard."""
    console.print()
    console.print(
        Panel.fit(
            "[bold green]ApplyTex Setup Wizard[/bold green]\n\n"
            "This will create your configuration at:\n"
            f"  [cyan]{APP_DIR}[/cyan]\n\n"
            "You can re-run this anytime with [bold]applytex init[/bold].",
            border_style="green",
        )
    )

    ensure_dirs()
    console.print(f"[dim]Created {APP_DIR}[/dim]\n")

    # Step 1: Resume (LaTeX or legacy)
    latex_mode = _setup_resume()
    write_default_config(latex_enabled=latex_mode)
    from applytex.config import ensure_skill_adjacency

    ensure_skill_adjacency(force=True)  # force = sync latest clusters from package on re-run
    console.print(f"[dim]Wrote {APP_DIR / 'config.yaml'} and skill_adjacency.yaml[/dim]\n")
    console.print()

    # Step 2: Profile
    _setup_profile()
    console.print()

    # Step 3: Search config
    _setup_searches()
    console.print()

    # Step 4: AI features (optional LLM)
    _setup_ai_features()
    console.print()

    # Step 5: Auto-apply (Claude Code detection)
    _setup_auto_apply()
    console.print()

    # Done — show tier status
    from applytex.config import get_tier, TIER_LABELS, TIER_COMMANDS

    tier = get_tier()

    tier_lines: list[str] = []
    for t in range(1, 4):
        label = TIER_LABELS[t]
        cmds = ", ".join(f"[bold]{c}[/bold]" for c in TIER_COMMANDS[t])
        if t <= tier:
            tier_lines.append(f"  [green]✓ Tier {t} — {label}[/green]  ({cmds})")
        elif t == tier + 1:
            tier_lines.append(f"  [yellow]→ Tier {t} — {label}[/yellow]  ({cmds})")
        else:
            tier_lines.append(f"  [dim]✗ Tier {t} — {label}  ({cmds})[/dim]")

    unlock_hint = ""
    if tier == 1:
        unlock_hint = "\n[dim]To unlock Tier 2: configure an LLM API key (re-run [bold]applytex init[/bold]).[/dim]"
    elif tier == 2:
        unlock_hint = "\n[dim]To unlock Tier 3: install Claude Code CLI + Chrome.[/dim]"

    console.print(
        Panel.fit(
            "[bold green]Setup complete![/bold green]\n\n"
            f"[bold]Your tier: Tier {tier} — {TIER_LABELS[tier]}[/bold]\n\n"
            + "\n".join(tier_lines)
            + unlock_hint,
            border_style="green",
        )
    )
