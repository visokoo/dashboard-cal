"""Configuration loading and validation.

Reads ``config.yaml`` (path: project root or ``DASHBOARD_CAL_CONFIG`` env var) and
turns it into a typed settings object. Also handles one-time zip -> lat/lon
geocoding via the Open-Meteo geocoder, with the result cached on disk so we
don't re-geocode on every launch.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Literal

import httpx
import yaml
from platformdirs import user_data_path
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger(__name__)


# Hardcoded allowlist for outbound HTTP to satisfy SSRF-prevention rule:
# only Open-Meteo's geocoder is called from this module.
GEOCODER_URL = "https://geocoding-api.open-meteo.com/v1/search"
GEOCODE_CACHE_NAME = "geocode-cache.json"

# Strict regex for zip/postal codes: alphanumerics, spaces, and dashes only.
# Keeps user input out of any URL-building shenanigans.
ZIP_PATTERN = re.compile(r"^[A-Za-z0-9 \-]{2,12}$")
COUNTRY_PATTERN = re.compile(r"^[A-Z]{2}$")


class WeatherConfig(BaseModel):
    zip_code: str
    country: str = "US"
    unit: Literal["fahrenheit", "celsius"] = "fahrenheit"
    forecast_days: int = Field(default=6, ge=1, le=7)

    @field_validator("zip_code")
    @classmethod
    def _zip_ok(cls, v: str) -> str:
        if not ZIP_PATTERN.match(v):
            raise ValueError("zip_code must be 2-12 chars of letters/digits/spaces/dashes")
        return v.strip()

    @field_validator("country")
    @classmethod
    def _country_ok(cls, v: str) -> str:
        v = v.upper()
        if not COUNTRY_PATTERN.match(v):
            raise ValueError("country must be a 2-letter ISO code, e.g. 'US'")
        return v


class CalendarConfig(BaseModel):
    calendars: list[str] = Field(default_factory=lambda: ["primary"])
    week_start: Literal["sunday", "monday"] = "sunday"
    default_view: Literal["month", "week"] = "month"


class TasksConfig(BaseModel):
    list_name: str = "Grocery"


class PhotosConfig(BaseModel):
    folder: str = "~/Pictures/dashboard-bg"
    rotation_seconds: int = Field(default=60, ge=5, le=3600)
    shuffle: bool = True
    dim_percent: int = Field(default=35, ge=0, le=90)

    def resolved_folder(self) -> Path:
        # Expand ~ and env vars, then resolve to an absolute path. This is the
        # only place we touch the filesystem with user-supplied paths, and the
        # photos service double-checks each file is inside this directory
        # before opening it (path-traversal-prevention rule).
        return Path(os.path.expandvars(self.folder)).expanduser().resolve()


class RefreshConfig(BaseModel):
    calendar_seconds: int = Field(default=300, ge=30)
    tasks_seconds: int = Field(default=120, ge=30)
    weather_seconds: int = Field(default=900, ge=60)


class UIConfig(BaseModel):
    fullscreen: bool = True
    theme: Literal["dark", "light", "system"] = "dark"
    refresh: RefreshConfig = Field(default_factory=RefreshConfig)


class Settings(BaseModel):
    weather: WeatherConfig
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)
    tasks: TasksConfig = Field(default_factory=TasksConfig)
    photos: PhotosConfig = Field(default_factory=PhotosConfig)
    ui: UIConfig = Field(default_factory=UIConfig)


def _config_path() -> Path:
    env = os.environ.get("DASHBOARD_CAL_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "config.yaml").resolve()


def load_settings() -> Settings:
    path = _config_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"config.yaml not found at {path}. Copy config.example.yaml to config.yaml."
        )
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Settings.model_validate(raw)


class GeocodeResult(BaseModel):
    latitude: float
    longitude: float
    name: str
    timezone: str


def _cache_path() -> Path:
    p = user_data_path("dashboard-cal", appauthor=False, ensure_exists=True)
    return p / GEOCODE_CACHE_NAME


def _read_cache() -> dict[str, dict]:
    p = _cache_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("geocode cache corrupt; ignoring")
        return {}


def _write_cache(data: dict[str, dict]) -> None:
    _cache_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def geocode_zip(weather: WeatherConfig, *, force: bool = False) -> GeocodeResult:
    """Resolve a zip/postal code to lat/lon + timezone, with on-disk cache.

    Only hits a single hardcoded host (Open-Meteo geocoder) and only passes
    validated zip/country values as query params, satisfying the SSRF rule.
    """
    key = f"{weather.country}:{weather.zip_code}"
    cache = _read_cache()
    if not force and key in cache:
        return GeocodeResult.model_validate(cache[key])

    # User input has already been validated by pydantic; pass via params (not f-string).
    params = {
        "name": weather.zip_code,
        "country": weather.country,
        "count": 1,
        "language": "en",
        "format": "json",
    }
    try:
        resp = httpx.get(GEOCODER_URL, params=params, timeout=10.0)
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError as e:
        # Generic message - we don't echo raw HTTP error bodies (logging rule).
        log.error("geocode lookup failed for country=%s", weather.country)
        raise RuntimeError("Failed to look up zip code; check internet connection.") from e

    results = payload.get("results") or []
    if not results:
        raise ValueError(
            f"No location found for zip '{weather.zip_code}' ({weather.country}). "
            "Check config.yaml."
        )
    r = results[0]
    out = GeocodeResult(
        latitude=float(r["latitude"]),
        longitude=float(r["longitude"]),
        name=str(r.get("name", weather.zip_code)),
        timezone=str(r.get("timezone", "auto")),
    )
    cache[key] = out.model_dump()
    _write_cache(cache)
    return out
