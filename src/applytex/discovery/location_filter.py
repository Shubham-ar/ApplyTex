"""Shared location accept/reject patterns from searches.yaml."""


def load_location_patterns(search_cfg: dict) -> tuple[list[str], list[str]]:
    """Load location filters from nested or legacy search config keys."""
    location = search_cfg.get("location") or {}
    accept = location.get("accept_patterns") or search_cfg.get("location_accept") or []
    reject = location.get("reject_patterns") or search_cfg.get("location_reject_non_remote") or []
    return list(accept), list(reject)


def location_ok(location: str | None, accept: list[str], reject: list[str]) -> bool:
    """Return True if a job location passes accept/reject rules."""
    if not location:
        return True

    loc = location.lower()

    if any(r in loc for r in ("remote", "anywhere", "work from home", "wfh", "distributed")):
        return True

    for pattern in reject:
        if pattern.lower() in loc:
            return False

    for pattern in accept:
        if pattern.lower() in loc:
            return True

    return False
