# Changelog

All notable changes to ApplyTex will be documented in this file.

## [0.4.5] - 2026-07-02

### Fixed

- Streaming pipeline marks skipped stages on canonical order (not legacy tailor-only graph)
- Per-run upstream graph: `cover` waits on `latex` when LaTeX is in the run
- `pipeline.default_stages` from `config.yaml` respected for `applytex run all`
- JobSpy, Workday, and smart-extract honor `jobspy_max_tier` / `workday_max_tier` query tiers
- `--min-score` defaults to `pipeline.min_score` from `config.yaml` (default 8)

### Changed

- Init wizard default search radius: 50 miles (was 0)
- Init wizard emits queries with `tier: 1` only

## [0.4.4] - 2026-07-02

### Fixed

- Glassdoor JobSpy scrape passes `country_indeed` (was missing)
- `exclude_titles` enforced in Workday and smart-extract discovery
- Smart extract expands `{location_encoded}` for **all** `locations[]` (local first)
- LaTeX init: `.zip` import, validate custom `\documentclass` requires matching `.cls`
- `applytex doctor` fails when custom document class is missing its `.cls`

## [0.4.3] - 2026-07-01

### Fixed

- **`searches.yaml` schema aligned with JobSpy** — `sites` (legacy `boards` alias), `defaults.country_indeed` (legacy top-level `country` alias)
- **Init wizard** emits complete search config: sites, country, location filters, `exclude_titles`
- **`exclude_titles`** enforced during JobSpy discovery
- **Legacy `applypilot.db`** auto-used when `applytex.db` missing; `applytex doctor` shows rename hint
- Invalid bare-string `locations` entries skipped with warning

## [0.4.2] - 2026-06-29

### Fixed

- Approve/reject resolve URLs with query params via `normalize_job_url` / `resolve_job_url`
- `applytex apply` precheck only counts **approved** jobs (matches `acquire_job` gate)
- Discovery location filters read `location.accept_patterns` / `reject_patterns` from `searches.yaml`

## [0.4.1] - 2026-06-29

### Added

- E2E tests: add → pending → approve → `acquire_job` (`tests/test_e2e_flow.py`)
- Validator unit tests for gap terms and sacred-zone adjacent swaps

### Changed

- `applytex add` — clearer status hints, non-zero exit on failures, Playwright error handling
- `applytex doctor` — Playwright check for `add` / enrich
- `acquire_job(--url)` — include jobs with `NULL` apply_status (fixes `apply --url` after approve)

## [0.4.0] - 2026-06-29

### Added

- **`applytex add URL`** — manual job URL: enrich → score → LaTeX Keyword Match (when above threshold)
- **`applytex registry`** — tailored resume variants with match scores, flags, review status (`--pending`, `--approved`, `--json`)
- **Resume Registry** section in `applytex view` dashboard — match bars, adjustments, PDF/tex links, approve hints
- `registry.py` and `jobs/add.py` modules
- Tests for registry and add flows

## [0.3.0] - 2026-07-01

### Added

- **Keyword Match** LaTeX pipeline (`applytex run latex` or default `run all` with LaTeX enabled)
- Modules: `keywords`, `placement`, `tailor_plan`, `patch`, `validator`, `compiler`, `tailor`, `review`
- Per-job outputs: `{prefix}.tex`, `.pdf`, `.txt`, `_KEYWORD_PLAN.json`, `_KEYWORD_REPORT.json`
- `applytex review --pending | --approve | --reject`
- DB columns: `tailored_latex_path`, `keyword_report_path`, `review_status`, match scores
- `skill_adjacency.example.yaml` copied on init
- Auto-apply gated on `review_status = approved` (unless `keyword_policy.auto_release: true`)

## [0.2.0] - 2026-07-01

### Added

- LaTeX-first `applytex init`: copy `master.tex` + assets to `~/.applytex/latex/`
- `latex/text_export.py` — derive `resume.txt` from LaTeX for scoring
- `latex/import_source.py` — import single `.tex` or Overleaf folder
- `~/.applytex/config.yaml` on init (`latex.enabled`, `pipeline`, `cover`)
- `applytex doctor` checks: `master.tex`, `resume.cls`, tectonic/pdflatex
- Legacy resume mode (`latex.enabled: false`) preserves plain-text ApplyPilot flow

