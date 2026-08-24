"""Render single demo frames to PNG for fast design iteration.

Usage:
    .venv/bin/python tools/preview.py 0 6 12 --out work/preview
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from weather_pipeline.config import SETTINGS  # noqa: E402
from weather_pipeline.demo import build_demo_data  # noqa: E402
from weather_pipeline.model_track import derive_all_model_tracks  # noqa: E402
from weather_pipeline.render import render_frame  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("indices", nargs="*", type=int, default=[0])
    parser.add_argument("--out", default="work/preview")
    args = parser.parse_args()

    frames, city_weather, typhoons = build_demo_data()
    model_tracks = derive_all_model_tracks(frames, typhoons)
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    for index in args.indices or [0]:
        image = render_frame(
            frames[index],
            index,
            len(frames),
            "2026082100",
            city_weather,
            typhoons,
            model_tracks,
            SETTINGS,
            demo=True,
        )
        target = out_dir / f"frame-{index:02d}.png"
        image.save(target)
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
