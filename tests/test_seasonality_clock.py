from datetime import datetime, timezone

import pytest

from return_intelligence.config import DEFAULT_DEMO_CLOCK, AppConfig, ConfigurationError
from return_intelligence.services.seasonality import SeasonalityService, season_for_date
from return_intelligence.services.supervisor import SupervisorService


def _at(month, day=15):
    return lambda: datetime(2026, month, day, 12, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_BACKEND", "simulated")
    monkeypatch.setenv("AWS_INTEGRATION_ENABLED", "false")
    monkeypatch.setenv("DEPLOYMENT_ENABLED", "false")
    for name in ("DEMO_CLOCK", "DEMO_SEASON", "DB_PATH", "UPLOAD_DIR", "ARTIFACT_DIR", "LOG_PATH"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.mark.parametrize(
    "month,season",
    [(1, "WINTER"), (3, "WINTER"), (11, "WINTER"), (5, "SUMMER"), (7, "SUMMER"), (4, "TRANSITION"), (9, "TRANSITION"), (10, "TRANSITION")],
)
def test_montreal_retail_calendar(month, season):
    assert season_for_date(_at(month)()) == season


def test_july_clock_derives_summer_and_override_wins():
    july = SeasonalityService(None, _at(7))
    summer = july.evaluate("SUMMER")
    assert summer.flag == 0 and summer.season == "SUMMER" and summer.source == "clock" and summer.as_of == "2026-07-15"
    assert summer.profile == "SUMMER"
    assert july.evaluate("WINTER").flag == 1
    overridden = SeasonalityService("WINTER", _at(7))
    result = overridden.evaluate("SUMMER")
    assert result.flag == 1 and result.season == "WINTER" and result.source == "override"
    transition = SeasonalityService(None, _at(4))
    assert transition.evaluate("SUMMER").flag == 0 and transition.evaluate("WINTER").flag == 0


def test_env_unset_uses_demo_clock_and_derived_season(env, tmp_path):
    config = AppConfig.from_env(tmp_path)
    assert config.demo_clock == datetime.fromisoformat(DEFAULT_DEMO_CLOCK) == datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    assert config.demo_season is None
    assert config.now() == config.demo_clock
    assert SeasonalityService(config.demo_season, config.now).current_season() == ("WINTER", "clock", "2026-01-15")


def test_demo_clock_now_and_naive_values(env, tmp_path):
    env.setenv("DEMO_CLOCK", "now")
    config = AppConfig.from_env(tmp_path)
    assert config.demo_clock is None
    assert abs((config.now() - datetime.now(timezone.utc)).total_seconds()) < 5
    env.setenv("DEMO_CLOCK", "")
    assert AppConfig.from_env(tmp_path).demo_clock is None
    env.setenv("DEMO_CLOCK", "2026-07-01T09:00:00")
    assert AppConfig.from_env(tmp_path).now() == datetime(2026, 7, 1, 9, tzinfo=timezone.utc)


def test_demo_season_override_is_validated(env, tmp_path):
    env.setenv("DEMO_SEASON", "summer")
    assert AppConfig.from_env(tmp_path).demo_season == "SUMMER"
    env.setenv("DEMO_SEASON", "SPRING")
    with pytest.raises(ConfigurationError):
        AppConfig.from_env(tmp_path)


def test_supervisor_default_clock_flags_sandal_in_winter(repo, tmp_path):
    service = SupervisorService(repo, tmp_path / "artifacts", None)
    result = service.seasonality.evaluate("SUMMER")
    assert result.flag == 1 and result.season == "WINTER" and result.source == "clock"
    assert service.warning.clock is service.clock


def test_complaint_events_use_business_clock(repo, tmp_path):
    service = SupervisorService(repo, tmp_path / "artifacts", None, clock=_at(7, 2))
    row = service.start_return("SYN-O-A95-001")
    service.submit_reason(row["return_id"], "wrong color")
    service.record_decision(row["return_id"], "REFUND")
    event = repo.one("SELECT occurred_at FROM complaint_events WHERE return_id=?", (row["return_id"],))
    assert event["occurred_at"] == "2026-07-02T12:00:00+00:00"
