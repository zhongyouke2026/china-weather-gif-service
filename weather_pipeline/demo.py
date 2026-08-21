from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from .models import CityWeather, FrameData, StormPoint, Typhoon, WeatherPoint
from .qweather import CITIES


def build_demo_data() -> tuple[list[FrameData], dict[str, CityWeather], list[Typhoon]]:
    start = datetime(2026, 8, 21, 0, tzinfo=timezone.utc)
    longitudes = np.linspace(72, 136, 129, dtype=np.float32)
    latitudes = np.linspace(17, 55, 77, dtype=np.float32)
    lon_grid, lat_grid = np.meshgrid(longitudes, latitudes)
    frames: list[FrameData] = []

    for index, forecast_hour in enumerate(range(0, 48, 3)):
        storm_lon = 126.0 + index * 0.72
        storm_lat = 19.0 + index * 0.48
        distance_sq = ((lon_grid - storm_lon) * 0.92) ** 2 + (lat_grid - storm_lat) ** 2
        monsoon = np.exp(-(((lon_grid - (104 + index * 0.35)) / 10) ** 2 + ((lat_grid - 28) / 5) ** 2))
        spiral = np.exp(-distance_sq / 18) * (1.1 + 0.45 * np.sin(np.sqrt(distance_sq) * 2.2 - index))
        precipitation = np.clip(22 * spiral + 12 * monsoon - 2.5, 0, None).astype(np.float32)
        pressure = (1014 - 32 * np.exp(-distance_sq / 16) + 4 * np.sin(np.radians(lon_grid * 4 + index * 9))).astype(np.float32)

        dx = (lon_grid - storm_lon) * np.cos(np.radians(storm_lat))
        dy = lat_grid - storm_lat
        radius = np.maximum(np.hypot(dx, dy), 0.7)
        circulation = 26 * np.exp(-radius / 7)
        u10 = (-circulation * dy / radius + 2.5).astype(np.float32)
        v10 = (circulation * dx / radius + 0.6).astype(np.float32)
        frames.append(
            FrameData(
                forecast_hour=forecast_hour,
                valid_time=start + timedelta(hours=forecast_hour),
                longitudes=longitudes,
                latitudes=latitudes,
                precipitation_mm=precipitation,
                pressure_hpa=pressure,
                u10_ms=u10,
                v10_ms=v10,
            )
        )

    city_weather: dict[str, CityWeather] = {}
    conditions = ("Clear", "Cloudy", "Showers", "Rain")
    for city_index, city in enumerate(CITIES):
        hourly = [
            WeatherPoint(
                time=frame.valid_time,
                temperature_c=22 + city_index * 0.55 + 3 * np.sin((frame.forecast_hour + city_index) / 12),
                condition=conditions[(city_index + frame.forecast_hour // 12) % len(conditions)],
                wind_speed_ms=3 + city_index * 0.2,
            )
            for frame in frames
        ]
        city_weather[city.key] = CityWeather(city=city, current=hourly[0], hourly=hourly)

    current = StormPoint(
        time=start,
        longitude=126.0,
        latitude=19.0,
        storm_type="TY",
        pressure_hpa=970,
        wind_speed_ms=36,
        move_speed_kmh=18,
        move_direction="NW",
    )
    history = [
        StormPoint(start - timedelta(hours=12 - step * 3), 122 + step, 16 + step * 0.75)
        for step in range(5)
    ]
    forecast = [
        StormPoint(
            start + timedelta(hours=step * 6),
            126 + step * 1.38,
            19 + step * 1.08,
            storm_type="TY" if step < 5 else "STS",
            pressure_hpa=970 + step * 2,
            wind_speed_ms=36 - step * 1.5,
        )
        for step in range(8)
    ]
    typhoon = Typhoon(
        storm_id="NP_DEMO01",
        name="DEMO",
        is_active=True,
        current=current,
        history=history,
        forecast=forecast,
    )
    return frames, city_weather, [typhoon]
