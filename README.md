# ApplyTex

**LaTeX-native job application pipeline** — fork of [ApplyPilot](https://github.com/Pickle-Pixel/ApplyPilot) v0.3.0 by Pickle-Pixel (AGPL-3.0).

ApplyTex keeps ApplyPilot's job discovery, LLM scoring, and optional browser auto-apply. The LaTeX path adds:

- **`master.tex` as your canonical resume** — copied from Overleaf or a local folder at `init`
- **Keyword Match** — zone-aware JD keyword alignment on your `.tex`, with flagged adjustments
- **Approve-before-apply** — review tailored PDFs before they enter the apply queue
- **Per-job PDF compile** from your template (`.cls` / `.sty`)
- **Registry** — tailored variant ↔ job URL in the CLI and HTML dashboard

User data lives in **`~/.applytex/`** (override with `APPLYTEX_DIR`).

> Developer reference: [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md)

---

## What you need (tiers)

| Tier | Unlocks | Requirements |
|------|---------|--------------|
| **1 — Discovery** | `init`, `run discover`, `run enrich`, `status`, `dashboard` | Python 3.11+, JobSpy, Playwright |
| **2 — AI scoring & LaTeX** | `run score`, `run latex`, `review`, `add`, `registry` | LLM API key in `~/.applytex/.env` |
| **3 — Auto-apply** | `apply` | Tier 2 + [Claude Code CLI](https://claude.ai/code) + Chrome + Node.js |

Run `applytex doctor` anytime to see what is missing.

---

## Installation

### 1. Clone and install ApplyTex

```bash
git clone <your-applytex-repo-url> ApplyTex
cd ApplyTex

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e .
applytex --version                   # should print 0.4.5+
```

### 2. Install JobSpy (job board scraping)

JobSpy is installed separately because of dependency pin conflicts:

```bash
pip install --no-deps python-jobspy
pip install pydantic tls-client requests markdownify regex
```

### 3. Install Playwright (enrichment + single-job add)

```bash
playwright install chromium
```

### 4. Install a LaTeX engine (Keyword Match PDF compile)

Pick one:

```bash
# Recommended — lightweight, no full TeX Live install
brew install tectonic              # macOS
# or: cargo install tectonic

# Alternative
# Install TeX Live, then ensure pdflatex is on PATH
```

Set the engine in `~/.applytex/config.yaml` (`latex.engine: tectonic` or `pdflatex`).

### 5. Verify

```bash
applytex doctor
```

Fix anything marked **MISSING** before continuing.

---

## First-time setup (`applytex init`)

The wizard creates everything under `~/.applytex/`:

```
~/.applytex/
  latex/master.tex          ← your resume source (copied in)
  latex/resume.cls          ← class/style files (if present)
  resume.txt                ← plain text derived for scoring
  profile.json              ← personal info for scoring + auto-fill
  searches.yaml             ← job boards, locations, queries
  config.yaml               ← pipeline + LaTeX settings
  skill_adjacency.yaml      ← keyword cluster rules
  .env                      ← LLM API keys
  applytex.db               ← job database
  tailored_resumes/         ← per-job .tex, .pdf, .txt outputs
```

### Run the wizard

```bash
applytex init
```

You will be prompted for:

1. **LaTeX resume** — path to a single `.tex` file, an Overleaf export folder, or a `.zip`. ApplyTex **copies** files into `~/.applytex/latex/`; your original path is not used at runtime.
2. **Profile** — name, email, work authorization, compensation, skills boundary, preserved resume facts.
3. **Search config** — target location, search radius, job titles/queries, Indeed country.
4. **LLM provider** — Gemini (free tier friendly), OpenAI, Anthropic-compatible (e.g. DeepSeek), or local Ollama.

After init, run `applytex doctor` again to confirm LaTeX assets and API keys.

### Migrating from ApplyPilot

```bash
mv ~/.applypilot ~/.applytex
# or keep the old dir:
export APPLYTEX_DIR=~/.applypilot
```

If you have `applypilot.db` but not `applytex.db`, ApplyTex uses the legacy DB automatically; `doctor` shows a rename hint.

---

## Configuration files

### `~/.applytex/config.yaml`

```yaml
latex:
  enabled: true
  engine: tectonic

pipeline:
  default_stages: [discover, enrich, score, latex]
  min_score: 8                    # used when --min-score is omitted

cover:
  enabled: false

keyword_policy:
  auto_release: false             # true = skip review gate (power users)
```

### `~/.applytex/searches.yaml`

Controls **where** and **what** to search. Key sections:

- `sites` — JobSpy boards (`indeed`, `linkedin`, `glassdoor`, …). Legacy `boards:` alias still works.
- `defaults.country_indeed` — Indeed/Glassdoor country (`usa`, `canada`, …).
- `locations[]` — search locations; each entry has `location` and `remote`.
- `location.accept_patterns` / `reject_patterns` — post-filter discovered jobs.
- `queries[]` — search strings with optional `tier` (1 = highest priority).
- `jobspy_max_tier` — max query tier for all discovery scrapers (default `2`).
- `exclude_titles` — skip jobs whose title contains these strings.

See [`src/applytex/config/searches.example.yaml`](./src/applytex/config/searches.example.yaml) for a full example.

### `~/.applytex/.env`

LLM keys (pick one provider):

```bash
# Gemini
GEMINI_API_KEY=your_key
LLM_MODEL=gemini-2.0-flash

# OpenAI
# OPENAI_API_KEY=your_key

# Anthropic-compatible (e.g. DeepSeek)
# ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
# ANTHROPIC_AUTH_TOKEN=your_key
# ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-flash

# Local
# LLM_URL=http://localhost:11434/v1
# LLM_MODEL=llama3
```

Optional for auto-apply: `CAPSOLVER_API_KEY`, `CHROME_PATH`, `APPLYTEX_DIR`.

---

## Step-by-step: full pipeline workflow

This is the default **semi-auto** flow: discover → score → tailor → **you approve** → apply.

### Step 1 — Discover jobs

Scrapes Indeed/LinkedIn (JobSpy), Workday employer portals, and configured career sites:

```bash
applytex run discover
# or run discovery + enrichment together:
applytex run discover enrich

# parallel discovery/enrichment:
applytex run discover enrich --workers 4
```

Check progress:

```bash
applytex status
```

Edit `~/.applytex/searches.yaml` to tune boards, locations, queries, and title filters, then re-run discover.

### Step 2 — Enrich job descriptions (if not done in Step 1)

Fetches full descriptions and application URLs:

```bash
applytex run enrich
applytex run enrich --workers 4
```

### Step 3 — Score jobs against your resume

Compares each job description to `~/.applytex/resume.txt` (derived from your LaTeX at init):

```bash
applytex run score
```

Scores are 1–10. Only jobs at or above `pipeline.min_score` (default **8**) proceed to tailoring. Override per run:

```bash
applytex run score
applytex run latex --min-score 7    # when running latex alone
```

### Step 4 — LaTeX Keyword Match (tailor + compile)

For each high-scoring job, ApplyTex:

1. Extracts JD keywords
2. Builds a keyword plan (exact / adjacent / gap)
3. Patches `master.tex` (sacred zone = current role; flex zone = older roles)
4. Compiles `{prefix}.pdf` and writes `{prefix}.txt` for the apply agent
5. Sets `review_status = pending` (unless `keyword_policy.auto_release: true`)

```bash
applytex run latex
# or run the default pipeline in one command:
applytex run all
# equivalent to config.yaml default_stages: discover enrich score latex
```

Outputs per job in `~/.applytex/tailored_resumes/`:

```
{prefix}.tex
{prefix}.pdf
{prefix}.txt                    ← used by auto-apply for form fields
{prefix}_KEYWORD_PLAN.json
{prefix}_KEYWORD_REPORT.json    ← human-readable adjustment flags
```

### Step 5 — Review flagged adjustments

List jobs awaiting your approval:

```bash
applytex review --pending
applytex registry --pending
applytex dashboard              # opens HTML dashboard with registry section
```

Inspect the PDF and `_KEYWORD_REPORT.json` adjustments (e.g. adjacent swaps on older projects). Then:

```bash
applytex review --approve --url "https://boards.greenhouse.io/company/jobs/123"
# or reject:
applytex review --reject --url "https://..."
```

Only **approved** jobs get `tailored_resume_path` set and appear in the apply queue.

### Step 6 — Auto-apply (optional, Tier 3)

Requires Claude Code CLI, Chrome, and Node.js (`npx`).

Dry-run first (fills forms, does not click Submit):

```bash
applytex apply --dry-run --url "https://boards.greenhouse.io/company/jobs/123"
```

Apply to one approved job:

```bash
applytex apply --url "https://..."
```

Apply to the highest-scoring approved jobs in queue:

```bash
applytex apply --limit 5
applytex apply --continuous      # poll forever for new approved jobs
```

Utility flags:

```bash
applytex apply --mark-applied "URL"
applytex apply --mark-failed "URL" --fail-reason "captcha"
applytex apply --reset-failed
applytex apply --gen --url "URL"   # dump prompt for manual debugging
```

---

## Step-by-step: single job URL

When you find one posting outside the discovery crawl:

```bash
applytex add "https://boards.greenhouse.io/company/jobs/456"
```

This runs: **insert → enrich → score → LaTeX Keyword Match** (if score ≥ threshold).

Then review and apply as above:

```bash
applytex review --pending
applytex review --approve --url "https://..."
applytex apply --dry-run --url "https://..."
```

---

## Step-by-step: run everything at once

```bash
# Sequential (default) — stages run one after another
applytex run all

# Streaming — stages overlap (discover feeds enrich feeds score, etc.)
applytex run all --stream

# Custom subset
applytex run discover enrich score latex

# Preview without executing
applytex run all --dry-run
```

`--min-score` defaults to `pipeline.min_score` in `config.yaml` when omitted.

---

## Command reference

| Command | Description |
|---------|-------------|
| `applytex init` | First-time setup wizard |
| `applytex doctor` | Check dependencies, config, LaTeX assets, API keys |
| `applytex run [stages]` | Pipeline: `discover`, `enrich`, `score`, `latex`, `tailor`, `cover`, `pdf`, or `all` |
| `applytex status` | DB stats and score distribution |
| `applytex add URL` | Single job: enrich → score → latex |
| `applytex review --pending` | List jobs awaiting approval |
| `applytex review --approve --url URL` | Approve tailored resume for apply |
| `applytex review --reject --url URL` | Reject a pending variant |
| `applytex registry` | CLI table of tailored variants (`--pending`, `--approved`, `--json`) |
| `applytex dashboard` | Generate and open HTML dashboard |
| `applytex apply` | Browser auto-apply (Tier 3) |

Common flags: `--min-score N`, `--workers N`, `--stream`, `--dry-run`, `--validation strict|normal|lenient`.

---

## Legacy mode (plain-text ApplyPilot flow)

Disable LaTeX in `~/.applytex/config.yaml`:

```yaml
latex:
  enabled: false
```

Then the default pipeline uses plain-text `tailor` + optional `cover` + `pdf` instead of `latex`, with no review gate (unless you add one manually). Useful if you do not have a LaTeX resume.

```bash
applytex run all                  # discover → enrich → score → tailor
applytex run score tailor cover   # LLM-only stages
```

---

## Troubleshooting

| Problem | What to do |
|---------|------------|
| `applytex doctor` shows missing JobSpy | Install JobSpy separately (see Installation §2) |
| LaTeX compile fails | Run `applytex doctor`; ensure `tectonic` or `pdflatex` on PATH; re-run `init` with full folder including `.cls` |
| No jobs after discover | Check `searches.yaml` sites, locations, `exclude_titles`; run `applytex status` |
| Jobs scored but not tailored | Score may be below `min_score`; lower in config or `--min-score` |
| `apply` says no approved resumes | Run `applytex review --pending` then `--approve` |
| Pending review but compile error | Fix LaTeX assets; re-run `applytex run latex` for that job |
| Migrating from ApplyPilot | `mv ~/.applypilot ~/.applytex` or set `APPLYTEX_DIR` |

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -q
```

---

## License

AGPL-3.0 — see [LICENSE](./LICENSE) and [NOTICE](./NOTICE). Based on ApplyPilot (Pickle-Pixel).
