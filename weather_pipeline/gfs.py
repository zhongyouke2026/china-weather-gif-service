from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests

from .config import Settings
from .models import FrameData


LOGGER = logging.getLogger(__name__)
GFS_CYCLES = (0, 6, 12, 18)


def parse_run(gfs_run: str) -> datetime:
    if len(gfs_run) != 10 or not gfs_run.isdigit():
        raise ValueError("GFS run must use YYYYMMDDHH format")
    return datetime.strptime(gfs_run, "%Y%m%d%H").replace(tzinfo=timezone.utc)


def candidate_runs(now: datetime | None = None, count: int = 16) -> list[str]:
    now = now or datetime.now(timezone.utc)
    latest_cycle = max((cycle for cycle in GFS_CYCLES if cycle <= now.hour), default=18)
    first = now.replace(hour=latest_cycle, minute=0, second=0, microsecond=0)
    if latest_cycle == 18 and now.hour < 18:
        first -= timedelta(days=1)
    return [
        (first - timedelta(hours=6 * index)).strftime("%Y%m%d%H")
        for index in range(count)
    ]


def gfs_index_url(settings: Settings, gfs_run: str, forecast_hour: int = 168) -> str:
    date = gfs_run[:8]
    cycle = gfs_run[8:]
    return (
        f"{settings.noaa_base_url}/pub/data/nccf/com/gfs/prod/"
        f"gfs.{date}/{cycle}/atmos/gfs.t{cycle}z.pgrb2.0p25."
        f"f{forecast_hour:03d}.idx"
    )


def filter_request(settings: Settings, gfs_run: str, forecast_hour: int) -> tuple[str, dict[str, str]]:
    date = gfs_run[:8]
    cycle = gfs_run[8:]
    params = {
        "file": f"gfs.t{cycle}z.pgrb2.0p25.f{forecast_hour:03d}",
        "lev_10_m_above_ground": "on",
        "lev_mean_sea_level": "on",
        "lev_surface": "on",
        "var_APCP": "on",
        "var_PRMSL": "on",
        "var_UGRD": "on",
        "var_VGRD": "on",
        "subregion": "",
        "leftlon": f"{settings.left_lon:g}",
        "rightlon": f"{settings.right_lon:g}",
        "toplat": f"{settings.top_lat:g}",
        "bottomlat": f"{settings.bottom_lat:g}",
        "dir": f"/gfs.{date}/{cycle}/atmos",
    }
    return f"{settings.noaa_base_url}/cgi-bin/filter_gfs_0p25.pl", params


class GfsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def find_latest_complete_run(self) -> str:
        for run in candidate_runs():
            try:
                response = requests.get(
                    gfs_index_url(self.settings, run, self.settings.max_forecast_hour),
                    headers={"Range": "bytes=0-0", "User-Agent": "china-weather-gif/1.0"},
                    timeout=10,
                )
                if response.ok:
                    LOGGER.info("Latest complete GFS run: %s", run)
                    return run
            except requests.RequestException as exc:
                LOGGER.warning("GFS probe failed for %s: %s", run, exc)
        raise RuntimeError("No complete GFS run was found in the NOMADS retention window")

    def download_frames(self, gfs_run: str) -> list[Path]:
        parse_run(gfs_run)
        bounds_key = (
            f"{self.settings.left_lon:g}-{self.settings.right_lon:g}_"
            f"{self.settings.bottom_lat:g}-{self.settings.top_lat:g}"
        ).replace(".", "p")
        target_dir = self.settings.work_dir / "gfs" / gfs_run / bounds_key
        target_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[int, Path] = {}

        with ThreadPoolExecutor(max_workers=self.settings.download_workers) as executor:
            futures = {
                executor.submit(self._download_one, gfs_run, hour, target_dir): hour
                for hour in self.settings.forecast_hours
            }
            for future in as_completed(futures):
                hour = futures[future]
                paths[hour] = future.result()

        return [paths[hour] for hour in self.settings.forecast_hours]

    def _download_one(self, gfs_run: str, hour: int, target_dir: Path) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"f{hour:03d}.grib2"
        if _is_grib(target):
            return target

        url, params = filter_request(self.settings, gfs_run, hour)
        part = target.with_suffix(".grib2.part")
        for attempt in range(1, 6):
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers={"User-Agent": "china-weather-gif/1.0"},
                    timeout=(15, 120),
                )
                response.raise_for_status()
                payload = response.content
                if (
                    len(payload) < 1_000
                    or not payload.startswith(b"GRIB")
                    or not payload.endswith(b"7777")
                ):
                    raise RuntimeError(
                        f"NOMADS returned a non-GRIB response for f{hour:03d}"
                    )
                part.write_bytes(payload)
                part.replace(target)
                LOGGER.info("Downloaded f%03d (%0.2f MB)", hour, len(payload) / 1_048_576)
                return target
            except (requests.RequestException, RuntimeError) as exc:
                if attempt == 5:
                    raise RuntimeError(f"Failed to download GFS f{hour:03d}: {exc}") from exc
                delay = min(30, 2**attempt)
                LOGGER.warning("Retrying f%03d in %ss: %s", hour, delay, exc)
                time.sleep(delay)
        raise AssertionError("unreachable")

    def load_frames(self, gfs_run: str, paths: list[Path]) -> list[FrameData]:
        run_time = parse_run(gfs_run)
        raw_frames = [read_grib(path, run_time) for path in paths]
        raw_frames.sort(key=lambda item: item["forecast_hour"])

        frames: list[FrameData] = []
        previous_precip: np.ndarray | None = None
        for raw in raw_frames:
            precip_raw = raw["precipitation_mm"]
            if raw["forecast_hour"] == 0:
                precipitation = np.zeros_like(precip_raw, dtype=np.float32)
            elif raw["precip_start_step"] > 0:
                precipitation = precip_raw
            elif previous_precip is None:
                precipitation = precip_raw
            else:
                difference = precip_raw - previous_precip
                precipitation = np.where(difference >= -0.05, difference, precip_raw)
            precipitation = np.clip(precipitation, 0, None).astype(np.float32)
            previous_precip = precip_raw

            frames.append(
                FrameData(
                    forecast_hour=raw["forecast_hour"],
                    valid_time=raw["valid_time"],
                    longitudes=raw["longitudes"],
                    latitudes=raw["latitudes"],
                    precipitation_mm=precipitation,
                    pressure_hpa=raw["pressure_hpa"].astype(np.float32),
                    u10_ms=raw["u10_ms"].astype(np.float32),
                    v10_ms=raw["v10_ms"].astype(np.float32),
                )
            )
        return frames


