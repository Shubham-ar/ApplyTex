"""Canonical job URL normalization and lookup."""

from __future__ import annotations

import sqlite3


def normalize_job_url(url: str) -> str:
    """Strip tracking query params and trailing slashes for stable DB keys."""
    url = url.strip()
    if "?" in url:
        url = url.split("?", 1)[0]
    return url.rstrip("/")


def resolve_job_url(conn: sqlite3.Connection, url: str) -> str | None:
    """Map a user/browser URL to the canonical ``jobs.url`` row."""
    normalized = normalize_job_url(url)
    row = conn.execute("SELECT url FROM jobs WHERE url = ?", (normalized,)).fetchone()
    if row:
        return row["url"]

    like = f"%{normalized}%"
    row = conn.execute(
        """
        SELECT url FROM jobs
        WHERE url LIKE ? OR application_url = ? OR application_url LIKE ?
        LIMIT 1
        """,
        (like, normalized, like),
    ).fetchone()
    return row["url"] if row else None
