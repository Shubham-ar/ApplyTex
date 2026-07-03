"""Validate LaTeX patches against KeywordPlan and resume_facts."""

from __future__ import annotations

import re
from typing import Any


def validate_patch(
    original_tex: str,
    patched_tex: str,
    plan: dict[str, Any],
    profile: dict,
    sacred_texts: list[str] | None = None,
) -> dict[str, Any]:
    """Programmatic validation of a patched resume.

    Args:
        original_tex: Original resume LaTeX source.
        patched_tex: LLM-patched LaTeX source.
        plan: KeywordPlan dict.
        profile: User profile dict.
        sacred_texts: Raw LaTeX content of sacred blocks. When provided,
            adjacent-adjustment checks look within this content rather than
            the full document, avoiding false positives from summary additions.

    Returns:
        {"passed": bool, "errors": list[str], "warnings": list[str]}
    """
    errors: list[str] = []
    warnings: list[str] = []
    patched_lower = patched_tex.lower()
    original_lower = original_tex.lower()

    resume_facts = profile.get("resume_facts", {})

    for company in resume_facts.get("preserved_companies", []):
        if company.lower() not in patched_lower:
            errors.append(f"Company '{company}' missing from patched tex")

    schools = resume_facts.get("preserved_school", "")
    if isinstance(schools, str):
        schools = [schools] if schools else []
    for school in schools:
        if school.lower() not in patched_lower:
            errors.append(f"Education '{school}' missing")

    for metric in resume_facts.get("real_metrics", []):
        if metric and metric.lower() not in patched_lower:
            warnings.append(f"Metric '{metric}' not found verbatim — verify not inflated")

    # Gap/blocked terms must not be newly introduced
    for term in plan.get("terms", []):
        if term.get("action") != "skip":
            continue
        jd = term.get("jd", "")
        if not jd:
            continue
        norm = jd.lower()
        if norm not in original_lower and re.search(rf"\b{re.escape(norm)}\b", patched_lower):
            errors.append(f"Gap/blocked term '{jd}' was added to resume")

    # Adjacent adjustments in sacred blocks
    sacred = plan.get("sacred_blocks", [])
    sacred_combined = " ".join(sacred_texts).lower() if sacred_texts else ""

    for term in plan.get("terms", []):
        action = term.get("action")
        if action not in ("swap_label", "append_adjacent"):
            continue
        jd = term.get("jd", "")
        anchor = (term.get("resume_anchor") or "").lower()
        if not jd:
            continue
        jd_lower = jd.lower()

        if action == "append_adjacent" and anchor:
            if anchor not in patched_lower:
                errors.append(f"Append '{jd}': resume anchor '{term.get('resume_anchor')}' was removed")

        # Check if the new term was added WITHIN sacred block content.
        # Without sacred_texts we fall back to full-document check (broader).
        if sacred_texts:
            search_range = sacred_combined
        else:
            search_range = patched_lower

        for block_label in sacred:
            if block_label.lower() in patched_lower and jd_lower in search_range:
                if jd_lower not in original_lower:
                    verb = "swap" if action == "swap_label" else "append"
                    errors.append(
                        f"Adjacent {verb} '{jd}' may have touched sacred block '{block_label}'"
                    )
            if action == "swap_label" and block_label.lower() in patched_lower:
                if jd_lower in patched_lower and jd_lower not in original_lower:
                    errors.append(
                        f"Adjacent swap '{jd}' may have touched sacred block '{block_label}'"
                    )

    if len(patched_tex) < len(original_tex) * 0.5:
        errors.append("Patched tex suspiciously shorter than original")

    return {"passed": len(errors) == 0, "errors": errors, "warnings": warnings}