## [0.1.0] - 2026-07-01

### Added

- Fork of ApplyPilot v0.3.0 rebranded as **ApplyTex** (`applytex` CLI, `~/.applytex/` data dir)
- `NOTICE` with upstream AGPL attribution
- `IMPLEMENTATION_PLAN.md` for LaTeX + Keyword Match roadmap
- `applytex doctor` migration hint when `~/.applypilot` exists without `~/.applytex`

---

## Upstream ApplyPilot history

All notable changes to ApplyPilot will be documented below.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-02-17

### Added
- **Parallel workers for discovery/enrichment** - `applypilot run --workers N` enables
  ThreadPoolExecutor-based parallelism for Workday scraping, smart extract, and detail
  enrichment. Default is sequential (1); power users can scale up.
- **Apply utility modes** - `--gen` (generate prompt for manual debugging), `--mark-applied`,
  `--mark-failed`, `--reset-failed` flags on `applypilot apply`
- **Dry-run mode** - `applypilot apply --dry-run` fills forms without clicking Submit
- **5 new tracking columns** - `agent_id`, `last_attempted_at`, `apply_duration_ms`,
  `apply_task_id`, `verification_confidence` for better apply-stage observability
- **Manual ATS detection** - `manual_ats` list in `config/sites.yaml` skips sites with
  unsolvable CAPTCHAs (e.g. TCS iBegin)
- **Qwen3 `/no_think` optimization** - automatically saves tokens when using Qwen models
- **`config.DEFAULTS`** - centralized dict for magic numbers (`min_score`, `max_apply_attempts`,
  `poll_interval`, `apply_timeout`, `viewport`)

### Fixed
- **Config YAML not found after install** - moved `config/` into the package at
  `src/applypilot/config/` so YAML files (employers, sites, searches) ship with `pip install`
- **Search config format mismatch** - wizard wrote `searches:` key but discovery code
  expected `queries:` with tier support. Aligned wizard output and example config
- **JobSpy install isolation** - removed python-jobspy from package dependencies due to
  broken numpy==1.26.3 exact pin in jobspy metadata. Installed separately with `--no-deps`
- **Scoring batch limit** - default limit of 50 silently left jobs unscored across runs.
  Changed to no limit (scores all pending jobs in one pass)
- **Missing logging output** - added `logging.basicConfig(INFO)` so per-job progress for
  scoring, tailoring, and cover letters is visible during pipeline runs

### Changed
- **Blocked sites externalized** - moved from hardcoded sets in launcher.py to
  `config/sites.yaml` under `blocked:` key
- **Site base URLs externalized** - moved from hardcoded dict in detail.py to
  `config/sites.yaml` under `base_urls:` key
- **SSO domains externalized** - moved from hardcoded list in prompt.py to
  `config/sites.yaml` under `blocked_sso:` key
- **Prompt improvements** - screening context uses `target_role` from profile,
  salary section includes `currency_conversion_note` and dynamic hourly rate examples
- **`acquire_job()` fixed** - writes `agent_id` and `last_attempted_at` to proper columns
  instead of misusing `apply_error`
- **`profile.example.json`** - added `currency_conversion_note` and `target_role` fields

## [0.1.0] - 2026-02-17

### Added
- 6-stage pipeline: discover, enrich, score, tailor, cover letter, apply
- Multi-source job discovery: Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs
- Workday employer portal support (46 preconfigured employers)
- Direct career site scraping (28 preconfigured sites)
- 3-tier job description extraction cascade (JSON-LD, CSS selectors, AI fallback)
- AI-powered job scoring (1-10 fit scale with rationale)
- Resume tailoring with factual preservation (no fabrication)
- Cover letter generation per job
- Autonomous browser-based application submission via Playwright
- Interactive setup wizard (`applypilot init`)
- Cross-platform Chrome/Chromium detection (Windows, macOS, Linux)
- Multi-provider LLM support (Gemini, OpenAI, local models via OpenAI-compatible endpoints)
- Pipeline stats and HTML results dashboard
- YAML-based configuration for employers, career sites, and search queries
- Job deduplication across sources
- Configurable score threshold filtering
- Safety limits for maximum applications per run
- Detailed application results logging