def _is_grib(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 1_000:
        return False
    with path.open("rb") as handle:
        if handle.read(4) != b"GRIB":
            return False
        handle.seek(-4, 2)
        return handle.read(4) == b"7777"


def _safe_get(codes_get: Any, message: Any, key: str, default: Any = None) -> Any:
    try:
        return codes_get(message, key)
    except Exception:
        return default


def read_grib(path: Path, run_time: datetime) -> dict[str, Any]:
    try:
        from eccodes import (
            codes_get,
            codes_get_array,
            codes_grib_new_from_file,
            codes_release,
        )
    except ImportError as exc:
        raise RuntimeError("Install the Python eccodes package to read GFS GRIB2 files") from exc

    fields: dict[str, np.ndarray] = {}
    metadata: dict[str, Any] = {}
    axes: tuple[np.ndarray, np.ndarray] | None = None

    with path.open("rb") as handle:
        while True:
            message = codes_grib_new_from_file(handle)
            if message is None:
                break
            try:
                short_name = str(_safe_get(codes_get, message, "shortName", ""))
                level_type = str(_safe_get(codes_get, message, "typeOfLevel", ""))
                level = float(_safe_get(codes_get, message, "level", -1))
                field_name: str | None = None
                if short_name == "prmsl" or level_type == "meanSea":
                    field_name = "pressure_hpa"
                elif short_name in {"10u", "u"} and level_type == "heightAboveGround" and level == 10:
                    field_name = "u10_ms"
                elif short_name in {"10v", "v"} and level_type == "heightAboveGround" and level == 10:
                    field_name = "v10_ms"
                elif short_name in {"tp", "apcp"} and level_type == "surface":
                    field_name = "precipitation_mm"
                    metadata["precip_start_step"] = int(
                        _safe_get(codes_get, message, "startStep", 0)
                    )

                if field_name is None or field_name in fields:
                    continue

                ni = int(codes_get(message, "Ni"))
                nj = int(codes_get(message, "Nj"))
                values = np.asarray(codes_get_array(message, "values"), dtype=np.float64).reshape(nj, ni)
                lat_grid = np.asarray(codes_get_array(message, "latitudes"), dtype=np.float64).reshape(nj, ni)
                lon_grid = np.asarray(codes_get_array(message, "longitudes"), dtype=np.float64).reshape(nj, ni)
                latitudes = lat_grid[:, 0]
                longitudes = np.mod(lon_grid[0, :] + 180.0, 360.0) - 180.0
                lat_order = np.argsort(latitudes)
                lon_order = np.argsort(longitudes)
                values = values[np.ix_(lat_order, lon_order)]
                fields[field_name] = values
                if axes is None:
                    axes = (longitudes[lon_order], latitudes[lat_order])
                metadata["forecast_hour"] = int(_safe_get(codes_get, message, "endStep", 0))
            finally:
                codes_release(message)

    forecast_hour = int(metadata.get("forecast_hour", int(path.stem[1:])))
    # The analysis file (f000) normally has no accumulated-precipitation
    # message. Its three-hour precipitation is exactly zero by definition.
    if (
        forecast_hour == 0
        and "precipitation_mm" not in fields
        and "pressure_hpa" in fields
    ):
        fields["precipitation_mm"] = np.zeros_like(fields["pressure_hpa"])
        metadata["precip_start_step"] = 0

    required = {"pressure_hpa", "u10_ms", "v10_ms", "precipitation_mm"}
    missing = required.difference(fields)
    if missing or axes is None:
        raise RuntimeError(f"Missing GRIB fields in {path.name}: {sorted(missing)}")

    if float(np.nanmedian(fields["pressure_hpa"])) > 2_000:
        fields["pressure_hpa"] = fields["pressure_hpa"] / 100.0

    return {
        **fields,
        "longitudes": axes[0].astype(np.float32),
        "latitudes": axes[1].astype(np.float32),
        "forecast_hour": forecast_hour,
        "valid_time": run_time + timedelta(hours=forecast_hour),
        "precip_start_step": int(metadata.get("precip_start_step", 0)),
    }
