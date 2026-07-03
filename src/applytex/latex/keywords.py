"""JD keyword extraction and classification (exact / adjacent / gap / blocked)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

_EXTRACT_PROMPT = """You extract ATS keywords from job descriptions.

Return ONLY a JSON array of 15-25 strings — languages, frameworks, tools, cloud, methodologies.
No markdown, no commentary.

Example: ["Python", "AWS", "Kubernetes", "Agile", "PostgreSQL"]
"""


def normalize_term(term: str) -> str:
    return re.sub(r"\s+", " ", term.lower().strip())


def _skills_set(profile: dict) -> set[str]:
    boundary = profile.get("skills_boundary", {})
    allowed: set[str] = set()
    for items in boundary.values():
        if isinstance(items, list):
            allowed.update(normalize_term(s) for s in items)
    return allowed


def _cluster_index(clusters: dict[str, list]) -> dict[str, str]:
    """Map normalized term -> cluster name."""
    index: dict[str, str] = {}
    for name, terms in clusters.items():
        for term in terms:
            index[normalize_term(str(term))] = name
    return index


def term_in_text(term: str, text: str) -> bool:
    norm = normalize_term(term)
    if not norm:
        return False
    if len(norm) <= 3:
        return bool(re.search(rf"\b{re.escape(norm)}\b", text, flags=re.IGNORECASE))
    return norm in normalize_term(text)


def extract_from_jd(job_description: str, client: Any | None = None) -> list[str]:
    """Extract 15–25 keyword phrases from a job description."""
    jd = (job_description or "")[:4000]  # Most tech keywords in first half; rest is boilerplate
    if client is not None:
        try:
            raw = client.chat(
                [
                    {"role": "system", "content": _EXTRACT_PROMPT},
                    {"role": "user", "content": jd},
                ],
                max_tokens=512,
                temperature=0.1,
            )
            terms = json.loads(_parse_json_array(raw))
            if terms:
                return [str(t).strip() for t in terms if str(t).strip()][:25]
        except Exception:
            log.debug("LLM keyword extract failed, using heuristic fallback", exc_info=True)
    return _heuristic_extract(jd)


def _parse_json_array(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("["):
        return raw
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end > start:
        return raw[start : end + 1]
    raise ValueError("No JSON array in response")


def _heuristic_extract(jd: str) -> list[str]:
    """Fallback keyword list from common tech tokens in the JD."""
    tokens = re.findall(
        r"\b(?:Python|Java(?:Script)?|TypeScript|Go|Rust|C\+\+|C#|Ruby|PHP|Swift|Kotlin|"
        r"React|Vue|Angular|Node\.?js|Django|Flask|FastAPI|Spring|\.NET|"
        r"AWS|Azure|GCP|Docker|Kubernetes|K8s|Terraform|PostgreSQL|MySQL|MongoDB|Redis|"
        r"Kafka|Spark|Airflow|Jenkins|GitHub Actions|GitLab|CI/CD|Agile|Scrum|Kanban|"
        r"Linux|Bash|SQL|NoSQL|GraphQL|REST|gRPC|Microservices|Tailwind|CSS|HTML)\b",
        jd,
        flags=re.IGNORECASE,
    )
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        key = normalize_term(t)
        if key not in seen:
            seen.add(key)
            out.append(t)
        if len(out) >= 25:
            break
    return out


def find_resume_anchor(term: str, resume_text: str, cluster_name: str, clusters: dict) -> str | None:
    """Find a resume term in the same cluster as the JD term."""
    members = clusters.get(cluster_name, [])
    for member in members:
        m = str(member)
        if normalize_term(m) == normalize_term(term):
            continue
        if term_in_text(m, resume_text):
            return m
    return None


def classify_term(
    term: str,
    resume_text: str,
    profile: dict,
    clusters: dict[str, list],
) -> dict[str, Any]:
    """Classify one JD term against resume + profile."""
    allowed = _skills_set(profile)
    index = _cluster_index(clusters)
    norm = normalize_term(term)

    if term_in_text(term, resume_text):
        return {"jd": term, "status": "exact", "resume_anchor": term, "action": "emphasize"}

    cluster = index.get(norm)
    if cluster:
        anchor = find_resume_anchor(term, resume_text, cluster, clusters)
        if anchor:
            return {
                "jd": term,
                "status": "adjacent",
                "resume_anchor": anchor,
                "action": "append_adjacent",
                "reason": cluster,
            }

    if allowed and norm not in allowed:
        # Not in skills boundary and no adjacent anchor — do not invent
        if not any(term_in_text(a, resume_text) for a in allowed if index.get(normalize_term(a)) == cluster):
            return {"jd": term, "status": "blocked", "action": "skip"}

    return {"jd": term, "status": "gap", "action": "skip"}


def classify_terms(
    terms: list[str],
    resume_text: str,
    profile: dict,
    clusters: dict[str, list],
) -> list[dict[str, Any]]:
    return [classify_term(t, resume_text, profile, clusters) for t in terms]


def compute_match_score(classifications: list[dict], *, strict: bool = False) -> float:
    """Fraction of JD terms matched (not gap/blocked).

    Args:
        classifications: List of classification dicts from classify_terms.
        strict: If True, count only exact (literal) matches — reflects actual
                resume coverage. If False (default), count exact + adjacent
                (cluster-enriched coverage), which is useful for high-level
                dashboard display but hides patch improvements.

    For before/after comparison use strict=True — this shows the real delta
    when the LLM patch adds adjacent terms to the resume text.
    """
    if not classifications:
        return 0.0
    if strict:
        hits = sum(1 for c in classifications if c.get("status") == "exact")
    else:
        hits = sum(1 for c in classifications if c.get("status") in ("exact", "adjacent"))
    return round(hits / len(classifications), 3)
