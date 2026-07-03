"""LLM-powered LaTeX patch constrained by KeywordPlan.

Token-efficient: the plan is compressed to a table, skip-terms are
omitted, and the LLM must verify every adjacent term was actually added.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compact plan representation — ~60 % smaller than full JSON
# ---------------------------------------------------------------------------

def _compact_plan(plan: dict) -> str:
    """Build a token-efficient summary of the keyword plan.

    Strips metadata the LLM doesn't need (job_url, company, adjustments
    array) and compresses the terms list to a fixed-width table with
    only the actionable fields.
    """
    lines: list[str] = []

    # Sacred blocks header — tells the LLM which sections are off-limits
    sacred = plan.get("sacred_blocks", [])
    if sacred:
        lines.append(f"Sacred sections (NO new skills here): {', '.join(sacred)}")

    # Term table — only include terms that need ACTION (skip gaps)
    header = f"{'Action':20s} {'JD Term':22s} {'Zone':16s} {'Anchor / Note'}"
    lines.append(header)
    lines.append("-" * 80)

    for t in plan.get("terms", []):
        action = t.get("action", "skip")
        if action == "skip":
            continue  # omit gaps/blocked — LLM must leave them alone
        jd = t["jd"]
        zone = t.get("zone", "")
        anchor = t.get("resume_anchor", "")
        note = t.get("note", "")
        extra = anchor or note or ""
        lines.append(f"  {action:18s} {jd:22s} {zone:16s} {extra}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Patch prompt — requires verified output
# ---------------------------------------------------------------------------

_PATCH_SYSTEM = """You are a LaTeX resume editor adding ATS keywords from a KeywordPlan.

RULES (violations cause rejection):
- SACRED BLOCKS (recent role): rephrase wording only — NO new tools/languages, NO swaps
- FLEX ZONE (older roles/projects):
  - append_adjacent: ADD the JD term alongside the existing anchor
    (e.g. "Java" -> "Java and Kotlin"). Keep the anchor keyword — do NOT remove it.
  - swap_label (if plan says swap): replace label only in flex zone
- NEVER add employers, dates, degrees, certifications, or new metrics
- NEVER add skills with action=skip (not in the term table)
- Do NOT change document structure, packages, or layout commands
- ESCAPE LaTeX special characters in text: # -> \\#, % -> \\%, & -> \\&, _ -> \\_

Return ONLY valid JSON (no markdown fences, no commentary):
{
  "tex": "<full updated latex document>",
  "adjustments": [
    {"jd_term": "Kotlin", "change": "Tech Cruzers: added Kotlin alongside Java", "zone": "flex", "flagged": true}
  ],
  "verified_adjacent_added": ["Kotlin", "Vue"],
  "verified_adjacent_skipped": []
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

    compact = _compact_plan(plan)

    user_content = (
        f"KEYWORD PLAN (compact):\n{compact}\n\n"
        f"PRESERVED COMPANIES: {companies}\n"
        f"PRESERVED SCHOOL: {school}\n"
        f"REAL METRICS (do not change): {metrics}\n\n"
        f"MASTER.TEX:\n{master_tex}\n"
    )

    client = get_client()
    raw = client.chat(
        [
            {"role": "system", "content": _PATCH_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        max_tokens=4096,   #<--- reduced from 8192 — typical output is ~5K chars of tex
        temperature=0.2,
    )

    data = _extract_json(raw)
    tex = data.get("tex", "").strip()
    if not tex:
        raise ValueError("LLM patch returned empty tex")

    adjustments = data.get("adjustments") or []

    # --- Verification: warn if adjacent terms were skipped ---
    skipped = data.get("verified_adjacent_skipped") or []
    if skipped:
        log.warning(
            "LLM skipped %d adjacent terms (not added): %s",
            len(skipped), ", ".join(skipped),
        )

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
