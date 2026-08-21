from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from dateutil.parser import isoparse

from .config import Settings
from .models import City, CityWeather, StormPoint, Typhoon, WeatherPoint


LOGGER = logging.getLogger(__name__)

CITIES = (
    City("beijing", "베이징", 116.4074, 39.9042, (-72, 10)),
    City("shanghai", "상하이", 121.4737, 31.2304, (16, -8)),
    City("qingdao", "칭다오", 120.3826, 36.0671, (15, 8)),
    City("xian", "시안", 108.9398, 34.3416, (-67, 9)),
    City("chengdu", "청두", 104.0665, 30.5728, (-72, -6)),
    City("chongqing", "충칭", 106.5516, 29.5630, (14, -22)),
    City("zhangjiajie", "장자제", 110.4792, 29.1171, (18, 8)),
    City("guangzhou", "광저우", 113.2644, 23.1291, (-83, 20)),
    City("shenzhen", "선전", 114.0579, 22.5431, (18, 12)),
    City("hongkong", "홍콩", 114.1694, 22.3193, (18, -30)),
    City("harbin", "하얼빈", 126.6424, 45.7560, (15, 10)),
    City("dalian", "대련", 121.6147, 38.9140, (22, -18)),
    City("shenyang", "선양", 123.4315, 41.8057, (18, 10)),
    City("hangzhou", "항저우", 120.1551, 30.2741, (-68, -21)),
    City("nanjing", "난징", 118.7969, 32.0603, (-68, 18)),
    City("xiamen", "샤먼", 118.0894, 24.4798, (-64, 5)),
    City("sanya", "싼야", 109.5119, 18.2528, (-30, 17)),
    City("guilin", "구이린", 110.2900, 25.2736, (-64, 6)),
    City("macau", "마카오", 113.5439, 22.1987, (-58, -24)),
    City("taipei", "타이베이", 121.5654, 25.0330, (24, 15)),
    City("taichung", "타이중", 120.6736, 24.1477, (45, -4)),
    City("kaohsiung", "가오슝", 120.3014, 22.6273, (45, -31)),
)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _time(value: Any, fallback: datetime | None = None) -> datetime:
    if value:
        parsed = isoparse(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return fallback or datetime.now(timezone.utc)


class QWeatherClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = bool(settings.qweather_api_host and settings.qweather_api_key)
        self.host = (settings.qweather_api_host or "").rstrip("/")
        if self.host and not self.host.startswith(("https://", "http://")):
            self.host = f"https://{self.host}"
        self.mode = os.getenv("QWEATHER_API_MODE", "auto").lower()
        self.cache_dir = settings.work_dir / "qweather-cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-QW-Api-Key": settings.qweather_api_key or "",
                "Accept-Encoding": "gzip",
                "User-Agent": "china-weather-gif/1.0",
            }
        )

    def fetch_city_weather(self) -> dict[str, CityWeather]:
        if not self.enabled:
            LOGGER.warning("QWeather credentials are absent; city overlays use labels only")
            return {city.key: CityWeather(city=city) for city in CITIES}

        weather: dict[str, CityWeather] = {}
        for city in CITIES:
            try:
                weather[city.key] = self._fetch_city(city)
            except Exception as exc:
                LOGGER.warning("QWeather city request failed for %s: %s", city.label, exc)
                weather[city.key] = CityWeather(city=city)
        return weather

    def _fetch_city(self, city: City) -> CityWeather:
        if self.mode == "legacy":
            return self._fetch_city_legacy(city)
        try:
            return self._fetch_city_modern(city)
        except Exception:
            if self.mode == "modern":
                raise
            LOGGER.info("Falling back to QWeather city-based v7 for %s", city.label)
            # Remember the successful compatibility path so the remaining
            # cities do not each repeat a known-to-fail modern request.
            self.mode = "legacy"
            return self._fetch_city_legacy(city)

    def _fetch_city_modern(self, city: City) -> CityWeather:
        coordinates = f"{city.latitude:.4f}/{city.longitude:.4f}"
        common = {"lang": self.settings.qweather_language, "localTime": "false"}
        current_data = self._get(
            f"/weather/v1/current/{coordinates}", common, cache_seconds=1_800
        )
        hourly_data = self._get(
            f"/weather/v1/hourly/{coordinates}",
            {**common, "hours": "168"},
            cache_seconds=7_200,
        )

        current_temp = _float(current_data.get("temperature", {}).get("value"))
        current = None
        if current_temp is not None:
            current = WeatherPoint(
                time=datetime.now(timezone.utc),
                temperature_c=current_temp,
                condition=str(current_data.get("condition", {}).get("text", "")),
                wind_speed_ms=_float(
                    current_data.get("wind", {}).get("speed", {}).get("value")
                ),
            )

        hourly: list[WeatherPoint] = []
        for item in hourly_data.get("hours", []):
            temperature = _float(item.get("temperature", {}).get("value"))
            if temperature is None or not item.get("forecastTime"):
                continue
            hourly.append(
                WeatherPoint(
                    time=_time(item["forecastTime"]),
                    temperature_c=temperature,
                    condition=str(item.get("condition", {}).get("text", "")),
                    wind_speed_ms=_float(
                        item.get("wind", {}).get("speed", {}).get("value")
                    ),
                )
            )
        return CityWeather(city=city, current=current, hourly=hourly)

    def _fetch_city_legacy(self, city: City) -> CityWeather:
        common = {
            "location": f"{city.longitude:.2f},{city.latitude:.2f}",
            "lang": self.settings.qweather_language,
        }
        current_data = self._get(
            "/v7/weather/now", common, cache_seconds=1_800
        )
        try:
            hourly_data = self._get(
                "/v7/weather/168h", common, cache_seconds=7_200
            )
        except Exception as exc:
            LOGGER.warning(
                "QWeather 168h forecast unavailable for %s; using current data: %s",
                city.label,
                exc,
            )
            hourly_data = {}

        now = current_data.get("now", {})
        current_temp = _float(now.get("temp"))
        current = None
        if current_temp is not None:
            wind_kmh = _float(now.get("windSpeed"))
            current = WeatherPoint(
                time=_time(now.get("obsTime")),
                temperature_c=current_temp,
                condition=str(now.get("text", "")),
                wind_speed_ms=wind_kmh / 3.6 if wind_kmh is not None else None,
            )

        hourly: list[WeatherPoint] = []
        for item in hourly_data.get("hourly", []):
            temperature = _float(item.get("temp"))
            if temperature is None or not item.get("fxTime"):
                continue
            wind_kmh = _float(item.get("windSpeed"))
            hourly.append(
                WeatherPoint(
                    time=_time(item["fxTime"]),
                    temperature_c=temperature,
                    condition=str(item.get("text", "")),
                    wind_speed_ms=wind_kmh / 3.6 if wind_kmh is not None else None,
                )
            )
        return CityWeather(city=city, current=current, hourly=hourly)

    def fetch_active_typhoons(self) -> list[Typhoon]:
        if not self.enabled:
            return []

        now = datetime.now(timezone.utc)
        years = [now.year]
        if now.month == 1:
            years.append(now.year - 1)

        storms: dict[str, dict[str, Any]] = {}
        for year in years:
            try:
                payload = self._get(
                    "/v7/tropical/storm-list",
                    {"basin": "NP", "year": str(year)},
                    cache_seconds=3_600,
                )
                for item in payload.get("storm", []):
                    if item.get("isActive") == "1":
                        storms[str(item["id"])] = item
            except Exception as exc:
                LOGGER.warning("QWeather storm list failed for %s: %s", year, exc)

        active: list[Typhoon] = []
        for storm_id, item in storms.items():
            try:
                track = self._get(
                    "/v7/tropical/storm-track",
                    {"stormid": storm_id},
                    cache_seconds=1_800,
                )
                forecast = self._get(
                    "/v7/tropical/storm-forecast",
                    {"stormid": storm_id},
                    cache_seconds=1_800,
                )
                active.append(self._parse_typhoon(item, track, forecast))
            except Exception as exc:
                LOGGER.warning("QWeather storm detail failed for %s: %s", storm_id, exc)
        return active

    def _parse_typhoon(
        self,
        summary: dict[str, Any],
        track_data: dict[str, Any],
        forecast_data: dict[str, Any],
    ) -> Typhoon:
        current_raw = track_data.get("now")
        current = self._storm_point(current_raw, "pubTime") if current_raw else None
        history = [
            point
            for raw in track_data.get("track", [])
            if (point := self._storm_point(raw, "time")) is not None
        ]
        forecast = [
            point
            for raw in forecast_data.get("forecast", [])
            if (point := self._storm_point(raw, "fxTime")) is not None
        ]
        return Typhoon(
            storm_id=str(summary.get("id", "")),
            name=str(summary.get("name") or "Unnamed"),
            is_active=summary.get("isActive") == "1",
            current=current,
            history=history,
            forecast=forecast,
        )

    @staticmethod
    def _storm_point(raw: dict[str, Any], time_key: str) -> StormPoint | None:
        latitude = _float(raw.get("lat"))
        longitude = _float(raw.get("lon"))
        if latitude is None or longitude is None or not raw.get(time_key):
            return None
        return StormPoint(
            time=_time(raw[time_key]),
            longitude=longitude,
            latitude=latitude,
            storm_type=str(raw.get("type", "")),
            pressure_hpa=_float(raw.get("pressure")),
            wind_speed_ms=_float(raw.get("windSpeed")),
            move_speed_kmh=_float(raw.get("moveSpeed")),
            move_direction=str(raw.get("moveDir", "")),
        )

    def _get(
        self,
        path: str,
        params: dict[str, str],
        cache_seconds: int,
    ) -> dict[str, Any]:
        cache_key = hashlib.sha256(
            f"{self.host}{path}?{urlencode(sorted(params.items()))}".encode()
        ).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        cached = _read_cache(cache_path, cache_seconds)
        if cached is not None:
            return cached

        response = self.session.get(
            f"{self.host}{path}", params=params, timeout=(10, 30)
        )
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("code", "200")) != "200":
            raise RuntimeError(
                f"QWeather returned code {payload.get('code')} for {path}"
            )
        cache_path.write_text(
            json.dumps(
                {"cached_at": datetime.now(timezone.utc).isoformat(), "payload": payload},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return payload


def _read_cache(path: Path, ttl_seconds: int) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        cached_at = _time(cached.get("cached_at"))
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age <= ttl_seconds:
            return cached["payload"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return None
