from applytex.latex.keywords import classify_term, compute_match_score, term_in_text
from applytex.latex.placement import detect_zones
from applytex.latex.tailor_plan import build_keyword_plan


def test_classify_exact():
    profile = {"skills_boundary": {"programming_languages": ["Python"]}}
    clusters = {"jvm_languages": ["java", "c#"]}
    result = classify_term("Python", "Built APIs with Python", profile, clusters)
    assert result["status"] == "exact"


def test_classify_adjacent_java_csharp():
    profile = {"skills_boundary": {"programming_languages": ["Java"]}}
    clusters = {"jvm_languages": ["java", "c#", "kotlin"]}
    result = classify_term("C#", "Senior role using Java and Spring", profile, clusters)
    assert result["status"] == "adjacent"
    assert result["resume_anchor"].lower() == "java"
    assert result["action"] == "append_adjacent"


def test_classify_gap():
    profile = {"skills_boundary": {"programming_languages": ["Python"]}}
    clusters = {"jvm_languages": ["java", "c#"]}
    result = classify_term("Rust", "Python developer", profile, clusters)
    assert result["status"] == "gap"


def test_compute_match_score():
    classes = [
        {"status": "exact"},
        {"status": "adjacent"},
        {"status": "gap"},
    ]
    assert compute_match_score(classes) == round(2 / 3, 3)


def test_build_keyword_plan_limits_swaps():
    job = {"url": "https://example.com/job", "title": "Engineer", "site": "Acme"}
    zones = {
        "sacred_blocks": ["Acme Corp 2024"],
        "flex_blocks": ["Side Project 2019"],
    }
    adjacency = {
        "placement": {"allow_adjacent_swap_in_flex_only": True, "sacred_roles": 1},
        "keyword_policy": {"max_adjacent_adjustments_per_job": 1, "adjacent_mode": "append"},
    }
    classes = [
        {"jd": "C#", "status": "adjacent", "resume_anchor": "Java", "action": "append_adjacent", "reason": "jvm_languages"},
        {"jd": "Kotlin", "status": "adjacent", "resume_anchor": "Java", "action": "append_adjacent", "reason": "jvm_languages"},
        {"jd": "Rust", "status": "gap", "action": "skip"},
    ]
    plan = build_keyword_plan(job, classes, zones, adjacency)
    appends = [t for t in plan["terms"] if t.get("action") == "append_adjacent"]
    assert len(appends) == 1
    skipped = [t for t in plan["terms"] if t["jd"] == "Kotlin" and t.get("action") == "skip"]
    assert skipped


def test_detect_zones_finds_sacred_block():
    tex = r"""
\section{Experience}
\subsection{Acme Corp}{2024--Present}
Built Java services.
\subsection{Old Co}{2018--2020}
Python scripts.
\section{Projects}
Cool side project.
"""
    zones = detect_zones(tex, {"sacred_roles": 1})
    assert len(zones["sacred_blocks"]) >= 1
