from applytex.discovery.search_config import (
    build_wizard_search_config,
    filter_queries_by_tier,
    normalize_country_indeed,
    normalize_search_config,
    resolve_max_query_tier,
    resolve_scrape_locations,
    resolve_sites,
    suggested_location_patterns,
    title_excluded,
)


def test_normalize_country_indeed_aliases():
    assert normalize_country_indeed("CAN") == "canada"
    assert normalize_country_indeed("United States") == "usa"
    assert normalize_country_indeed("Canada") == "canada"


def test_resolve_sites_prefers_sites_over_boards():
    cfg = {"sites": ["indeed"], "boards": ["linkedin", "zip_recruiter"]}
    assert resolve_sites(cfg) == ["indeed"]


def test_resolve_sites_falls_back_to_boards():
    cfg = {"boards": ["indeed", "linkedin"]}
    assert resolve_sites(cfg) == ["indeed", "linkedin"]


def test_resolve_sites_default():
    assert resolve_sites({}) == ["indeed", "linkedin"]


def test_normalize_search_config_merges_legacy_country_and_boards():
    cfg = {
        "country": "CAN",
        "boards": ["indeed", "linkedin"],
        "defaults": {"hours_old": 48},
    }
    out = normalize_search_config(cfg)
    assert out["defaults"]["country_indeed"] == "canada"
    assert out["sites"] == ["indeed", "linkedin"]
    assert out["defaults"]["hours_old"] == 48


def test_title_excluded_case_insensitive():
    patterns = ["senior", "intern"]
    assert title_excluded("Senior Software Engineer", patterns) is True
    assert title_excluded("Software Developer", patterns) is False


def test_suggested_location_patterns_canada():
    accept, reject = suggested_location_patterns("Toronto, ON", "canada", city="Toronto")
    assert "Toronto" in accept
    assert "Canada" in accept
    assert "Remote" in accept
    assert "India" in reject


def test_get_db_path_legacy_fallback(tmp_path, monkeypatch):
    import applytex.config as cfg

    app_dir = tmp_path / ".applytex"
    app_dir.mkdir()
    legacy = app_dir / "applypilot.db"
    legacy.write_text("", encoding="utf-8")
    monkeypatch.setattr(cfg, "APP_DIR", app_dir)
    monkeypatch.setattr(cfg, "DB_PATH", app_dir / "applytex.db")
    monkeypatch.setattr(cfg, "LEGACY_DB_PATH", legacy)

    assert cfg.get_db_path() == legacy


def test_resolve_scrape_locations_local_first():
    cfg = {
        "locations": [
            {"location": "Canada", "remote": True},
            {"location": "Toronto, ON", "remote": False},
        ]
    }
    assert resolve_scrape_locations(cfg) == ["Toronto, ON", "Canada"]


def test_build_wizard_search_config_includes_sites_and_filters():
    cfg = build_wizard_search_config(
        search_location="Toronto, ON",
        distance=50,
        roles=["Software Developer"],
        country_indeed="canada",
        city="Toronto",
        province_state="Ontario",
        include_country_remote=True,
    )
    assert cfg["defaults"]["country_indeed"] == "canada"
    assert cfg["sites"] == ["indeed", "linkedin"]
    assert len(cfg["locations"]) == 2
    assert cfg["locations"][1]["remote"] is True
    assert cfg["exclude_titles"]


def test_filter_queries_by_tier():
    queries = [
        {"query": "a", "tier": 1},
        {"query": "b", "tier": 2},
        {"query": "c", "tier": 3},
    ]
    assert [q["query"] for q in filter_queries_by_tier(queries, 2)] == ["a", "b"]
    assert [q["query"] for q in filter_queries_by_tier(queries, None)] == ["a", "b", "c"]


def test_resolve_max_query_tier_prefers_jobspy():
    cfg = {"jobspy_max_tier": 1, "workday_max_tier": 3}
    assert resolve_max_query_tier(cfg) == 1


def test_build_wizard_queries_use_tier_one():
    cfg = build_wizard_search_config(
        search_location="Toronto, ON",
        distance=50,
        roles=["Backend Engineer", "Full Stack Developer"],
        country_indeed="canada",
    )
    assert all(q["tier"] == 1 for q in cfg["queries"])
