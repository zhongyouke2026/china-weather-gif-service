from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env")


def _integer(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _path(name: str, default: str) -> Path:
    raw = Path(os.getenv(name, default))
    return raw if raw.is_absolute() else PROJECT_ROOT / raw


@dataclass(frozen=True)
class Settings:
    # China-focused viewport with a small border/nearshore margin.
    left_lon: float = 72.0
    right_lon: float = 136.0
    bottom_lat: float = 17.0
    top_lat: float = 55.0
    max_forecast_hour: int = _integer("WEATHER_MAX_FORECAST_HOUR", 168)
    frame_step_hours: int = _integer("WEATHER_FRAME_STEP_HOURS", 3)
    download_workers: int = _integer("WEATHER_DOWNLOAD_WORKERS", 3)
    frame_duration_ms: int = _integer("WEATHER_FRAME_DURATION_MS", 420)
    gif_colors: int = _integer("WEATHER_GIF_COLORS", 192)
    noaa_base_url: str = os.getenv(
        "NOAA_GFS_BASE_URL", "https://nomads.ncep.noaa.gov"
    ).rstrip("/")
    qweather_api_host: str | None = os.getenv("QWEATHER_API_HOST")
    qweather_api_key: str | None = os.getenv("QWEATHER_API_KEY")
    qweather_language: str = os.getenv("QWEATHER_LANGUAGE", "ko")
    supabase_url: str | None = os.getenv("SUPABASE_URL")
    supabase_service_role_key: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    storage_bucket: str = os.getenv("WEATHER_STORAGE_BUCKET", "weather-assets")
    asset_key: str = os.getenv("WEATHER_ASSET_KEY", "china-7d")
    work_dir: Path = _path("WEATHER_WORK_DIR", "work")
    output_dir: Path = _path("WEATHER_OUTPUT_DIR", "artifacts")

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.left_lon, self.right_lon, self.bottom_lat, self.top_lat

    @property
    def forecast_hours(self) -> list[int]:
        return list(range(0, self.max_forecast_hour + 1, self.frame_step_hours))


SETTINGS = Settings()
