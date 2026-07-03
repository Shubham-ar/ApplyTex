from applytex.latex.validator import validate_patch


def test_gap_term_rejected_when_added():
    original = r"\section{Experience} Python developer."
    patched = r"\section{Experience} Python and Rust developer."
    plan = {
        "terms": [{"jd": "Rust", "action": "skip", "status": "gap"}],
        "sacred_blocks": [],
    }
    result = validate_patch(original, patched, plan, {})
    assert result["passed"] is False
    assert any("Rust" in e for e in result["errors"])


def test_sacred_adjacent_swap_rejected():
    original = r"""
\subsection{Acme Corp}{2024--Present}
Built Java services.
"""
    patched = r"""
\subsection{Acme Corp}{2024--Present}
Built C# services.
"""
    plan = {
        "terms": [
            {
                "jd": "C#",
                "action": "swap_label",
                "status": "adjacent",
            }
        ],
        "sacred_blocks": ["Acme Corp"],
    }
    result = validate_patch(original, patched, plan, {})
    assert result["passed"] is False
    assert any("sacred" in e.lower() for e in result["errors"])


def test_append_adjacent_requires_anchor_preserved():
    original = r"""
\subsection{Old Co}{2018--2020}
Built Java microservices for clients.
"""
    patched = r"""
\subsection{Old Co}{2018--2020}
Built Kotlin microservices for clients.
"""
    plan = {
        "terms": [
            {
                "jd": "Kotlin",
                "action": "append_adjacent",
                "resume_anchor": "Java",
                "status": "adjacent",
            }
        ],
        "sacred_blocks": ["Intact"],
    }
    result = validate_patch(original, patched, plan, {})
    assert result["passed"] is False
    assert any("anchor" in e.lower() or "removed" in e.lower() for e in result["errors"])


def test_append_adjacent_ok_when_both_present():
    original = r"""
\subsection{Old Co}{2018--2020}
Built Java microservices.
"""
    patched = r"""
\subsection{Old Co}{2018--2020}
Built Java and Kotlin microservices.
"""
    plan = {
        "terms": [{"jd": "Kotlin", "action": "append_adjacent", "resume_anchor": "Java"}],
        "sacred_blocks": ["Intact Corp"],
    }
    result = validate_patch(original, patched, plan, {})
    assert result["passed"] is True


def test_valid_rephrase_passes():
    tex = r"\section{Experience} Led Agile ceremonies for the team."
    plan = {
        "terms": [{"jd": "Scrum", "action": "rephrase", "status": "adjacent"}],
        "sacred_blocks": [],
    }
    result = validate_patch(tex, tex, plan, {})
    assert result["passed"] is True
