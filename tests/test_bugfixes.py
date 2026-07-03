import pytest

from applytex import config as cfg
from applytex import database
from applytex.database import init_db
from applytex.discovery.location_filter import load_location_patterns, location_ok
from applytex.jobs.urls import normalize_job_url, resolve_job_url


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    db_path = tmp_path / "applytex.db"
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "get_db_path", lambda: db_path)
    return init_db(db_path)


def test_normalize_job_url_strips_query():
    assert normalize_job_url("https://example.com/jobs/1?utm_source=linkedin") == "https://example.com/jobs/1"
    assert normalize_job_url("https://example.com/jobs/1/") == "https://example.com/jobs/1"


def test_load_location_patterns_nested():
    cfg = {
        "location": {
            "accept_patterns": ["San Francisco", "Remote"],
            "reject_patterns": ["India"],
        }
    }
    accept, reject = load_location_patterns(cfg)
    assert "San Francisco" in accept
    assert "India" in reject


def test_load_location_patterns_legacy_keys():
    cfg = {
        "location_accept": ["Austin"],
        "location_reject_non_remote": ["UK only"],
    }
    accept, reject = load_location_patterns(cfg)
    assert accept == ["Austin"]
    assert reject == ["UK only"]


def test_location_ok_accepts_remote():
    assert location_ok("Remote - US", ["California"], ["India"]) is True


def test_location_ok_rejects_non_matching():
    assert location_ok("London, UK", ["San Francisco"], ["India"]) is False


def test_resolve_job_url_with_query_params(test_db):
    url = "https://boards.greenhouse.io/acme/jobs/42"
    test_db.execute(
        "INSERT INTO jobs (url, title, site) VALUES (?, ?, ?)",
        (url, "Engineer", "Acme"),
    )
    test_db.commit()

    resolved = resolve_job_url(test_db, f"{url}?utm_campaign=test")
    assert resolved == url


def test_approve_job_with_query_param_url(test_db, tmp_path, monkeypatch):
    from applytex import config as cfg
    from applytex.latex.review import approve_job

    tailored = tmp_path / "tailored"
    tailored.mkdir()
    monkeypatch.setattr(cfg, "TAILORED_DIR", tailored)
    import applytex.latex.review as review_mod
    monkeypatch.setattr(review_mod, "TAILORED_DIR", tailored)

    canonical = "https://boards.greenhouse.io/acme/jobs/42"
    prefix = "Acme_Engineer"
    tex = tailored / f"{prefix}.tex"
    tex.write_text(r"\documentclass{article}", encoding="utf-8")
    (tailored / f"{prefix}.txt").write_text("resume", encoding="utf-8")
    (tailored / f"{prefix}.pdf").write_bytes(b"%PDF-1.4")

    test_db.execute(
        """
        INSERT INTO jobs (url, title, site, review_status, tailored_latex_path, keyword_report_path)
        VALUES (?, ?, ?, 'pending', ?, ?)
        """,
        (canonical, "Engineer", "Acme", str(tex), str(tailored / f"{prefix}_KEYWORD_REPORT.json")),
    )
    test_db.commit()

    assert approve_job(f"{canonical}?ref=linkedin") is True
    row = test_db.execute(
        "SELECT review_status, tailored_resume_path FROM jobs WHERE url = ?",
        (canonical,),
    ).fetchone()
    assert row["review_status"] == "approved"
    assert row["tailored_resume_path"].endswith(".txt")
