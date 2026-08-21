from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np


@dataclass(frozen=True)
class City:
    key: str
    label: str
    longitude: float
    latitude: float
    label_offset: tuple[int, int] = (7, 7)


@dataclass(frozen=True)
class WeatherPoint:
    time: datetime
    temperature_c: float
    condition: str
    wind_speed_ms: float | None = None


@dataclass
class CityWeather:
    city: City
    current: WeatherPoint | None = None
    hourly: list[WeatherPoint] = field(default_factory=list)

    def at(self, valid_time: datetime) -> WeatherPoint | None:
        if valid_time.tzinfo is None:
            valid_time = valid_time.replace(tzinfo=timezone.utc)
        if self.hourly:
            closest = min(
                self.hourly,
                key=lambda point: abs((point.time - valid_time).total_seconds()),
            )
            if abs((closest.time - valid_time).total_seconds()) <= 3 * 3600:
                return closest
        return self.current


@dataclass(frozen=True)
class StormPoint:
    time: datetime
    longitude: float
    latitude: float
    storm_type: str = ""
    pressure_hpa: float | None = None
    wind_speed_ms: float | None = None
    move_speed_kmh: float | None = None
    move_direction: str = ""


@dataclass
class Typhoon:
    storm_id: str
    name: str
    is_active: bool
    current: StormPoint | None = None
    history: list[StormPoint] = field(default_factory=list)
    forecast: list[StormPoint] = field(default_factory=list)


@dataclass(frozen=True)
class ModelTrackPoint:
    frame_index: int
    time: datetime
    longitude: float
    latitude: float
    pressure_hpa: float
    wind_speed_ms: float


@dataclass
class FrameData:
    forecast_hour: int
    valid_time: datetime
    longitudes: np.ndarray
    latitudes: np.ndarray
    precipitation_mm: np.ndarray
    pressure_hpa: np.ndarray
    u10_ms: np.ndarray
    v10_ms: np.ndarray

    @property
    def wind_speed_ms(self) -> np.ndarray:
        return np.hypot(self.u10_ms, self.v10_ms)

