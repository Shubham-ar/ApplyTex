"""ApplyTex configuration: paths, platform detection, user data."""

import os
import platform
import shutil
from pathlib import Path

# User data directory — all user-specific files live here
APP_DIR = Path(
    os.environ.get(
        "APPLYTEX_DIR",
        os.environ.get("APPLYPILOT_DIR", Path.home() / ".applytex"),
    )
)

# Core paths
DB_PATH = APP_DIR / "applytex.db"
LEGACY_DB_PATH = APP_DIR / "applypilot.db"


def get_db_path() -> Path:
    """Resolve SQLite DB path, falling back to legacy applypilot.db after dir rename."""
    if DB_PATH.exists():
        return DB_PATH
    if LEGACY_DB_PATH.exists():
        return LEGACY_DB_PATH
    return DB_PATH
PROFILE_PATH = APP_DIR / "profile.json"
RESUME_PATH = APP_DIR / "resume.txt"
RESUME_PDF_PATH = APP_DIR / "resume.pdf"
SEARCH_CONFIG_PATH = APP_DIR / "searches.yaml"
ENV_PATH = APP_DIR / ".env"
CONFIG_PATH = APP_DIR / "config.yaml"

# LaTeX resume source (canonical after init)
LATEX_DIR = APP_DIR / "latex"
MASTER_TEX_PATH = LATEX_DIR / "master.tex"
MASTER_CLS_PATH = LATEX_DIR / "resume.cls"

SKILL_ADJACENCY_PATH = APP_DIR / "skill_adjacency.yaml"

# Generated output
TAILORED_DIR = APP_DIR / "tailored_resumes"
COVER_LETTER_DIR = APP_DIR / "cover_letters"
LOG_DIR = APP_DIR / "logs"

# Chrome worker isolation
CHROME_WORKER_DIR = APP_DIR / "chrome-workers"
APPLY_WORKER_DIR = APP_DIR / "apply-workers"

# Package-shipped config (YAML registries)
PACKAGE_DIR = Path(__file__).parent
CONFIG_DIR = PACKAGE_DIR / "config"


