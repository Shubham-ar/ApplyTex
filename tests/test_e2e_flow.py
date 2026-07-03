"""End-to-end flow: add → pending → approve → acquire_job (mocked enrich/tailor)."""

import json
from datetime import datetime, timezone

import pytest

from applytex import config as cfg
from applytex import database
from applytex.apply.launcher import acquire_job
from applytex.database import get_stats, init_db
from applytex.jobs.add import add_job_from_url
from applytex.latex.review import approve_job
from applytex.latex.utils import job_file_prefix


@pytest.fixture
def pipeline_env(tmp_path, monkeypatch):
    app_dir = tmp_path / "applytex_home"
    app_dir.mkdir()
    db_path = app_dir / "applytex.db"
    tailored = app_dir / "tailored_resumes"
    tailored.mkdir()
    resume = app_dir / "resume.txt"
    resume.write_text("Python backend engineer with Java experience", encoding="utf-8")
    master = app_dir / "latex" / "master.tex"
    master.parent.mkdir(parents=True)
    master.write_text(
        r"""
\section{Experience}
\subsection{Acme Corp}{2024--Present}
Built Java microservices.
\subsection{Side Project}{2019--2020}
Python scripts.
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(cfg, "APP_DIR", app_dir)
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "get_db_path", lambda: db_path)
    monkeypatch.setattr(cfg, "RESUME_PATH", resume)
    monkeypatch.setattr(cfg, "MASTER_TEX_PATH", master)
    monkeypatch.setattr(cfg, "TAILORED_DIR", tailored)

    import applytex.jobs.add as add_mod
    import applytex.latex.review as review_mod

    monkeypatch.setattr(add_mod, "RESUME_PATH", resume)
    monkeypatch.setattr(review_mod, "TAILORED_DIR", tailored)

    init_db(db_path)
    return {
        "url": "https://boards.greenhouse.io/acme/jobs/99",
        "tailored": tailored,
        "master": master,
        "resume": resume,
    }


def _mock_enrich(url: str, title: str = "Backend Engineer"):
    """Mock enrich that also writes DB fields required for ready_to_apply."""
    from applytex.database import get_connection

    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE jobs SET full_description = ?, application_url = ?,
                        detail_scraped_at = ?, title = COALESCE(?, title)
        WHERE url = ?
        """,
        (f"JD text for {title}", url, now, title, url),
    )
    conn.commit()
    return {
        "status": "ok",
        "title": title,
        "full_description": f"JD text for {title}",
        "application_url": url,
    }


def _mock_tailor(master_tex, resume_text, job, profile, tailored_dir):
    prefix = job_file_prefix(job)
    tex_path = tailored_dir / f"{prefix}.tex"
    txt_path = tailored_dir / f"{prefix}.txt"
    report_path = tailored_dir / f"{prefix}_KEYWORD_REPORT.json"
    tex_path.write_text(master_tex, encoding="utf-8")
    txt_path.write_text("Tailored resume for apply agent", encoding="utf-8")
    (tailored_dir / f"{prefix}.pdf").write_bytes(b"%PDF-1.4 mock")
    report_path.write_text(
        json.dumps(
            {
                "adjustments": [
                    {
                        "jd_term": "C#",
                        "change": "Side Project: Java → C#",
                        "zone": "flex",
                        "note": "Adjacent JVM language on older project",
                    }
                ],
                "skipped_gaps": ["Rust"],
                "match_before": 0.55,
                "match_after": 0.82,
            }
        ),
        encoding="utf-8",
    )
    return {
        "status": "ok",
        "tex_path": str(tex_path),
        "report_path": str(report_path),
        "match_before": 0.55,
        "match_after": 0.82,
        "review_status": "pending",
        "compile_error": None,
        "tailored_resume_path": None,
    }


def test_add_pending_not_apply_ready(pipeline_env, monkeypatch):
    env = pipeline_env
    url = env["url"]

    monkeypatch.setattr(
        "applytex.jobs.add.enrich_single_url",
        lambda u: _mock_enrich(url),
    )
    monkeypatch.setattr(
        "applytex.jobs.add.score_job",
        lambda resume, job: {"score": 9, "keywords": "java", "reasoning": "strong fit"},
    )
    monkeypatch.setattr(
        "applytex.config.is_latex_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "applytex.jobs.add.load_app_config",
        lambda: {"pipeline": {"min_score": 8}},
    )
    monkeypatch.setattr(
        "applytex.config.load_profile",
        lambda: {"skills_boundary": {}, "resume_facts": {}},
    )
    monkeypatch.setattr(
        "applytex.latex.tailor.tailor_job",
        lambda master_tex, resume_text, job, profile: _mock_tailor(
            master_tex, resume_text, job, profile, env["tailored"]
        ),
    )

    summary = add_job_from_url(url, min_score=8)
    assert summary["status"] == "pending_review"
    assert summary["review_status"] == "pending"

    stats = get_stats()
    assert stats["pending_review"] == 1
    assert stats["ready_to_apply"] == 0

    assert acquire_job(target_url=url, min_score=7) is None


def test_approve_then_acquire_job(pipeline_env, monkeypatch):
    env = pipeline_env
    url = env["url"]

    monkeypatch.setattr(
        "applytex.jobs.add.enrich_single_url",
        lambda u: _mock_enrich(url),
    )
    monkeypatch.setattr(
        "applytex.jobs.add.score_job",
        lambda resume, job: {"score": 9, "keywords": "java", "reasoning": "strong"},
    )
    monkeypatch.setattr("applytex.config.is_latex_enabled", lambda: True)
    monkeypatch.setattr(
        "applytex.jobs.add.load_app_config",
        lambda: {"pipeline": {"min_score": 8}},
    )
    monkeypatch.setattr(
        "applytex.config.load_profile",
        lambda: {"skills_boundary": {}, "resume_facts": {}},
    )
    monkeypatch.setattr(
        "applytex.latex.tailor.tailor_job",
        lambda master_tex, resume_text, job, profile: _mock_tailor(
            master_tex, resume_text, job, profile, env["tailored"]
        ),
    )

    add_job_from_url(url, min_score=8)
    assert approve_job(url) is True

    stats = get_stats()
    assert stats["ready_to_apply"] == 1
    assert stats["pending_review"] == 0

    job = acquire_job(target_url=url, min_score=7)
    assert job is not None
    assert job["url"] == url
    assert job["tailored_resume_path"].endswith(".txt")
