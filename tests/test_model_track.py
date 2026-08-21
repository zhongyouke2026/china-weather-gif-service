from datetime import datetime, timedelta, timezone

import numpy as np

from weather_pipeline.model_track import derive_model_track
from weather_pipeline.models import FrameData, StormPoint, Typhoon


def test_model_track_follows_moving_pressure_minimum() -> None:
    start = datetime(2026, 8, 21, tzinfo=timezone.utc)
    longitudes = np.linspace(120, 135, 31, dtype=np.float32)
    latitudes = np.linspace(12, 27, 31, dtype=np.float32)
    lon_grid, lat_grid = np.meshgrid(longitudes, latitudes)
    frames = []
    for index in range(4):
        center_lon = 125 + index
        center_lat = 17 + index * 0.5
        distance_sq = (lon_grid - center_lon) ** 2 + (lat_grid - center_lat) ** 2
        pressure = (1012 - 35 * np.exp(-distance_sq / 3)).astype(np.float32)
        wind = (20 * np.exp(-distance_sq / 8)).astype(np.float32)
        frames.append(
            FrameData(
                forecast_hour=index * 3,
                valid_time=start + timedelta(hours=index * 3),
                longitudes=longitudes,
                latitudes=latitudes,
                precipitation_mm=np.zeros_like(pressure),
                pressure_hpa=pressure,
                u10_ms=wind,
                v10_ms=np.zeros_like(wind),
            )
        )

    storm = Typhoon(
        storm_id="NP_TEST",
        name="Test",
        is_active=True,
        current=StormPoint(start, 125, 17, pressure_hpa=977, wind_speed_ms=20),
    )
    track = derive_model_track(frames, storm)
    assert len(track) == 4
    assert abs(track[-1].longitude - 128) <= 0.5
    assert abs(track[-1].latitude - 18.5) <= 0.5

