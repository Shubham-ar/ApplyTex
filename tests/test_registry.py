import json
from datetime import datetime, timezone

import pytest

from applytex import config as cfg
from applytex import database
from applytex.database import init_db
from applytex.registry import list_registry, load_keyword_report


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    db_path = tmp_path / "applytex.db"
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "get_db_path", lambda: db_path)
    return init_db(db_path)


def test_list_registry_variant_and_flags(test_db, tmp_path):
    report_path = tmp_path / "acme_KEYWORD_REPORT.json"
    report_path.write_text(
        json.dumps(
            {
                "adjustments": [{"change": "Java → C# in flex block"}],
                "skipped_gaps": ["Rust"],
            }
        ),
        encoding="utf-8",
    )
    tex_path = tmp_path / "acme.tex"
    tex_path.write_text(r"\documentclass{article}", encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat()
    test_db.execute(
        """
        INSERT INTO jobs (
            url, title, site, fit_score, review_status,
            keyword_match_before, keyword_match_after,
            tailored_latex_path, keyword_report_path, tailored_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/job",
            "Backend Engineer",
            "Acme",
            9,
            "pending",
            0.4,
            0.75,
            str(tex_path),
            str(report_path),
            now,
        ),
    )
    test_db.commit()

    rows = list_registry(review_status="pending")
    assert len(rows) == 1
    row = rows[0]
    assert row["variant"] == "acme"
    assert row["flags"] == "1 adj, 1 gaps"
    assert row["match"] == "40%→75%"
    assert row["pdf_path"] == str(tex_path.with_suffix(".pdf"))


def test_list_registry_filters_review_status(test_db):
    now = datetime.now(timezone.utc).isoformat()
    for url, status in (
        ("https://a.com/1", "pending"),
        ("https://a.com/2", "approved"),
    ):
        test_db.execute(
            """
            INSERT INTO jobs (url, title, tailored_resume_path, review_status, tailored_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (url, "Job", f"/tmp/{url.split('/')[-1]}.txt", status, now),
        )
    test_db.commit()

    pending = list_registry(review_status="pending")
    assert len(pending) == 1
    assert pending[0]["review_status"] == "pending"


def test_load_keyword_report_missing():
    assert load_keyword_report(None) == {}
    assert load_keyword_report("/nonexistent/report.json") == {}
