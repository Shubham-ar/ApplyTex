"""LLM-powered LaTeX patch constrained by KeywordPlan."""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

_PATCH_PROMPT = """You are a LaTeX resume editor for ATS keyword alignment.

You receive:
1. The user's master.tex resume
2. A KeywordPlan listing allowed changes per JD term

RULES (violations cause rejection):
- SACRED BLOCKS (recent role): rephrase wording only — NO new tools/languages, NO swaps
- FLEX ZONE (older roles/projects):
  - append_adjacent: ADD the JD term alongside the existing anchor (e.g. "Java" -> "Java and Kotlin")
    Keep the anchor keyword — do NOT remove or replace it
  - swap_label (if plan says swap): replace label only in flex zone
- NEVER add employers, dates, degrees, certifications, or new metrics
- NEVER add skills marked action=skip (gap/blocked terms)
- Do NOT change document structure, packages, or layout commands
- Every material keyword change must appear in adjustments[] with flagged=true
- ESCAPE LaTeX special characters in text: # -> \\#, % -> \\%, & -> \\&, _ -> \\_

Return ONLY valid JSON (no markdown fences):
{
  "tex": "<full updated latex document>",
  "adjustments": [
    {"jd_term": "Kotlin", "change": "Tech Cruzers: added Kotlin alongside Java", "zone": "flex",
     "note": "Adjacent JVM language; older role — discuss transferability in interview", "flagged": true}
  ]
}
"""


def apply_patch(
    master_tex: str,
    plan: dict[str, Any],
    profile: dict,
) -> tuple[str, list[dict]]:
    """Apply keyword plan to master.tex via LLM.

    Returns:
        (patched_tex, adjustments)
    """
    from applytex.llm import get_client

    resume_facts = profile.get("resume_facts", {})
    companies = ", ".join(resume_facts.get("preserved_companies", []))
    school_raw = resume_facts.get("preserved_school", "")
    if isinstance(school_raw, list):
        school = ", ".join(school_raw)
    else:
        school = school_raw
    metrics = ", ".join(resume_facts.get("real_metrics", []))

    user_content = (
        f"KEYWORD PLAN:\n{json.dumps(plan, indent=2)}\n\n"
        f"PRESERVED COMPANIES: {companies}\n"
        f"PRESERVED SCHOOL: {school}\n"
        f"REAL METRICS (do not change): {metrics}\n\n"
        f"MASTER.TEX:\n{master_tex}\n"
    )

    client = get_client()
    raw = client.chat(
        [
            {"role": "system", "content": _PATCH_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=8192,
        temperature=0.2,
    )

    data = _extract_json(raw)
    tex = data.get("tex", "").strip()
    if not tex:
        raise ValueError("LLM patch returned empty tex")
    adjustments = data.get("adjustments") or []
    return tex, adjustments


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    if "```" in raw:
        for part in raw.split("```")[1::2]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except json.JSONDecodeError:
                continue
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        return json.loads(raw[start : end + 1])
    raise ValueError("No valid JSON in LLM patch response")
