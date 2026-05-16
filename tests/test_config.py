"""Config-parsing tests. No network calls."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from dashboard_cal.config import Settings, WeatherConfig, load_settings


def test_weather_zip_invalid() -> None:
    with pytest.raises(ValueError):
        WeatherConfig(zip_code="bad/zip", country="US")


def test_weather_country_normalized() -> None:
    w = WeatherConfig(zip_code="98101", country="us")
    assert w.country == "US"


def test_weather_forecast_days_clamped() -> None:
    with pytest.raises(ValueError):
        WeatherConfig(zip_code="98101", forecast_days=99)


def test_load_settings_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "weather": {"zip_code": "98101", "country": "US", "forecast_days": 3},
                "calendar": {"calendars": ["primary"]},
                "tasks": {"list_name": "Test"},
                "photos": {"folder": str(tmp_path / "photos")},
                "ui": {"fullscreen": False},
            }
        )
    )
    monkeypatch.setenv("DASHBOARD_CAL_CONFIG", str(cfg))
    s = load_settings()
    assert isinstance(s, Settings)
    assert s.weather.forecast_days == 3
    assert s.tasks.list_name == "Test"
    assert s.ui.fullscreen is False


def test_load_settings_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DASHBOARD_CAL_CONFIG", str(tmp_path / "nope.yaml"))
    with pytest.raises(FileNotFoundError):
        load_settings()
