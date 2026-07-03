from datetime import datetime, timezone

import pytest

from applytex import config as cfg
from applytex import database
from applytex.database import init_db
from applytex.jobs.add import _site_from_url, _upsert_job, add_job_from_url


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    db_path = tmp_path / "applytex.db"
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "get_db_path", lambda: db_path)
    resume = tmp_path / "resume.txt"
    resume.write_text("Python backend engineer", encoding="utf-8")
    monkeypatch.setattr(cfg, "RESUME_PATH", resume)
    import applytex.jobs.add as add_mod
    monkeypatch.setattr(add_mod, "RESUME_PATH", resume)
    return init_db(db_path)


def test_add_job_no_resume(tmp_path, monkeypatch):
    db_path = tmp_path / "applytex.db"
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "get_db_path", lambda: db_path)
    missing_resume = tmp_path / "missing_resume.txt"
    monkeypatch.setattr(cfg, "RESUME_PATH", missing_resume)
    import applytex.jobs.add as add_mod
    monkeypatch.setattr(add_mod, "RESUME_PATH", missing_resume)
    init_db(db_path)

    result = add_job_from_url("https://example.com/job", min_score=8)
    assert result["status"] == "no_resume"
    assert result.get("hint")


def test_site_from_url():
    assert _site_from_url("https://boards.greenhouse.io/acme/jobs/1") == "Greenhouse"
    assert _site_from_url("https://jobs.lever.co/acme/abc") == "Lever"


def test_upsert_job_idempotent(test_db):
    url = "https://example.com/job"
    _upsert_job(test_db, url, "Acme", "Title")
    _upsert_job(test_db, url, "Acme", "Title")
    count = test_db.execute("SELECT COUNT(*) FROM jobs WHERE url = ?", (url,)).fetchone()[0]
    assert count == 1


def test_add_job_below_threshold(test_db, monkeypatch):
    monkeypatch.setattr(
        "applytex.jobs.add.enrich_single_url",
        lambda url: {"status": "ok", "title": "Engineer"},
    )
    monkeypatch.setattr(
        "applytex.jobs.add.score_job",
        lambda resume, job: {"score": 6, "keywords": "python", "reasoning": "ok"},
    )

    result = add_job_from_url("https://boards.greenhouse.io/acme/jobs/1", min_score=8)
    assert result["status"] == "below_threshold"
    assert result["latex"] == "skipped"
    assert result["score"] == 6


def test_add_job_runs_latex_when_enabled(test_db, tmp_path, monkeypatch):
    master = tmp_path / "master.tex"
    master.write_text(r"\section{Experience}", encoding="utf-8")
    monkeypatch.setattr(cfg, "MASTER_TEX_PATH", master)
    monkeypatch.setattr(
        "applytex.config.is_latex_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "applytex.jobs.add.load_app_config",
        lambda: {"pipeline": {"min_score": 8}},
    )
    monkeypatch.setattr(
        "applytex.jobs.add.enrich_single_url",
        lambda url: {"status": "ok", "title": "Engineer"},
    )
    monkeypatch.setattr(
        "applytex.jobs.add.score_job",
        lambda resume, job: {"score": 9, "keywords": "python", "reasoning": "strong"},
    )
    monkeypatch.setattr(
        "applytex.config.load_profile",
        lambda: {"skills_boundary": {}},
    )
    monkeypatch.setattr(
        "applytex.latex.tailor.tailor_job",
        lambda master_tex, resume_text, job, profile: {
            "status": "ok",
            "tex_path": str(tmp_path / "job.tex"),
            "report_path": str(tmp_path / "job_KEYWORD_REPORT.json"),
            "match_before": 0.5,
            "match_after": 0.8,
            "review_status": "pending",
            "compile_error": None,
            "tailored_resume_path": None,
        },
    )

    result = add_job_from_url("https://boards.greenhouse.io/acme/jobs/2", min_score=8)
    assert result["status"] == "pending_review"
    assert result["review_status"] == "pending"
    assert result["match_after"] == 0.8

    row = test_db.execute(
        "SELECT review_status, fit_score FROM jobs WHERE url LIKE ?",
        ("%/jobs/2",),
    ).fetchone()
    assert row["review_status"] == "pending"
    assert row["fit_score"] == 9


def test_add_job_compile_error_not_pending_review(test_db, tmp_path, monkeypatch):
    master = tmp_path / "master.tex"
    master.write_text(r"\section{Experience}", encoding="utf-8")
    monkeypatch.setattr(cfg, "MASTER_TEX_PATH", master)
    monkeypatch.setattr("applytex.config.is_latex_enabled", lambda: True)
    monkeypatch.setattr(
        "applytex.jobs.add.load_app_config",
        lambda: {"pipeline": {"min_score": 8}},
    )
    monkeypatch.setattr(
        "applytex.jobs.add.enrich_single_url",
        lambda url: {"status": "ok", "title": "Engineer"},
    )
    monkeypatch.setattr(
        "applytex.jobs.add.score_job",
        lambda resume, job: {"score": 9, "keywords": "python", "reasoning": "strong"},
    )
    monkeypatch.setattr(
        "applytex.config.load_profile",
        lambda: {"skills_boundary": {}},
    )
    monkeypatch.setattr(
        "applytex.latex.tailor.tailor_job",
        lambda master_tex, resume_text, job, profile: {
            "status": "compile_error",
            "tex_path": str(tmp_path / "job.tex"),
            "report_path": str(tmp_path / "job_KEYWORD_REPORT.json"),
            "match_before": 0.5,
            "match_after": 0.8,
            "review_status": None,
            "compile_error": "tectonic not found",
            "tailored_resume_path": None,
        },
    )

    result = add_job_from_url("https://boards.greenhouse.io/acme/jobs/3", min_score=8)
    assert result["status"] == "latex_failed"
    assert result["latex"] == "compile_error"
    assert result.get("latex_error") == "tectonic not found"
    assert result.get("review_status") is None

    row = test_db.execute(
        "SELECT review_status, latex_compile_error FROM jobs WHERE url LIKE ?",
        ("%/jobs/3",),
    ).fetchone()
    assert row["review_status"] is None
    assert row["latex_compile_error"] == "tectonic not found"

