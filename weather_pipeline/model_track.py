from __future__ import annotations

import math

import numpy as np

from .models import FrameData, ModelTrackPoint, Typhoon


def derive_model_track(
    frames: list[FrameData],
    typhoon: Typhoon,
    search_radius_degrees: float = 8.0,
) -> list[ModelTrackPoint]:
    """Estimate a GFS center track by following pressure minima near the storm.

    This is deliberately labeled as a model-derived center, never as an official
    warning track. The QWeather forecast remains a separate overlay.
    """
    if not typhoon.current:
        return []

    center_lon = typhoon.current.longitude
    center_lat = typhoon.current.latitude
    points: list[ModelTrackPoint] = []

    for frame_index, frame in enumerate(frames):
        if frame.valid_time < typhoon.current.time:
            continue

        lon_grid, lat_grid = np.meshgrid(frame.longitudes, frame.latitudes)
        cos_lat = max(0.35, math.cos(math.radians(center_lat)))
        distance = np.hypot((lon_grid - center_lon) * cos_lat, lat_grid - center_lat)
        mask = distance <= search_radius_degrees
        if not np.any(mask):
            break

        wind = frame.wind_speed_ms
        # Favor a compact low near the previous center while allowing the storm
        # to move quickly between 3-hour frames.
        score = frame.pressure_hpa + distance * 0.75 - np.minimum(wind, 60) * 0.10
        score = np.where(mask, score, np.inf)
        flat_index = int(np.argmin(score))
        row, column = np.unravel_index(flat_index, score.shape)
        pressure = float(frame.pressure_hpa[row, column])
        wind_speed = float(wind[row, column])

        if not np.isfinite(pressure) or pressure > 1016:
            break
        if points and wind_speed < 4 and pressure > 1010:
            break

        center_lon = float(frame.longitudes[column])
        center_lat = float(frame.latitudes[row])
        points.append(
            ModelTrackPoint(
                frame_index=frame_index,
                time=frame.valid_time,
                longitude=center_lon,
                latitude=center_lat,
                pressure_hpa=pressure,
                wind_speed_ms=wind_speed,
            )
        )
    return points


def derive_all_model_tracks(
    frames: list[FrameData], typhoons: list[Typhoon]
) -> dict[str, list[ModelTrackPoint]]:
    return {
        typhoon.storm_id: derive_model_track(frames, typhoon)
        for typhoon in typhoons
        if typhoon.is_active and typhoon.current
    }

