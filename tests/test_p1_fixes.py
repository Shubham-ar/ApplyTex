"""Tests for P1 audit fixes: stats min_score, pdf pending count, batch limits."""

from pathlib import Path

import pytest

from applytex import config as cfg
from applytex.database import get_stats, init_db
from applytex.pipeline import _count_pending
from applytex.scoring.pdf import count_pending_pdf


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    app_dir = tmp_path / ".applytex"
    app_dir.mkdir()
    tailored = app_dir / "tailored_resumes"
    tailored.mkdir()
    db_path = app_dir / "applytex.db"
    config_path = app_dir / "config.yaml"

    monkeypatch.setattr(cfg, "APP_DIR", app_dir)
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "get_db_path", lambda: db_path)
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_path)
    monkeypatch.setattr(cfg, "TAILORED_DIR", tailored)

    import applytex.scoring.pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "TAILORED_DIR", tailored)

    conn = init_db(db_path)
    return {"conn": conn, "tailored": tailored, "config_path": config_path}


def test_get_stats_untailored_eligible_uses_config_min_score(app_env, monkeypatch):
    app_env["config_path"].write_text(
        "pipeline:\n  min_score: 6\n",
        encoding="utf-8",
    )
    conn = app_env["conn"]
    conn.execute(
        """
        INSERT INTO jobs (url, full_description, fit_score, tailored_resume_path)
        VALUES
          ('http://a/7', 'desc', 7, NULL),
          ('http://a/5', 'desc', 5, NULL)
        """
    )
    conn.commit()

    stats = get_stats(conn)
    assert stats["untailored_eligible"] == 1


def test_count_pending_pdf_ignores_existing_pdf_and_latex_jobs(app_env):
    tailored: Path = app_env["tailored"]
    conn = app_env["conn"]

    legacy_txt = tailored / "legacy_job.txt"
    legacy_txt.write_text("SUMMARY\nHello", encoding="utf-8")
    (tailored / "legacy_job.pdf").write_text("pdf", encoding="utf-8")

    missing_txt = tailored / "needs_pdf.txt"
    missing_txt.write_text("SUMMARY\nNeeds convert", encoding="utf-8")

    latex_txt = tailored / "latex_job.txt"
    latex_txt.write_text("SUMMARY\nLaTeX", encoding="utf-8")

    conn.execute(
        """
        INSERT INTO jobs (url, tailored_resume_path, tailored_latex_path)
        VALUES
          ('http://legacy', ?, NULL),
          ('http://missing', ?, NULL),
          ('http://latex', ?, ?)
        """,
        (str(legacy_txt), str(missing_txt), str(latex_txt), str(tailored / "latex_job.tex")),
    )
    conn.commit()

    assert count_pending_pdf() == 1
    assert _count_pending("pdf") == 1


def test_count_pending_pdf_zero_when_all_converted(app_env):
    tailored: Path = app_env["tailored"]
    conn = app_env["conn"]

    txt = tailored / "done.txt"
    txt.write_text("SUMMARY\nDone", encoding="utf-8")
    (tailored / "done.pdf").write_text("pdf", encoding="utf-8")

    conn.execute(
        "INSERT INTO jobs (url, tailored_resume_path) VALUES ('http://done', ?)",
        (str(txt),),
    )
    conn.commit()

    assert count_pending_pdf() == 0
    assert _count_pending("pdf") == 0
