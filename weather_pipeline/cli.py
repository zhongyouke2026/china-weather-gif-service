from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import SETTINGS, Settings
from .gfs import GfsClient
from .qweather import QWeatherClient
from .storage import SupabaseStore, sha256_file


LOGGER = logging.getLogger(__name__)


def _logging() -> None:
    logging.basicConfig(
        level=os.getenv("WEATHER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )


def _output_path(raw: str | None, settings: Settings, gfs_run: str) -> Path:
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else Path.cwd() / path
    return settings.output_dir / f"china-weather-{gfs_run}.gif"


def command_probe(settings: Settings) -> int:
    run = GfsClient(settings).find_latest_complete_run()
    print(json.dumps({"gfs_run": run, "complete_through_hour": settings.max_forecast_hour}))
    return 0


def command_demo(output: str | None, settings: Settings) -> int:
    from .demo import build_demo_data
    from .model_track import derive_all_model_tracks
    from .render import render_gif

    frames, city_weather, typhoons = build_demo_data()
    model_tracks = derive_all_model_tracks(frames, typhoons)
    target = Path(output) if output else Path("public/sample/china-weather-sample.gif")
    if not target.is_absolute():
        target = Path.cwd() / target
    render_gif(
        frames,
        city_weather,
        typhoons,
        model_tracks,
        "2026082100",
        target,
        settings,
        demo=True,
    )
    print(target)
    return 0


def command_generate(
    gfs_run: str,
    output: str | None,
    no_upload: bool,
    settings: Settings,
) -> int:
    from .model_track import derive_all_model_tracks
    from .render import render_gif

    gfs = GfsClient(settings)
    if gfs_run == "auto":
        gfs_run = gfs.find_latest_complete_run()

    store: SupabaseStore | None = None
    claimed = False
    if not no_upload:
        store = SupabaseStore(settings)
        claimed = store.claim(gfs_run, os.getenv("GITHUB_EVENT_NAME", "batch"))
        if not claimed:
            LOGGER.info("Skipping %s: ready or actively processing", gfs_run)
            print(json.dumps({"status": "skipped", "gfs_run": gfs_run}))
            return 0

    try:
        qweather = QWeatherClient(settings)
        city_weather = qweather.fetch_city_weather()
        typhoons = qweather.fetch_active_typhoons()
        paths = gfs.download_frames(gfs_run)
        frames = gfs.load_frames(gfs_run, paths)
        model_tracks = derive_all_model_tracks(frames, typhoons)
        target = _output_path(output, settings, gfs_run)
        render_gif(
            frames,
            city_weather,
            typhoons,
            model_tracks,
            gfs_run,
            target,
            settings,
        )

        checksum = sha256_file(target)
        generated_at_value = datetime.now(timezone.utc)
        generated_at = generated_at_value.isoformat()
        storage_path = (
            f"{settings.asset_key}/{gfs_run}/"
            f"china-weather-{gfs_run}-{checksum[:12]}.gif"
        )
        metadata = {
            "pipelineVersion": __version__,
            "bounds": {
                "leftLon": settings.left_lon,
                "rightLon": settings.right_lon,
                "bottomLat": settings.bottom_lat,
                "topLat": settings.top_lat,
            },
            "forecastStepHours": settings.frame_step_hours,
            "activeTyphoons": [
                {"id": storm.storm_id, "name": storm.name} for storm in typhoons
            ],
            "qweatherCityCount": sum(
                1 for weather in city_weather.values() if weather.current or weather.hourly
            ),
            "attribution": [
                "Weather model: NOAA/NCEP GFS",
                "Weather & Typhoon data: QWeather",
            ],
        }

        manifest = target.with_suffix(".json")
        manifest.write_text(
            json.dumps(
                {
                    "assetKey": settings.asset_key,
                    "gfsRun": gfs_run,
                    "storagePath": storage_path,
                    "sha256": checksum,
                    "byteSize": target.stat().st_size,
                    "frameCount": len(frames),
                    "forecastStart": frames[0].valid_time.isoformat(),
                    "forecastEnd": frames[-1].valid_time.isoformat(),
                    "generatedAt": generated_at,
                    "metadata": metadata,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        if store:
            store.upload_file(target, storage_path, "image/gif")
            manifest_stamp = generated_at_value.strftime("%Y%m%dT%H%M%S%fZ")
            manifest_path = (
                f"{settings.asset_key}/{gfs_run}/manifest-{manifest_stamp}.json"
            )
            store.upload_file(manifest, manifest_path, "application/json")
            metadata["manifestPath"] = manifest_path
            store.mark_ready(
                gfs_run,
                storage_path=storage_path,
                sha256=checksum,
                byte_size=target.stat().st_size,
                frame_count=len(frames),
                forecast_start=frames[0].valid_time.isoformat(),
                forecast_end=frames[-1].valid_time.isoformat(),
                generated_at=generated_at,
                metadata=metadata,
            )

        print(
            json.dumps(
                {
                    "status": "ready",
                    "gfs_run": gfs_run,
                    "output": str(target),
                    "sha256": checksum,
                    "uploaded": bool(store),
                }
            )
        )
        return 0
    except Exception as exc:
        if store and claimed:
            store.mark_failed(gfs_run, str(exc))
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="china-weather",
        description="Generate and publish the China and Taiwan seven-day weather GIF",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("probe", help="Print the latest complete NOAA GFS run")

    demo = subparsers.add_parser("demo", help="Generate a synthetic sample GIF")
    demo.add_argument("--output", help="Output GIF path")

    generate = subparsers.add_parser("generate", help="Generate a production GIF")
    generate.add_argument(
        "--gfs-run",
        default="auto",
        help="YYYYMMDDHH or auto (default: auto)",
    )
    generate.add_argument("--output", help="Local output GIF path")
    generate.add_argument(
        "--no-upload",
        action="store_true",
        help="Render locally without Supabase DB/Storage",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _logging()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "probe":
            return command_probe(SETTINGS)
        if args.command == "demo":
            return command_demo(args.output, SETTINGS)
        if args.command == "generate":
            return command_generate(
                args.gfs_run,
                args.output,
                args.no_upload,
                SETTINGS,
            )
        raise AssertionError("unknown command")
    except KeyboardInterrupt:
        return 130
    except Exception:
        LOGGER.exception("Pipeline failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
