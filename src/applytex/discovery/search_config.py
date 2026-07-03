"""Normalize searches.yaml and shared discovery config helpers."""

from __future__ import annotations

import copy
import re

# JobSpy country_indeed values (case-insensitive). Keys are normalized lookup tokens.
_COUNTRY_ALIASES: dict[str, str] = {
    "usa": "usa",
    "us": "usa",
    "u.s.": "usa",
    "u.s.a.": "usa",
    "united states": "usa",
    "united states of america": "usa",
    "can": "canada",
    "canada": "canada",
    "uk": "uk",
    "u.k.": "uk",
    "united kingdom": "uk",
    "gb": "uk",
    "great britain": "uk",
    "australia": "australia",
    "aus": "australia",
    "india": "india",
    "ind": "india",
    "germany": "germany",
    "de": "germany",
    "france": "france",
    "fr": "france",
}

DEFAULT_SITES = ["indeed", "linkedin"]

DEFAULT_EXCLUDE_TITLES = [
    "senior director",
    "VP ",
    "vice president",
    "chief",
    "intern",
    "internship",
    "co-op",
    "clearance required",
    "TS/SCI",
    "principal scientist",
]




def resolve_max_query_tier(search_cfg: dict, *, default: int = 2) -> int | None:
    """Max query tier for discovery scrapers (jobspy, workday, smartextract)."""
    if "jobspy_max_tier" in search_cfg:
        return search_cfg.get("jobspy_max_tier")
    if "workday_max_tier" in search_cfg:
        return search_cfg.get("workday_max_tier")
    return default


def filter_queries_by_tier(queries: list[dict], max_tier: int | None) -> list[dict]:
    """Keep queries with tier <= max_tier (missing tier = 99)."""
    if max_tier is None:
        return list(queries)
    return [q for q in queries if q.get("tier", 99) <= max_tier]


def normalize_country_indeed(value: str | None) -> str:
    """Map profile/YAML country strings to JobSpy country_indeed."""
    if not value or not str(value).strip():
        return "usa"
    key = re.sub(r"\s+", " ", str(value).strip().lower())
    return _COUNTRY_ALIASES.get(key, key)


def resolve_sites(cfg: dict) -> list[str]:
    """Job boards for JobSpy: prefer ``sites``, fall back to legacy ``boards``."""
    raw = cfg.get("sites") or cfg.get("boards")
    if not raw:
        return list(DEFAULT_SITES)
    if isinstance(raw, str):
        return [raw]
    return [str(s).strip() for s in raw if str(s).strip()]


def resolve_country_indeed(cfg: dict) -> str:
    """Indeed/Glassdoor country from defaults or legacy top-level ``country``."""
    defaults = cfg.get("defaults") or {}
    raw = defaults.get("country_indeed") or cfg.get("country")
    return normalize_country_indeed(raw)


def normalize_search_config(cfg: dict | None) -> dict:
    """Return a copy with legacy keys merged into fields discovery code reads."""
    if not cfg:
        return {}

    out = copy.deepcopy(cfg)
    defaults = dict(out.get("defaults") or {})
    defaults["country_indeed"] = resolve_country_indeed(out)
    out["defaults"] = defaults
    out["sites"] = resolve_sites(out)
    if "exclude_titles" not in out or out["exclude_titles"] is None:
        out["exclude_titles"] = []
    return out


def resolve_scrape_locations(search_cfg: dict) -> list[str]:
    """Location strings for career-site URL templates (local entries first)."""
    locs = search_cfg.get("locations") or []
    parsed: list[tuple[str, bool]] = []
    for loc in locs:
        if isinstance(loc, str):
            parsed.append((loc, False))
        elif isinstance(loc, dict) and loc.get("location"):
            parsed.append((str(loc["location"]), bool(loc.get("remote"))))

    if not parsed:
        return [""]

    local = [s for s, remote in parsed if not remote]
    remote = [s for s, is_remote in parsed if is_remote]
    ordered = local + remote

    seen: set[str] = set()
    unique: list[str] = []
    for item in ordered:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def title_excluded(title: str | None, exclude_titles: list[str]) -> bool:
    """True if job title contains any exclude pattern (case-insensitive)."""
    if not title or not exclude_titles:
        return False
    lower = title.lower()
    return any(pat.lower() in lower for pat in exclude_titles if pat)


def suggested_location_patterns(
    search_location: str,
    country_indeed: str,
    *,
    city: str = "",
    province_state: str = "",
) -> tuple[list[str], list[str]]:
    """Build default accept/reject patterns for init wizard output."""
    accept: list[str] = ["Remote", "Hybrid", "Anywhere"]
    reject = ["India", "Philippines", "US only", "United States only"]

    country = normalize_country_indeed(country_indeed)
    if country == "canada":
        accept.extend(["Canada", "Ontario", "British Columbia", "Quebec", "GTA"])
        reject.extend(["UK only", "Europe only"])
    elif country == "usa":
        accept.extend(["United States", "US", "USA", "California", "CA"])
    elif country == "uk":
        accept.extend(["United Kingdom", "UK", "England", "London"])
    elif country == "australia":
        accept.extend(["Australia", "AU", "Sydney", "Melbourne"])
    else:
        accept.append(country.title())

    loc = (search_location or "").strip()
    if loc and loc.lower() not in ("remote", "anywhere"):
        accept.append(loc)
        if "," in loc:
            accept.append(loc.split(",")[0].strip())
        if city:
            accept.append(city)
        if province_state:
            accept.append(province_state)

    # De-dupe while preserving order
    seen: set[str] = set()
    unique_accept: list[str] = []
    for pat in accept:
        key = pat.lower()
        if key not in seen:
            seen.add(key)
            unique_accept.append(pat)
    return unique_accept, reject


def build_wizard_search_config(
    *,
    search_location: str,
    distance: int,
    roles: list[str],
    country_indeed: str,
    city: str = "",
    province_state: str = "",
    include_country_remote: bool = True,
) -> dict:
    """Structured searches.yaml content for ``applytex init``."""
    remote_only = distance == 0
    country_label = country_indeed.title() if country_indeed else "Canada"
    accept, reject = suggested_location_patterns(
        search_location, country_indeed, city=city, province_state=province_state,
    )

    locations: list[dict] = [
        {"location": search_location, "remote": remote_only},
    ]
    if include_country_remote and not remote_only:
        locations.append({"location": country_label, "remote": True})

    queries = [{"query": role, "tier": 1} for role in roles]

    return {
        "defaults": {
            "country_indeed": country_indeed,
            "distance": distance,
            "hours_old": 72,
            "results_per_site": 50,
        },
        "locations": locations,
        "location": {
            "accept_patterns": accept,
            "reject_patterns": reject,
        },
        "sites": list(DEFAULT_SITES),
        "queries": queries,
        "exclude_titles": list(DEFAULT_EXCLUDE_TITLES),
    }
