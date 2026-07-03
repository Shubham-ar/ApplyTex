"""Build KeywordPlan JSON before LaTeX patch."""

from __future__ import annotations

from typing import Any

from applytex.latex.placement import zone_for_term


def build_keyword_plan(
    job: dict,
    classifications: list[dict[str, Any]],
    zones: dict,
    adjacency_cfg: dict,
) -> dict[str, Any]:
    """Build a constrained keyword plan for one job."""
    placement = adjacency_cfg.get("placement", {})
    policy = adjacency_cfg.get("keyword_policy", {})
    max_adj = int(policy.get("max_adjacent_adjustments_per_job", policy.get("max_adjacent_swaps_per_job", 5)))
    adjacent_mode = policy.get("adjacent_mode", "append")  # append | swap
    allow_adjacent = bool(placement.get("allow_adjacent_swap_in_flex_only", True))

    terms: list[dict[str, Any]] = []
    adjacent_count = 0

    for item in classifications:
        term = dict(item)
        zone = zone_for_term(term, zones)
        term["zone"] = zone

        if term.get("status") == "adjacent":
            if adjacent_mode == "swap":
                term["action"] = "swap_label"
            elif term.get("action") == "swap_label":
                term["action"] = "append_adjacent"

        if term.get("status") == "adjacent" and term.get("action") in ("swap_label", "append_adjacent"):
            if not allow_adjacent or zone != "flex":
                term["action"] = "rephrase"
                term["zone"] = "summary_light"
            elif adjacent_count >= max_adj:
                term["action"] = "skip"
                term["note"] = "max_adjacent_adjustments reached"
            else:
                adjacent_count += 1
                flex_labels = zones.get("flex_blocks", [])
                term["target"] = flex_labels[0] if flex_labels else "older experience"

        if term.get("status") == "exact":
            term["action"] = "emphasize"
            term["zone"] = "summary_light"

        if term.get("status") in ("gap", "blocked"):
            term["action"] = "skip"

        terms.append(term)

    return {
        "job_url": job.get("url"),
        "job_title": job.get("title"),
        "company": job.get("site"),
        "terms": terms,
        "sacred_blocks": zones.get("sacred_blocks", []),
        "adjustments": [],
    }
