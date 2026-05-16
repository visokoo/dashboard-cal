"""Weather adapter using Open-Meteo (no API key required)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import httpx

from ..config import GeocodeResult, WeatherConfig

log = logging.getLogger(__name__)

# Hardcoded host - the only outbound endpoint this module talks to (SSRF rule).
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> short label + Material icon name.
# See https://open-meteo.com/en/docs (WMO Weather interpretation codes).
WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear", "wb_sunny"),
    1: ("Mostly clear", "wb_sunny"),
    2: ("Partly cloudy", "wb_cloudy"),
    3: ("Overcast", "cloud"),
    45: ("Fog", "foggy"),
    48: ("Rime fog", "foggy"),
    51: ("Light drizzle", "grain"),
    53: ("Drizzle", "grain"),
    55: ("Heavy drizzle", "grain"),
    61: ("Light rain", "umbrella"),
    63: ("Rain", "umbrella"),
    65: ("Heavy rain", "umbrella"),
    71: ("Light snow", "ac_unit"),
    73: ("Snow", "ac_unit"),
    75: ("Heavy snow", "ac_unit"),
    77: ("Snow grains", "ac_unit"),
    80: ("Light showers", "umbrella"),
    81: ("Showers", "umbrella"),
    82: ("Heavy showers", "umbrella"),
    85: ("Snow showers", "ac_unit"),
    86: ("Snow showers", "ac_unit"),
    95: ("Thunderstorm", "thunderstorm"),
    96: ("Thunderstorm w/ hail", "thunderstorm"),
    99: ("Thunderstorm w/ hail", "thunderstorm"),
}


@dataclass(frozen=True)
class DayForecast:
    day: date
    code: int
    label: str
    icon: str
    high: float
    low: float
    precip_prob: int
    unit: str  # "F" or "C"


def _describe(code: int) -> tuple[str, str]:
    return WMO_CODES.get(code, ("--", "help_outline"))


def fetch_forecast(weather: WeatherConfig, loc: GeocodeResult) -> list[DayForecast]:
    """Synchronous fetch. Called from a worker thread to keep the UI responsive."""
    unit_param = "fahrenheit" if weather.unit == "fahrenheit" else "celsius"
    params = {
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "timezone": loc.timezone,
        "temperature_unit": unit_param,
        "forecast_days": weather.forecast_days,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    }
    try:
        resp = httpx.get(FORECAST_URL, params=params, timeout=10.0)
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError:
        # Generic message - we don't echo HTTP status/body bits (logging rule).
        log.warning("weather: fetch failed")
        return []

    daily = payload.get("daily") or {}
    days_s = daily.get("time") or []
    codes = daily.get("weather_code") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    pops = daily.get("precipitation_probability_max") or []
    out: list[DayForecast] = []
    unit_letter = "F" if weather.unit == "fahrenheit" else "C"
    for i, day_s in enumerate(days_s):
        try:
            code = int(codes[i])
            label, icon = _describe(code)
            out.append(
                DayForecast(
                    day=date.fromisoformat(day_s),
                    code=code,
                    label=label,
                    icon=icon,
                    high=float(highs[i]),
                    low=float(lows[i]),
                    precip_prob=int(pops[i] if i < len(pops) and pops[i] is not None else 0),
                    unit=unit_letter,
                )
            )
        except (IndexError, TypeError, ValueError):
            continue
    log.info("weather: fetched days=%d", len(out))
    return out
