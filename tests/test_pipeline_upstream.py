from applytex.pipeline import _build_upstream


def test_cover_upstream_is_latex_when_latex_in_run():
    upstream = _build_upstream(["discover", "enrich", "score", "latex", "cover"])
    assert upstream["cover"] == "latex"


def test_cover_upstream_is_tailor_without_latex():
    upstream = _build_upstream(["discover", "enrich", "score", "tailor", "cover"])
    assert upstream["cover"] == "tailor"


def test_latex_upstream_is_score():
    upstream = _build_upstream(["discover", "enrich", "score", "latex"])
    assert upstream["latex"] == "score"