def get_chrome_path() -> str:
    """Auto-detect Chrome/Chromium executable path, cross-platform.

    Override with CHROME_PATH environment variable.
    """
    env_path = os.environ.get("CHROME_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    system = platform.system()

    if system == "Windows":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
    elif system == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
    else:  # Linux
        candidates = []
        for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    for c in candidates:
        if c and c.exists():
            return str(c)

    # Fall back to PATH search
    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found

    raise FileNotFoundError(
        "Chrome/Chromium not found. Install Chrome or set CHROME_PATH environment variable."
    )


def get_chrome_user_data() -> Path:
    """Default Chrome user data directory, cross-platform."""
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    else:
        return Path.home() / ".config" / "google-chrome"


def ensure_dirs():
    """Create all required directories."""
    for d in [
        APP_DIR,
        LATEX_DIR,
        TAILORED_DIR,
        COVER_LETTER_DIR,
        LOG_DIR,
        CHROME_WORKER_DIR,
        APPLY_WORKER_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


_DEFAULT_APP_CONFIG: dict = {
    "latex": {"enabled": True, "engine": "tectonic"},
    "pipeline": {
        "default_stages": ["discover", "enrich", "score", "latex"],
        "min_score": 8,
    },
    "cover": {"enabled": False},
    "keyword_policy": {"auto_release": False},
}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_app_config() -> dict:
    """Load ~/.applytex/config.yaml merged with package defaults."""
    import yaml

    cfg = dict(_DEFAULT_APP_CONFIG)
    if CONFIG_PATH.exists():
        user_cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        cfg = _deep_merge(cfg, user_cfg)
    return cfg


def is_latex_enabled() -> bool:
    """Whether the LaTeX pipeline is active (vs legacy plain-text tailor)."""
    return bool(load_app_config().get("latex", {}).get("enabled", True))


def latex_engine() -> str:
    """LaTeX compiler: tectonic or pdflatex."""
    return str(load_app_config().get("latex", {}).get("engine", "tectonic")).lower()


def write_default_config(*, latex_enabled: bool = True) -> Path:
    """Write config.yaml from the shipped example, optionally toggling latex."""
    import yaml

    example = CONFIG_DIR / "config.example.yaml"
    if example.exists():
        data = yaml.safe_load(example.read_text(encoding="utf-8")) or {}
    else:
        data = dict(_DEFAULT_APP_CONFIG)

    data.setdefault("latex", {})
    data["latex"]["enabled"] = latex_enabled
    CONFIG_PATH.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")
    return CONFIG_PATH


def find_latex_compiler() -> str | None:
    """Return path to configured LaTeX engine if available on PATH."""
    engine = latex_engine()
    if engine == "tectonic":
        return shutil.which("tectonic")
    if engine == "pdflatex":
        return shutil.which("pdflatex")
    return shutil.which(engine)


def keyword_auto_release() -> bool:
    """If True, skip review gate and set jobs apply-ready immediately."""
    cfg = load_app_config()
    if "keyword_policy" in cfg:
        return bool(cfg["keyword_policy"].get("auto_release", False))
    adj = load_skill_adjacency()
    return bool(adj.get("keyword_policy", {}).get("auto_release", False))


def load_skill_adjacency() -> dict:
    """Load skill cluster config from ~/.applytex/skill_adjacency.yaml."""
    import yaml

    path = SKILL_ADJACENCY_PATH
    if not path.exists():
        example = CONFIG_DIR / "skill_adjacency.example.yaml"
        if example.exists():
            return yaml.safe_load(example.read_text(encoding="utf-8")) or {}
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def ensure_skill_adjacency(*, force: bool = False) -> Path:
    """Copy example skill_adjacency.yaml to APP_DIR if missing (or force)."""
    example = CONFIG_DIR / "skill_adjacency.example.yaml"
    if not example.exists():
        return SKILL_ADJACENCY_PATH

    if force and SKILL_ADJACENCY_PATH.exists():
        # Back up the old file before overwriting
        backup = SKILL_ADJACENCY_PATH.with_suffix(".yaml.bak")
        shutil.copy2(SKILL_ADJACENCY_PATH, backup)
        SKILL_ADJACENCY_PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        return SKILL_ADJACENCY_PATH

    if not SKILL_ADJACENCY_PATH.exists():
        shutil.copy2(example, SKILL_ADJACENCY_PATH)

    return SKILL_ADJACENCY_PATH


def load_profile() -> dict:
    """Load user profile from ~/.applytex/profile.json."""
    import json
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"Profile not found at {PROFILE_PATH}. Run `applytex init` first."
        )
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def load_search_config() -> dict:
    """Load search configuration from ~/.applytex/searches.yaml."""
    import yaml

    from applytex.discovery.search_config import normalize_search_config

    if not SEARCH_CONFIG_PATH.exists():
        # Fall back to package-shipped example
        example = CONFIG_DIR / "searches.example.yaml"
        if example.exists():
            return normalize_search_config(
                yaml.safe_load(example.read_text(encoding="utf-8"))
            )
        return {}
    raw = yaml.safe_load(SEARCH_CONFIG_PATH.read_text(encoding="utf-8"))
    return normalize_search_config(raw)


def load_sites_config() -> dict:
    """Load sites.yaml configuration (sites list, manual_ats, blocked, etc.)."""
    import yaml
    path = CONFIG_DIR / "sites.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def is_manual_ats(url: str | None) -> bool:
    """Check if a URL routes through an ATS that requires manual application."""
    if not url:
        return False
    sites_cfg = load_sites_config()
    domains = sites_cfg.get("manual_ats", [])
    url_lower = url.lower()
    return any(domain in url_lower for domain in domains)


def load_blocked_sites() -> tuple[set[str], list[str]]:
    """Load blocked sites and URL patterns from sites.yaml.

    Returns:
        (blocked_site_names, blocked_url_patterns)
    """
    cfg = load_sites_config()
    blocked = cfg.get("blocked", {})
    sites = set(blocked.get("sites", []))
    patterns = blocked.get("url_patterns", [])
    return sites, patterns


def load_blocked_sso() -> list[str]:
    """Load blocked SSO domains from sites.yaml."""
    cfg = load_sites_config()
    return cfg.get("blocked_sso", [])


def load_base_urls() -> dict[str, str | None]:
    """Load site base URLs for URL resolution from sites.yaml."""
    cfg = load_sites_config()
    return cfg.get("base_urls", {})


# ---------------------------------------------------------------------------
# Default values — referenced across modules instead of magic numbers
# ---------------------------------------------------------------------------

DEFAULTS = {
    "min_score": 8,
    "max_apply_attempts": 3,
    "max_tailor_attempts": 5,
    "poll_interval": 60,
    "apply_timeout": 300,
    "viewport": "1280x900",
}


def pipeline_min_score() -> int:
    """Minimum fit score from ~/.applytex/config.yaml (pipeline.min_score)."""
    return int(load_app_config().get("pipeline", {}).get("min_score", 8))


def load_env():
    """Load environment variables from ~/.applytex/.env if it exists."""
    from dotenv import load_dotenv
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=True)
    # CWD .env is a fallback only — do not override ApplyTex config
    load_dotenv(override=False)


