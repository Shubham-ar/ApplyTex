# ApplyTex

**LaTeX-native job application pipeline** — fork of [ApplyPilot](https://github.com/Pickle-Pixel/ApplyPilot) v0.3.0 (AGPL-3.0).

Discover jobs, score them against your resume, auto-tailor your LaTeX resume per job, then auto-apply through browsers.

---

## Quick Start

### What you need

| Tier | What you can do | Requirements |
|------|----------------|-------------|
| **1 — Discovery** | `discover`, `enrich`, `status`, `dashboard` | Python 3.11+, [JobSpy](#2-install-jobspy), [Playwright](#3-install-playwright) |
| **2 — AI scoring & tailoring** | `score`, `latex`, `review`, `add`, `registry` | LLM API key (DeepSeek/Gemini/OpenAI) |
| **3 — Auto-apply** | `apply` | Tier 2 + [Claude Code CLI](https://claude.ai/code) + Chrome + Node.js |

Run `applytex doctor` anytime to see what's missing.

### 1. Clone and install

```bash
git clone <your-applytex-repo-url> ApplyTex
cd ApplyTex

python3 -m venv .venv
source .venv/bin/activate

pip install -e .
applytex --version        # should print 0.4.5+
```

### 2. Install JobSpy (job discovery)

```bash
pip install --no-deps python-jobspy
pip install pydantic tls-client requests markdownify regex
```

### 3. Install Playwright (enrichment)

```bash
playwright install chromium
```

### 4. Install LaTeX engine (PDF compile)

```bash
# Recommended — lightweight
brew install tectonic
# or: cargo install tectonic
```

### 5. Set up your LLM (AI features)

Create `~/.applytex/.env`:

```bash
# DeepSeek (cheap, fast — recommended for scoring + tailoring)
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN=your_deepseek_api_key
ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-flash
LLM_MODEL=deepseek-v4-flash

# Or Gemini (free tier)
# GEMINI_API_KEY=your_key
# LLM_MODEL=gemini-2.0-flash

# Or OpenAI
# OPENAI_API_KEY=your_key
```

> **Tip:** Use DeepSeek for scoring/tailoring (cheap). If you also enable auto-apply (Tier 3), Claude Code uses its own model — you can keep DeepSeek for everything else.

### 6. Run the setup wizard

```bash
applytex init
```

This walks you through:
- **LaTeX resume** — path to your `.tex` file, Overleaf export folder, or `.zip`
- **Profile** — name, email, work auth, skills, preserved resume facts
- **Search config** — locations, job titles, Indeed country
- **AI provider** — API key for scoring + tailoring

### 7. Run the pipeline

```bash
# Full pipeline: discover → enrich → score → latex
applytex run all

# Or step by step:
applytex run discover         # find jobs
applytex run score            # score them against your resume
applytex run latex            # tailor + compile PDFs per job
```

### 8. Review and apply

```bash
applytex review --pending     # see what needs approval
applytex dashboard            # open HTML dashboard in browser

# Approve a tailored resume:
applytex review --approve --url "https://boards.greenhouse.io/..."

# Auto-apply (Tier 3 — needs Claude Code + Chrome):
applytex apply --dry-run --limit 3   # dry run first
applytex apply --limit 5              # real apply
```

---

## Detailed Documentation

### What ApplyTex does

ApplyTex takes you from zero to submitted applications:

1. **Discover** — scrapes Indeed, LinkedIn, Workday employer portals, and 50+ career sites
2. **Enrich** — fetches full job descriptions and application URLs
3. **Score** — LLM evaluates fit (1-10) against your resume
4. **Gap Insights** — analyze what skills are commonly missing across borderline jobs to improve your base resume
5. **LaTeX Keyword Match** — extracts JD keywords, patches your `master.tex`, compiles a tailored PDF per job, flags all adjustments
6. **Review** — you inspect the PDF and adjustment report, then approve or reject
7. **Apply** — launches Chrome + Claude Code to autonomously fill and submit applications

### Directory layout

All user data lives in `~/.applytex/`:

```
~/.applytex/
  latex/master.tex          ← your canonical resume (copied at init)
  latex/resume.cls          ← document class file
  resume.txt                ← plain text for scoring
  profile.json              ← your personal info
  searches.yaml             ← job boards, locations, queries
  config.yaml               ← pipeline + LaTeX settings
  skill_adjacency.yaml      ← keyword cluster rules
  .env                      ← LLM API keys
  applytex.db               ← SQLite job database
  tailored_resumes/         ← per-job .tex, .pdf, .txt outputs
```

### Configuration files

#### `~/.applytex/config.yaml`

```yaml
latex:
  enabled: true
  engine: tectonic

pipeline:
  default_stages: [discover, enrich, score, latex]
  min_score: 8

cover:
  enabled: false

keyword_policy:
  auto_release: false       # true = skip review gate
```

#### `~/.applytex/searches.yaml`

Controls where and what to search:

- `sites` — JobSpy boards: `indeed`, `linkedin`, `glassdoor`, `zip_recruiter`
- `defaults.country_indeed` — `usa`, `canada`, `uk`, etc.
- `locations[]` — search locations with optional `remote` flag
- `location.accept_patterns` / `reject_patterns` — post-filter results
- `queries[]` — search strings with optional `tier` (1 = highest priority)
- `exclude_titles` — skip jobs matching these patterns

#### `~/.applytex/.env`

```bash
# Pick one provider:
GEMINI_API_KEY=your_key
# OPENAI_API_KEY=your_key
# ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
# ANTHROPIC_AUTH_TOKEN=your_key
# LLM_URL=http://localhost:11434/v1
# LLM_MODEL=llama3
```

### Full pipeline workflow

#### Step 1 — Discover jobs

```bash
applytex run discover
applytex run discover enrich --workers 4   # parallel
```

#### Step 2 — Enrich (if not done in Step 1)

```bash
applytex run enrich
applytex run enrich --workers 4
```

#### Step 3 — Score jobs

```bash
applytex run score
```

Only jobs ≥ `pipeline.min_score` (default **8**) proceed to tailoring.

#### Step 3a — Resume gap insights

```bash
applytex analyze                  # default: jobs scoring 5-6
applytex analyze --min-score 4    # custom range
applytex analyze --llm            # include AI recommendations (1 LLM call)
applytex analyze --json           # machine-readable output
```

Shows which skills/technologies are **most frequently missing** from your resume across jobs in a score range. Helps prioritize what to add to your base resume (e.g., "Python missing in 46% of borderline jobs, AWS in 30%"). The `--llm` flag makes one LLM call for actionable recommendations on which gaps are worth addressing.

#### Step 4 — LaTeX Keyword Match (tailor + compile)

For each high-scoring job, ApplyTex:
1. Extracts JD keywords via LLM
2. Classifies them: `exact` / `adjacent` / `gap` / `blocked`
3. Detects **sacred zone** (current role — rephrase only) vs **flex zone** (older roles — can add adjacent skills)
4. Builds a keyword plan, patches `master.tex` via LLM
5. Compiles PDF, exports plain text, generates keyword report
6. Sets `review_status = pending`

```bash
applytex run latex
applytex run latex --workers 10           # parallel
```

Outputs per job in `~/.applytex/tailored_resumes/`:
- `{prefix}.tex` / `.pdf` / `.txt`
- `{prefix}_KEYWORD_PLAN.json`
- `{prefix}_KEYWORD_REPORT.json` — human-readable adjustments

#### Step 5 — Review and approve

```bash
applytex review --pending
applytex review --approve --url "https://..."
applytex review --reject --url "https://..."
```

#### Step 6 — Auto-apply (Tier 3)

```bash
applytex apply --dry-run --url "https://..."       # fills form, no Submit
applytex apply --url "https://..."                  # single job
applytex apply --limit 5                            # top N approved jobs
applytex apply --continuous                         # poll forever
```

Utility flags:
```bash
applytex apply --mark-applied "URL"
applytex apply --mark-failed "URL" --fail-reason "captcha"
applytex apply --reset-failed
```

### Single job URL

```bash
applytex add "https://boards.greenhouse.io/company/jobs/456"
```

Runs: insert → enrich → score → LaTeX Keyword Match (if score ≥ threshold). Then review and apply.

### Running everything at once

```bash
# Sequential (default)
applytex run all

# Streaming — stages overlap
applytex run all --stream

# Custom stages
applytex run discover enrich score latex

# Custom score threshold
applytex run latex --min-score 7
```

### Command reference

| Command | Description |
|---------|-------------|
| `applytex init` | First-time setup wizard |
| `applytex doctor` | Check dependencies, config, API keys |
| `applytex run [stages]` | Pipeline: `discover`, `enrich`, `score`, `tailor`, `latex`, `cover`, `pdf`, or `all` |
| `applytex status` | DB stats and score distribution |
| `applytex add URL` | Single job: enrich → score → latex |
| `applytex review --pending` | List jobs awaiting approval |
| `applytex review --approve --url URL` | Approve for apply |
| `applytex review --reject --url URL` | Reject a variant |
| `applytex registry` | CLI table of tailored variants (`--pending`, `--approved`, `--json`) |
| `applytex analyze` | Aggregate gap insights — find what skills your resume is missing across a score range |
| `applytex dashboard` | Generate and open HTML dashboard |
| `applytex apply` | Browser auto-apply (Tier 3) |

Common flags: `--min-score N`, `--workers N`, `--stream`, `--dry-run`, `--validation strict|normal|lenient`.

### Validation modes

| Mode | Banned words | LLM Judge | Use case |
|------|-------------|-----------|----------|
| `strict` | Errors (retry) | Must pass | Production |
| `normal` | Warnings only | Can fail on last retry | Default |
| `lenient` | Ignored | Skipped | Fastest, fewest API calls |

### Legacy mode (plain text, no LaTeX)

```yaml
# ~/.applytex/config.yaml
latex:
  enabled: false
```

Then the pipeline uses plain-text `tailor` + optional `cover` + `pdf` instead of `latex`, with no review gate.

### Troubleshooting

| Problem | What to do |
|---------|------------|
| `doctor` shows missing JobSpy | Install separately (see Quick Start §2) |
| LaTeX compile fails | Run `doctor`; ensure `tectonic` on PATH; re-run `init` with folder including `.cls` |
| No jobs after discover | Check `searches.yaml` sites, locations, `exclude_titles`; run `status` |
| Jobs scored but not tailored | Score below `min_score`; lower threshold via `--min-score` |
| `apply` says no approved resumes | Run `review --pending` then `--approve` |
| Pending review but compile error | Fix LaTeX assets; re-run `applytex run latex` |
| `apply` needs Claude Code | Install from https://claude.ai/code |
| Migrating from ApplyPilot | `mv ~/.applypilot ~/.applytex` or set `APPLYTEX_DIR` |

### Development

```bash
pip install -e ".[dev]"
pytest tests/ -q
```

### License

AGPL-3.0 — see [LICENSE](./LICENSE) and [NOTICE](./NOTICE). Based on ApplyPilot v0.3.0 by Pickle-Pixel.