# ---------------------------------------------------------------------------
# Tier system — feature gating by installed dependencies
# ---------------------------------------------------------------------------

TIER_LABELS = {
    1: "Discovery",
    2: "AI Scoring & Tailoring",
    3: "Full Auto-Apply",
}

TIER_COMMANDS: dict[int, list[str]] = {
    1: ["init", "run discover", "run enrich", "status", "dashboard"],
    2: ["run score", "run latex", "run tailor", "review", "add", "registry"],
    3: ["apply"],
}


def get_tier() -> int:
    """Detect the current tier based on available dependencies.

    Tier 1 (Discovery):            Python + pip
    Tier 2 (AI Scoring & Tailoring): + LLM API key
    Tier 3 (Full Auto-Apply):       + Claude Code CLI + Chrome
    """
    load_env()

    has_llm = any(
        os.environ.get(k)
        for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "LLM_URL")
    )
    if not has_llm:
        return 1

    has_claude = shutil.which("claude") is not None
    try:
        get_chrome_path()
        has_chrome = True
    except FileNotFoundError:
        has_chrome = False

    if has_claude and has_chrome:
        return 3

    return 2


def check_tier(required: int, feature: str) -> None:
    """Raise SystemExit with a clear message if the current tier is too low.

    Args:
        required: Minimum tier needed (1, 2, or 3).
        feature: Human-readable description of the feature being gated.
    """
    current = get_tier()
    if current >= required:
        return

    from rich.console import Console
    _console = Console(stderr=True)

    missing: list[str] = []
    if required >= 2 and not any(
        os.environ.get(k)
        for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "LLM_URL")
    ):
        missing.append(
            "LLM API key — run [bold]applytex init[/bold] or set GEMINI_API_KEY / ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN"
        )
    if required >= 3:
        if not shutil.which("claude"):
            missing.append("Claude Code CLI — install from [bold]https://claude.ai/code[/bold]")
        try:
            get_chrome_path()
        except FileNotFoundError:
            missing.append("Chrome/Chromium — install or set CHROME_PATH")

    _console.print(
        f"\n[red]'{feature}' requires {TIER_LABELS.get(required, f'Tier {required}')} (Tier {required}).[/red]\n"
        f"Current tier: {TIER_LABELS.get(current, f'Tier {current}')} (Tier {current})."
    )
    if missing:
        _console.print("\n[yellow]Missing:[/yellow]")
        for m in missing:
            _console.print(f"  - {m}")
    _console.print()
    raise SystemExit(1)
