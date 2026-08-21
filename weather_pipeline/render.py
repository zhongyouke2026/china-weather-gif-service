from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .config import PROJECT_ROOT, Settings

_default_cache = PROJECT_ROOT / "work"
os.environ.setdefault("MPLCONFIGDIR", str(_default_cache / "matplotlib"))
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")

import cartopy
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.colors as mcolors
import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
import numpy as np
from cartopy.io import shapereader
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnnotationBbox, DrawingArea
from matplotlib.patches import Arc, Circle, Ellipse, FancyBboxPatch, Polygon
from matplotlib.text import Text
from PIL import Image

from .models import CityWeather, FrameData, ModelTrackPoint, StormPoint, Typhoon

_cartopy_data_dir = Path(
    os.getenv("CARTOPY_DATA_DIR", str(_default_cache / "cartopy"))
)
_cartopy_data_dir.mkdir(parents=True, exist_ok=True)
cartopy.config["data_dir"] = str(_cartopy_data_dir)


LOGGER = logging.getLogger(__name__)

# A restrained, consumer-friendly palette inspired by Korean fintech products.
INK = "#191F28"
MUTED = "#8B95A1"
SUBTLE = "#B0B8C1"
BACKGROUND = "#F7F8FA"
SURFACE = "#FFFFFF"
LAND = "#F2F4F6"
OCEAN = "#EAF5F9"
PRIMARY = "#3182F6"
PRIMARY_DARK = "#1B64DA"
TYPHOON = "#F04452"
WARM = "#F76A35"
TAIWAN = "#6B5CF6"

# Storm identity is encoded redundantly with both color and a visible number.
# The number is repeated in the fixed west-side panel and in the storm eye, so
# no leader line is needed even when two tracks cross the crowded east coast.
STORM_COLORS = (TYPHOON, "#FF8A3D", "#00A6A6")

# One material system for every floating surface.  Animated GIFs cannot use a
# live backdrop blur, so the renderer recreates the useful parts of a frosted
# material with restrained translucency, a cool hairline, a white specular
# edge and one consistent soft shadow.  The more opaque surface is used for
# weather data cards, while the blue-tinted variant is reserved for time.
GLASS_SURFACE = "#F8FBFFE8"
GLASS_SURFACE_STRONG = "#FBFDFFF2"
GLASS_SURFACE_BLUE = "#EDF6FFE8"
GLASS_EDGE = "#FFFFFFEE"
GLASS_HAIRLINE = "#B8C7D6A8"
GLASS_SEPARATOR = "#AFC2D480"
GLASS_HIGHLIGHT = "#FFFFFFE8"
GLASS_SHADOW = "#455568"
GLASS_CONNECTOR = "#718397"

ScreenRect = tuple[float, float, float, float]
LabelCandidate = tuple[tuple[float, float], tuple[float, float]]

# Layer contract, bottom to top:
# basemap/weather (0-13) -> typhoon tracks -> fixed city markers/cards ->
# numbered typhoon eyes -> fixed UI panels -> title/date. City cards never move
# for a passing storm, while the critical numbered eye remains visible.
Z_TYPHOON_TRACK = 20
Z_TYPHOON_INFO = 33
Z_CITY_SECONDARY_POINT = 35
Z_CITY_SECONDARY_CARD = 36
Z_CITY_PRIMARY_POINT = 37
Z_CITY_PRIMARY_CARD = 38
Z_TYPHOON_CORE = 40
Z_FIXED_UI = 44
Z_FIXED_UI_TEXT = 45
Z_HEADER = 46
Z_TIME = 47

PRIMARY_CITY_KEYS = {
    "beijing",
    "dalian",
    "shanghai",
    "qingdao",
    "xian",
    "chengdu",
    "chongqing",
    "zhangjiajie",
    "guangzhou",
    "hongkong",
    "taipei",
}

# Every city uses one identical card template. Its dimensions, typography and
# full weather-icon slot never change as temperatures or conditions update.
CITY_CARD_WIDTH_POINTS = 56.0
CITY_CARD_HEIGHT_POINTS = 32.0
CITY_NAME_FONT_SIZE = 8.4
CITY_TEMPERATURE_FONT_SIZE = 8.8

TYPHOON_PANEL_LEFT = 0.018
TYPHOON_PANEL_TOP = 0.842
TYPHOON_PANEL_WIDTH = 0.215
TYPHOON_PANEL_HEADER_HEIGHT = 0.046
TYPHOON_PANEL_ROW_HEIGHT = 0.072
TYPHOON_PANEL_FOOTER_HEIGHT = 0.032
TYPHOON_PANEL_BOTTOM_PADDING = 0.008

PRECIP_LEVELS = [0.2, 1, 3, 6, 10, 20, 40, 80]
PRECIP_COLORS = [
    "#E3F2FF",
    "#CBE7FF",
    "#ACD8FF",
    "#82C2FF",
    "#57A6FF",
    "#3182F6",
    "#1B64DA",
    "#0B3F9B",
]
PRECIP_CMAP = mcolors.ListedColormap(PRECIP_COLORS)
PRECIP_NORM = mcolors.BoundaryNorm(PRECIP_LEVELS + [160], PRECIP_CMAP.N)


def _glass_path_effects(
    *,
    shadow_color: str = GLASS_SHADOW,
    shadow_alpha: float = 0.13,
    shadow_offset: tuple[float, float] = (0.0, -1.2),
    highlight: str = "#FFFFFFB8",
) -> list[path_effects.AbstractPathEffect]:
    """Return the shared optical edge and depth treatment for floating UI."""

    return [
        path_effects.SimplePatchShadow(
            offset=shadow_offset,
            shadow_rgbFace=shadow_color,
            alpha=shadow_alpha,
        ),
        path_effects.Stroke(linewidth=1.15, foreground=highlight),
        path_effects.Normal(),
    ]


def _configure_font() -> str:
    installed = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in (
        "Noto Sans CJK KR",
        "Noto Sans KR",
        "Apple SD Gothic Neo",
        "AppleGothic",
        "Malgun Gothic",
        "Arial Unicode MS",
    ):
        if candidate in installed:
            matplotlib.rcParams["font.family"] = candidate
            matplotlib.rcParams["axes.unicode_minus"] = False
            return candidate
    matplotlib.rcParams["font.family"] = "DejaVu Sans"
    matplotlib.rcParams["axes.unicode_minus"] = False
    LOGGER.warning("Korean font unavailable; install Noto Sans CJK KR for Korean labels")
    return "DejaVu Sans"


FONT_FAMILY = _configure_font()


@lru_cache(maxsize=1)
def _china_geometries() -> tuple:
    path = shapereader.natural_earth(
        resolution="110m",
        category="cultural",
        name="admin_0_countries",
    )
    geometries = []
    for record in shapereader.Reader(path).records():
        attributes = record.attributes
        code = (
            attributes.get("ADM0_A3")
            or attributes.get("SOV_A3")
            or attributes.get("ISO_A3")
        )
        name = attributes.get("ADMIN") or attributes.get("NAME_LONG")
        if code == "CHN" or name == "China":
            geometries.append(record.geometry)
    return tuple(geometries)


@lru_cache(maxsize=1)
def _taiwan_geometries() -> tuple:
    path = shapereader.natural_earth(
        resolution="110m",
        category="cultural",
        name="admin_0_countries",
    )
    geometries = []
    for record in shapereader.Reader(path).records():
        attributes = record.attributes
        code = (
            attributes.get("ADM0_A3")
            or attributes.get("SOV_A3")
            or attributes.get("ISO_A3")
        )
        name = attributes.get("ADMIN") or attributes.get("NAME_LONG")
        if code == "TWN" or name == "Taiwan":
            geometries.append(record.geometry)
    return tuple(geometries)


@lru_cache(maxsize=1)
def _china_province_geometries() -> tuple:
    try:
        path = shapereader.natural_earth(
            resolution="110m",
            category="cultural",
            name="admin_1_states_provinces_lines",
        )
        geometries = []
        for record in shapereader.Reader(path).records():
            attributes = record.attributes
            code = (
                attributes.get("adm0_a3")
                or attributes.get("ADM0_A3")
                or attributes.get("sov_a3")
            )
            if code == "CHN":
                geometries.append(record.geometry)
        return tuple(geometries)
    except Exception as exc:  # A missing optional Natural Earth layer is non-fatal.
        LOGGER.info("China province boundaries unavailable: %s", exc)
        return ()


def _condition_kind(condition: str) -> str:
    value = condition.casefold()
    if any(token in value for token in ("thunder", "storm", "雷", "번개", "폭풍")):
        return "storm"
    if any(token in value for token in ("snow", "sleet", "雪", "눈", "진눈깨비")):
        return "snow"
    if any(token in value for token in ("rain", "shower", "drizzle", "雨", "비", "소나기")):
        return "rain"
    if any(token in value for token in ("fog", "mist", "haze", "smog", "雾", "안개", "황사")):
        return "fog"
    if any(token in value for token in ("partly", "few cloud", "구름 조금", "多云")):
        return "partly"
    if any(token in value for token in ("clear", "sunny", "fair", "晴", "맑")):
        return "clear"
    if any(token in value for token in ("cloud", "overcast", "阴", "云", "구름", "흐림")):
        return "cloud"
    return "unknown"


def _weather_icon(
    condition: str,
    drawing: DrawingArea | None = None,
    *,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> DrawingArea:
    kind = _condition_kind(condition)
    drawing = drawing or DrawingArea(20, 18, 0, 0)
    cloud = "#A8B2BD"
    sun = "#FFB13B"
    rain = PRIMARY

    def x(value: float) -> float:
        return origin_x + value

    def y(value: float) -> float:
        return origin_y + value

    def add_sun(cx: float = 9.5, cy: float = 9.5, radius: float = 4.0) -> None:
        for angle in range(0, 360, 45):
            radians = np.radians(angle)
            drawing.add_artist(
                Line2D(
                    [x(cx + np.cos(radians) * 5.3), x(cx + np.cos(radians) * 7.0)],
                    [y(cy + np.sin(radians) * 5.3), y(cy + np.sin(radians) * 7.0)],
                    color=sun,
                    linewidth=1.15,
                    solid_capstyle="round",
                )
            )
        drawing.add_artist(
            Circle((x(cx), y(cy)), radius, facecolor=sun, edgecolor="none")
        )

    def add_cloud(cx: float = 10.0, cy: float = 9.0, scale: float = 1.0) -> None:
        drawing.add_artist(
            Ellipse(
                (x(cx), y(cy - 1.2 * scale)),
                15 * scale,
                6.5 * scale,
                facecolor=cloud,
                edgecolor="none",
            )
        )
        drawing.add_artist(
            Circle((x(cx - 4.0 * scale), y(cy + 0.4 * scale)), 3.4 * scale, facecolor=cloud, edgecolor="none")
        )
        drawing.add_artist(
            Circle((x(cx + 0.2 * scale), y(cy + 2.0 * scale)), 4.2 * scale, facecolor=cloud, edgecolor="none")
        )
        drawing.add_artist(
            Circle((x(cx + 4.1 * scale), y(cy + 0.2 * scale)), 3.2 * scale, facecolor=cloud, edgecolor="none")
        )

    if kind == "clear":
        add_sun()
    elif kind == "partly":
        add_sun(7, 11, 3.5)
        add_cloud(11.5, 7.5, 0.8)
    elif kind in ("rain", "storm", "snow"):
        add_cloud(10, 10.5, 0.85)
        if kind == "rain":
            for rain_x in (6.3, 10.2, 14.1):
                drawing.add_artist(
                    Line2D(
                        [origin_x + rain_x, origin_x + rain_x - 1.0],
                        [y(5.2), y(2.2)],
                        color=rain,
                        linewidth=1.45,
                        solid_capstyle="round",
                    )
                )
        elif kind == "storm":
            drawing.add_artist(
                Polygon(
                    [
                        (x(10.4), y(6.0)),
                        (x(7.7), y(1.0)),
                        (x(10.4), y(2.1)),
                        (x(9.5), y(-1.0)),
                        (x(14.0), y(4.2)),
                        (x(11.3), y(3.4)),
                    ],
                    closed=True,
                    facecolor=sun,
                    edgecolor="none",
                )
            )
        else:
            for cx in (7, 13):
                drawing.add_artist(Line2D([x(cx - 2), x(cx + 2)], [y(2.6), y(2.6)], color=rain, linewidth=1.0))
                drawing.add_artist(Line2D([x(cx), x(cx)], [y(0.6), y(4.6)], color=rain, linewidth=1.0))
                drawing.add_artist(Line2D([x(cx - 1.5), x(cx + 1.5)], [y(1.1), y(4.1)], color=rain, linewidth=0.9))
                drawing.add_artist(Line2D([x(cx - 1.5), x(cx + 1.5)], [y(4.1), y(1.1)], color=rain, linewidth=0.9))
    elif kind == "fog":
        for fog_y, width in ((12, 13), (8, 17), (4, 12)):
            drawing.add_artist(
                Line2D(
                    [x(10 - width / 2), x(10 + width / 2)],
                    [origin_y + fog_y, origin_y + fog_y],
                    color=SUBTLE,
                    linewidth=1.8,
                    solid_capstyle="round",
                )
            )
    else:
        add_cloud(10, 9, 0.9)
    return drawing


def _temperature_color(temperature_c: float | None) -> str:
    if temperature_c is None:
        return MUTED
    if temperature_c <= 12:
        return PRIMARY
    if temperature_c >= 30:
        return TYPHOON
    if temperature_c >= 27:
        return WARM
    return INK


def _city_card_content(
    key: str,
    label: str,
    temperature: float | None,
    condition: str,
) -> DrawingArea:
    temperature_label = f"{temperature:.0f}°" if temperature is not None else "--°"
    drawing = DrawingArea(
        CITY_CARD_WIDTH_POINTS,
        CITY_CARD_HEIGHT_POINTS,
        0,
        0,
    )
    drawing.add_artist(
        Text(
            CITY_CARD_WIDTH_POINTS / 2,
            23.2,
            label,
            color=INK,
            fontsize=CITY_NAME_FONT_SIZE,
            fontweight="bold",
            fontfamily=FONT_FAMILY,
            ha="center",
            va="center",
        )
    )
    # A tiny specular edge gives every fixed-size card the same glass depth
    # without adding another visible divider or competing with the weather.
    drawing.add_artist(
        Line2D(
            [10.0, CITY_CARD_WIDTH_POINTS - 10.0],
            [CITY_CARD_HEIGHT_POINTS - 0.9, CITY_CARD_HEIGHT_POINTS - 0.9],
            color=GLASS_HIGHLIGHT,
            linewidth=0.75,
            solid_capstyle="round",
        )
    )
    _weather_icon(condition, drawing, origin_x=8.0, origin_y=0.6)

    drawing.add_artist(
        Text(
            38.0,
            10.2,
            temperature_label,
            color=_temperature_color(temperature),
            fontsize=CITY_TEMPERATURE_FONT_SIZE,
            fontweight="bold",
            fontfamily=FONT_FAMILY,
            ha="center",
            va="center",
        )
    )
    return drawing


def _rectangles_overlap(
    first: ScreenRect,
    second: ScreenRect,
    margin: float = 3.0,
) -> bool:
    return not (
        first[2] + margin <= second[0]
        or second[2] + margin <= first[0]
        or first[3] + margin <= second[1]
        or second[3] + margin <= first[1]
    )


def _intersection_area(first: ScreenRect, second: ScreenRect) -> float:
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    return width * height


def _typhoon_panel_geometry(storm_count: int) -> tuple[float, float, float, float]:
    visible_count = min(3, max(0, storm_count))
    height = (
        TYPHOON_PANEL_HEADER_HEIGHT
        + visible_count * TYPHOON_PANEL_ROW_HEIGHT
        + TYPHOON_PANEL_FOOTER_HEIGHT
        + TYPHOON_PANEL_BOTTOM_PADDING
    )
    bottom = TYPHOON_PANEL_TOP - height
    return TYPHOON_PANEL_LEFT, bottom, TYPHOON_PANEL_WIDTH, height


def _label_reserved_boxes(
    ax: plt.Axes,
    typhoon_count: int = 0,
) -> list[ScreenRect]:
    width, height = ax.figure.canvas.get_width_height()
    boxes = [
        # Frameless title and sample badge.
        (width * 0.012, height * 0.895, width * 0.34, height * 0.995),
        # Date/time capsule.
        (width * 0.715, height * 0.895, width * 0.995, height * 0.995),
        # Rain legend and bottom progress line.
        (0.0, 0.0, width * 0.35, height * 0.13),
        (0.0, 0.0, float(width), height * 0.028),
        # Attribution. The route-style key lives inside the west-side panel.
        (width * 0.73, 0.0, float(width), height * 0.105),
    ]
    # Reserve the largest supported panel even when no storm is active. This
    # makes city placement independent from storms appearing, disappearing or
    # changing count between GFS runs; only the panel's visible height changes.
    left, bottom, panel_width, panel_height = _typhoon_panel_geometry(3)
    boxes.append(
        (
            width * left,
            height * bottom,
            width * (left + panel_width),
            height * (bottom + panel_height),
        )
    )
    return boxes


def _preferred_label_direction(offset: tuple[int, int]) -> str:
    horizontal = "left" if offset[0] < 0 else "right"
    if offset[1] >= 12:
        return f"upper_{horizontal}"
    if offset[1] <= -12:
        return f"lower_{horizontal}"
    return horizontal


def _city_label_candidates(offset: tuple[int, int]) -> list[LabelCandidate]:
    directions: dict[str, tuple[float, float, tuple[float, float]]] = {
        "right": (1.0, 0.0, (0.0, 0.5)),
        "upper_right": (1.0, 1.0, (0.0, 0.0)),
        "lower_right": (1.0, -1.0, (0.0, 1.0)),
        "above": (0.0, 1.0, (0.5, 0.0)),
        "below": (0.0, -1.0, (0.5, 1.0)),
        "upper_left": (-1.0, 1.0, (1.0, 0.0)),
        "lower_left": (-1.0, -1.0, (1.0, 1.0)),
        "left": (-1.0, 0.0, (1.0, 0.5)),
    }
    preferred = _preferred_label_direction(offset)
    preferred_vector = directions[preferred][:2]

    def direction_score(name: str) -> tuple[float, int]:
        vector = directions[name][:2]
        dot = preferred_vector[0] * vector[0] + preferred_vector[1] * vector[1]
        return (-dot, list(directions).index(name))

    direction_order = sorted(directions, key=direction_score)
    candidates: list[LabelCandidate] = []
    for gap in (10.0, 17.0, 25.0, 34.0, 46.0, 60.0, 76.0, 94.0, 115.0):
        for name in direction_order:
            x_direction, y_direction, alignment = directions[name]
            candidates.append(
                ((x_direction * gap, y_direction * gap), alignment)
            )

    preferred_horizontal = -1.0 if offset[0] < 0 else 1.0
    preferred_vertical = -1.0 if offset[1] < 0 else 1.0
    extra_ranked: list[tuple[float, LabelCandidate]] = []
    for x_direction in (preferred_horizontal, -preferred_horizontal):
        for x_gap in (12.0, 22.0, 36.0, 54.0, 76.0, 102.0, 132.0, 162.0):
            for y_direction in (preferred_vertical, -preferred_vertical):
                for y_gap in (0.0, 18.0, 32.0, 50.0, 72.0, 98.0, 128.0, 160.0):
                    x_offset = x_direction * x_gap
                    y_offset = y_direction * y_gap
                    alignment = (1.0, 0.5) if x_offset < 0 else (0.0, 0.5)
                    direction_penalty = 0.0
                    if x_direction != preferred_horizontal:
                        direction_penalty += 18.0
                    if y_direction != preferred_vertical:
                        direction_penalty += 10.0
                    extra_ranked.append(
                        (
                            np.hypot(x_gap, y_gap) + direction_penalty,
                            ((x_offset, y_offset), alignment),
                        )
                    )
    for _, candidate in sorted(extra_ranked, key=lambda item: item[0]):
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _select_label_placement(
    ax: plt.Axes,
    anchor: tuple[float, float],
    width: float,
    height: float,
    candidates: list[LabelCandidate],
    occupied: list[ScreenRect],
) -> tuple[tuple[float, float], tuple[float, float], ScreenRect, bool]:
    canvas_width, canvas_height = ax.figure.canvas.get_width_height()
    points_to_pixels = ax.figure.dpi / 72.0
    canvas = (6.0, 6.0, canvas_width - 6.0, canvas_height - 6.0)
    best: tuple[
        float,
        tuple[float, float],
        tuple[float, float],
        ScreenRect,
    ] | None = None

    for rank, (offset, alignment) in enumerate(candidates):
        reference_x = anchor[0] + offset[0] * points_to_pixels
        reference_y = anchor[1] + offset[1] * points_to_pixels
        left = reference_x - alignment[0] * width
        bottom = reference_y - alignment[1] * height
        rectangle = (left, bottom, left + width, bottom + height)
        inside = (
            rectangle[0] >= canvas[0]
            and rectangle[1] >= canvas[1]
            and rectangle[2] <= canvas[2]
            and rectangle[3] <= canvas[3]
        )
        collisions = [
            other
            for other in occupied
            if _rectangles_overlap(rectangle, other)
        ]
        if inside and not collisions:
            return offset, alignment, rectangle, True

        clipped_area = _intersection_area(rectangle, canvas)
        outside_area = width * height - clipped_area
        overlap_area = sum(_intersection_area(rectangle, other) for other in collisions)
        score = outside_area * 20.0 + overlap_area * 5.0 + rank
        if best is None or score < best[0]:
            best = (score, offset, alignment, rectangle)

    if best is None:
        raise RuntimeError("No city label placement candidates were provided")
    return best[1], best[2], best[3], False


def _city_label_anchors(
    ax: plt.Axes,
    city_weather: dict[str, CityWeather],
) -> dict[str, tuple[float, float]]:
    coordinate_transform = ccrs.PlateCarree()._as_mpl_transform(ax)
    return {
        weather.city.key: tuple(
            coordinate_transform.transform(
                (weather.city.longitude, weather.city.latitude)
            )
        )
        for weather in city_weather.values()
    }


def _draw_city_cards(
    ax: plt.Axes,
    frame: FrameData,
    city_weather: dict[str, CityWeather],
    occupied_boxes: list[ScreenRect],
    anchors: dict[str, tuple[float, float]],
) -> list[ScreenRect]:
    coordinate_transform = ccrs.PlateCarree()._as_mpl_transform(ax)
    ordered_weather = sorted(
        city_weather.values(),
        key=lambda weather: weather.city.key not in PRIMARY_CITY_KEYS,
    )
    occupied = list(occupied_boxes)

    for weather in ordered_weather:
        city = weather.city
        point = weather.at(frame.valid_time)
        temperature = point.temperature_c if point else None
        condition = point.condition if point else ""
        is_primary = city.key in PRIMARY_CITY_KEYS
        card = _city_card_content(
            city.key,
            city.label,
            temperature,
            condition,
        )

        ax.scatter(
            [city.longitude],
            [city.latitude],
            s=20,
            c=PRIMARY if city.key not in {"taipei", "taichung", "kaohsiung"} else TAIWAN,
            edgecolors=SURFACE,
            linewidths=1.0,
            transform=ccrs.PlateCarree(),
            zorder=Z_CITY_PRIMARY_POINT if is_primary else Z_CITY_SECONDARY_POINT,
        )

        points_to_pixels = ax.figure.dpi / 72.0
        estimated_width = CITY_CARD_WIDTH_POINTS * points_to_pixels
        estimated_height = CITY_CARD_HEIGHT_POINTS * points_to_pixels
        offset, alignment, rectangle, collision_free = _select_label_placement(
            ax,
            anchors[city.key],
            estimated_width,
            estimated_height,
            _city_label_candidates(city.label_offset),
            occupied,
        )
        if not collision_free:
            LOGGER.warning("City label placement required overlap fallback: %s", city.label)
        occupied.append(rectangle)

        annotation = AnnotationBbox(
            card,
            (city.longitude, city.latitude),
            xybox=offset,
            xycoords=coordinate_transform,
            boxcoords="offset points",
            box_alignment=alignment,
            frameon=True,
            bboxprops={
                "boxstyle": "round,pad=0,rounding_size=0.85",
                "facecolor": GLASS_SURFACE_STRONG,
                "edgecolor": GLASS_EDGE,
                "linewidth": 0.85,
            },
            arrowprops={
                "arrowstyle": "-",
                "color": GLASS_CONNECTOR,
                "linewidth": 0.55,
                "alpha": 0.38,
                "shrinkA": 2,
                "shrinkB": 4,
                "connectionstyle": "arc3,rad=0.025",
            },
            zorder=Z_CITY_PRIMARY_CARD if is_primary else Z_CITY_SECONDARY_CARD,
        )
        annotation.patch.set_path_effects(_glass_path_effects())
        ax.add_artist(annotation)
    return occupied


def _plot_track(
    ax: plt.Axes,
    points: Iterable[StormPoint | ModelTrackPoint],
    *,
    color: str,
    linestyle: str,
    linewidth: float,
    marker: str | None = None,
    alpha: float = 1.0,
    gid: str | None = None,
    zorder: int = Z_TYPHOON_TRACK,
) -> None:
    point_list = list(points)
    if not point_list:
        return
    line = ax.plot(
        [point.longitude for point in point_list],
        [point.latitude for point in point_list],
        color=color,
        alpha=alpha,
        linestyle=linestyle,
        linewidth=linewidth,
        marker=marker,
        markersize=4.2,
        markerfacecolor=SURFACE,
        markeredgecolor=color,
        markeredgewidth=1.25,
        transform=ccrs.PlateCarree(),
        zorder=zorder,
        solid_capstyle="round",
        dash_capstyle="round",
        path_effects=[
            path_effects.Stroke(linewidth=linewidth + 2.6, foreground="#FFFFFFD9"),
            path_effects.Normal(),
        ],
    )[0]
    if gid:
        line.set_gid(gid)


def _storm_display_point(typhoon: Typhoon, valid_time: datetime) -> StormPoint:
    current = typhoon.current
    if current is None:
        raise ValueError("Typhoon must have a current point")
    candidates = sorted([current, *typhoon.forecast], key=lambda point: point.time)
    if valid_time <= candidates[0].time or len(candidates) == 1:
        return candidates[0]
    if valid_time >= candidates[-1].time:
        return candidates[-1]

    def interpolate_optional(
        left: float | None,
        right: float | None,
        ratio: float,
    ) -> float | None:
        if left is None:
            return right
        if right is None:
            return left
        return left + (right - left) * ratio

    for left, right in zip(candidates, candidates[1:]):
        if left.time <= valid_time <= right.time:
            seconds = (right.time - left.time).total_seconds()
            ratio = 0.0 if seconds <= 0 else (valid_time - left.time).total_seconds() / seconds
            return StormPoint(
                time=valid_time,
                longitude=left.longitude + (right.longitude - left.longitude) * ratio,
                latitude=left.latitude + (right.latitude - left.latitude) * ratio,
                storm_type=right.storm_type or left.storm_type,
                pressure_hpa=interpolate_optional(left.pressure_hpa, right.pressure_hpa, ratio),
                wind_speed_ms=interpolate_optional(left.wind_speed_ms, right.wind_speed_ms, ratio),
                move_speed_kmh=interpolate_optional(left.move_speed_kmh, right.move_speed_kmh, ratio),
                move_direction=right.move_direction or left.move_direction,
            )
    return candidates[-1]


def _draw_typhoon_swirl(
    ax: plt.Axes,
    point: StormPoint,
    *,
    storm_number: int,
    color: str,
) -> None:
    transform = ccrs.PlateCarree()
    core = ax.scatter(
        [point.longitude],
        [point.latitude],
        s=360,
        c=color,
        edgecolors=SURFACE,
        linewidths=2.2,
        transform=transform,
        zorder=Z_TYPHOON_CORE,
        path_effects=[path_effects.SimplePatchShadow(offset=(0, -1), alpha=0.22), path_effects.Normal()],
    )
    core.set_gid(f"typhoon-map-core-{storm_number}")
    for width, theta1, theta2 in ((1.45, 24, 160), (1.45, 204, 340)):
        ax.add_patch(
            Arc(
                (point.longitude, point.latitude),
                width=width,
                height=width * 0.82,
                theta1=theta1,
                theta2=theta2,
                color=SURFACE,
                linewidth=1.8,
                transform=transform,
                zorder=Z_TYPHOON_CORE + 1,
            )
        )
    ax.add_patch(
        Circle(
            (point.longitude, point.latitude),
            radius=0.34,
            facecolor=SURFACE,
            edgecolor="none",
            transform=transform,
            zorder=Z_TYPHOON_CORE + 2,
        )
    )
    number = ax.text(
        point.longitude,
        point.latitude,
        str(storm_number),
        transform=transform,
        color=color,
        fontsize=6.4,
        fontweight="bold",
        ha="center",
        va="center",
        zorder=Z_TYPHOON_CORE + 3,
    )
    number.set_gid(f"typhoon-map-number-{storm_number}")


def _move_direction_ko(value: str) -> str:
    normalized = value.strip().upper().replace("-", " ")
    translations = {
        "N": "북쪽",
        "NORTH": "북쪽",
        "NE": "북동쪽",
        "NNE": "북북동쪽",
        "ENE": "동북동쪽",
        "NORTHEAST": "북동쪽",
        "E": "동쪽",
        "EAST": "동쪽",
        "SE": "남동쪽",
        "ESE": "동남동쪽",
        "SSE": "남남동쪽",
        "SOUTHEAST": "남동쪽",
        "S": "남쪽",
        "SOUTH": "남쪽",
        "SW": "남서쪽",
        "SSW": "남남서쪽",
        "WSW": "서남서쪽",
        "SOUTHWEST": "남서쪽",
        "W": "서쪽",
        "WEST": "서쪽",
        "NW": "북서쪽",
        "WNW": "서북서쪽",
        "NNW": "북북서쪽",
        "NORTHWEST": "북서쪽",
    }
    return translations.get(normalized.replace(" ", ""), value or "이동 정보 없음")


def _compact_label_value(value: str, limit: int) -> str:
    cleaned = value.strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1]}…"


def _draw_typhoon_info_pill(
    ax: plt.Axes,
    typhoon: Typhoon,
    point: StormPoint,
    storm_index: int,
    occupied: list[ScreenRect],
) -> None:
    current = typhoon.current
    if current is None:
        return

    pressure = point.pressure_hpa if point.pressure_hpa is not None else current.pressure_hpa
    wind = point.wind_speed_ms if point.wind_speed_ms is not None else current.wind_speed_ms
    movement_point = point if point.move_direction or point.move_speed_kmh else current
    vitals = []
    if pressure is not None:
        vitals.append(f"{pressure:.0f} hPa")
    if wind is not None:
        vitals.append(f"{wind:.0f} m/s")
    movement = _move_direction_ko(movement_point.move_direction) if movement_point.move_direction else ""
    if movement_point.move_speed_kmh is not None:
        movement = f"{movement}  ·  {movement_point.move_speed_kmh:.0f} km/h".strip(" ·")

    # A narrow, stacked card stays close to the storm even in the crowded
    # Taiwan / south-east China corridor. Name, number, intensity and movement
    # remain readable without forcing a several-hundred-pixel leader line.
    display_name = _compact_label_value(typhoon.name or "이름 확인 중", 7)
    display_id = _compact_label_value(typhoon.storm_id, 11)
    vitals_text = "  ·  ".join(vitals) if vitals else "중심 정보 확인 중"
    movement_text = movement or "이동 정보 확인 중"

    card_width_points = 82.0
    card_height_points = 43.0
    card_content = DrawingArea(card_width_points, card_height_points, 0, 0)
    # A small optical cyclone mark, restrained type hierarchy and a separator
    # make the alert readable as a designed component instead of raw API text.
    card_content.add_artist(
        Circle((8.2, 34.0), 4.8, facecolor="#FFFFFF2E", edgecolor="#FFFFFF5C", linewidth=0.5)
    )
    card_content.add_artist(
        Arc((8.2, 34.0), 5.7, 4.6, theta1=20, theta2=175, color=SURFACE, linewidth=0.8)
    )
    card_content.add_artist(
        Arc((8.2, 34.0), 5.7, 4.6, theta1=200, theta2=350, color=SURFACE, linewidth=0.8)
    )
    card_content.add_artist(
        Text(
            15.0,
            34.1,
            f"태풍 {display_name}",
            color=SURFACE,
            fontsize=6.6,
            fontweight="bold",
            fontfamily=FONT_FAMILY,
            ha="left",
            va="center",
        )
    )
    card_content.add_artist(
        Text(
            card_width_points - 5.0,
            34.0,
            display_id,
            color="#FFE7EB",
            fontsize=4.6,
            fontweight="semibold",
            fontfamily=FONT_FAMILY,
            ha="right",
            va="center",
        )
    )
    card_content.add_artist(
        Line2D(
            [6.0, card_width_points - 6.0],
            [26.3, 26.3],
            color="#FFFFFF52",
            linewidth=0.55,
            solid_capstyle="round",
        )
    )
    card_content.add_artist(
        Text(
            7.0,
            18.8,
            vitals_text,
            color=SURFACE,
            fontsize=5.9,
            fontweight="semibold",
            fontfamily=FONT_FAMILY,
            ha="left",
            va="center",
        )
    )
    card_content.add_artist(
        Text(
            7.0,
            9.5,
            movement_text,
            color="#FFF0F2",
            fontsize=5.65,
            fontweight="semibold",
            fontfamily=FONT_FAMILY,
            ha="left",
            va="center",
        )
    )

    lon_min, lon_max, lat_min, lat_max = ax.get_extent(ccrs.PlateCarree())
    place_left = point.longitude > (lon_min + lon_max) / 2
    place_below = point.latitude > lat_min + (lat_max - lat_min) * 0.74
    coordinate_transform = ccrs.PlateCarree()._as_mpl_transform(ax)
    anchor = tuple(
        coordinate_transform.transform((point.longitude, point.latitude))
    )
    points_to_pixels = ax.figure.dpi / 72.0
    label_width = card_width_points * points_to_pixels
    label_height = card_height_points * points_to_pixels

    preferred_horizontal = -1.0 if place_left else 1.0
    preferred_vertical = -1.0 if place_below else 1.0
    ranked_candidates: list[tuple[float, LabelCandidate]] = []
    for x_direction in (preferred_horizontal, -preferred_horizontal):
        for y_direction in (preferred_vertical, -preferred_vertical):
            for x_gap in (18.0, 28.0, 42.0, 60.0, 82.0, 108.0, 138.0):
                for y_gap in (26.0, 42.0, 62.0, 86.0, 115.0, 150.0, 190.0, 230.0):
                    x_offset = x_direction * x_gap
                    y_offset = y_direction * (y_gap + storm_index * 8.0)
                    alignment = (1.0, 0.5) if x_offset < 0 else (0.0, 0.5)
                    direction_penalty = 0.0
                    if x_direction != preferred_horizontal:
                        direction_penalty += 24.0
                    if y_direction != preferred_vertical:
                        direction_penalty += 14.0
                    distance = np.hypot(x_gap, y_gap) + direction_penalty
                    ranked_candidates.append(
                        (distance, ((x_offset, y_offset), alignment))
                    )
        for x_gap in (28.0, 48.0, 72.0, 100.0, 132.0):
            x_offset = x_direction * x_gap
            alignment = (1.0, 0.5) if x_offset < 0 else (0.0, 0.5)
            direction_penalty = 0.0 if x_direction == preferred_horizontal else 24.0
            ranked_candidates.append(
                (x_gap + direction_penalty, ((x_offset, 0.0), alignment))
            )
    candidate_pool = [
        candidate
        for _, candidate in sorted(ranked_candidates, key=lambda item: item[0])
    ]

    # If the nearby area is crowded, search the full canvas. These candidates
    # are intentionally appended after the local choices so the pill remains
    # near the storm whenever possible while the city cards stay fixed.
    canvas_width, canvas_height = ax.figure.canvas.get_width_height()
    global_ranked: list[tuple[float, LabelCandidate]] = []
    max_left = max(10.0, canvas_width - label_width - 10.0)
    for left in np.linspace(10.0, max_left, 42):
        for center_y in np.linspace(32.0, canvas_height - 32.0, 30):
            offset = (
                (left - anchor[0]) / points_to_pixels,
                (center_y - anchor[1]) / points_to_pixels,
            )
            distance = np.hypot(
                left + label_width / 2.0 - anchor[0],
                center_y - anchor[1],
            )
            global_ranked.append((distance, (offset, (0.0, 0.5))))
    for _, candidate in sorted(global_ranked, key=lambda item: item[0]):
        if candidate not in candidate_pool:
            candidate_pool.append(candidate)

    # Rank local and full-canvas candidates together by the card's actual
    # centre-to-storm distance. Previously every local candidate was tried
    # before the canvas search, so a collision-free but very remote local
    # position could win even when a much closer slot existed.
    def card_distance(candidate: LabelCandidate) -> float:
        candidate_offset, candidate_alignment = candidate
        reference_x = anchor[0] + candidate_offset[0] * points_to_pixels
        reference_y = anchor[1] + candidate_offset[1] * points_to_pixels
        center_x = reference_x + (0.5 - candidate_alignment[0]) * label_width
        center_y = reference_y + (0.5 - candidate_alignment[1]) * label_height
        return float(np.hypot(center_x - anchor[0], center_y - anchor[1]))

    candidates = sorted(candidate_pool, key=card_distance)

    offset, box_alignment, rectangle, collision_free = _select_label_placement(
        ax,
        anchor,
        label_width,
        label_height,
        candidates,
        occupied,
    )
    if not collision_free:
        LOGGER.warning("Typhoon label placement required overlap fallback: %s", typhoon.name)
    occupied.append(rectangle)
    curve_direction = 0.08 if box_alignment[0] == 1.0 else -0.08
    annotation = AnnotationBbox(
        card_content,
        (point.longitude, point.latitude),
        xybox=offset,
        xycoords=coordinate_transform,
        boxcoords="offset points",
        box_alignment=box_alignment,
        frameon=True,
        bboxprops={
            "boxstyle": "round,pad=0.52,rounding_size=1.2",
            "facecolor": "#E94655EE",
            "edgecolor": GLASS_EDGE,
            "linewidth": 0.9,
        },
        arrowprops={
            "arrowstyle": "-",
            "color": "#D54855",
            "linewidth": 0.75,
            "alpha": 0.68,
            "shrinkA": 4,
            "shrinkB": 9,
            "connectionstyle": f"arc3,rad={curve_direction}",
        },
        zorder=Z_TYPHOON_INFO,
    )
    annotation.patch.set_path_effects(
        _glass_path_effects(
            shadow_color="#7F1D2D",
            shadow_alpha=0.18,
            highlight="#FFFFFFA8",
        )
    )
    ax.add_artist(annotation)


def _draw_typhoon_panel(
    ax: plt.Axes,
    storms: list[tuple[int, Typhoon, StormPoint, str]],
) -> None:
    if not storms:
        return

    left, bottom, width, height = _typhoon_panel_geometry(len(storms))
    top = bottom + height
    panel = FancyBboxPatch(
        (left, bottom),
        width,
        height,
        transform=ax.transAxes,
        boxstyle="round,pad=0.007,rounding_size=0.017",
        facecolor=GLASS_SURFACE,
        edgecolor=GLASS_EDGE,
        linewidth=0.85,
        zorder=Z_FIXED_UI,
    )
    panel.set_gid("typhoon-status-panel")
    panel.set_path_effects(_glass_path_effects(shadow_alpha=0.12))
    ax.add_patch(panel)
    ax.plot(
        [left + 0.014, left + width - 0.014],
        [top - 0.006, top - 0.006],
        transform=ax.transAxes,
        color=GLASS_HIGHLIGHT,
        linewidth=0.75,
        solid_capstyle="round",
        zorder=Z_FIXED_UI_TEXT,
    )
    ax.text(
        left + 0.016,
        top - 0.023,
        "태풍 현황",
        transform=ax.transAxes,
        color=INK,
        fontsize=8.1,
        fontweight="bold",
        ha="left",
        va="center",
        zorder=Z_FIXED_UI_TEXT,
    )
    ax.text(
        left + width - 0.014,
        top - 0.023,
        f"{len(storms)}개 활동 중",
        transform=ax.transAxes,
        color=TYPHOON,
        fontsize=5.6,
        fontweight="semibold",
        ha="right",
        va="center",
        bbox={
            "boxstyle": "round,pad=0.28,rounding_size=0.55",
            "facecolor": "#FFF0F2D9",
            "edgecolor": "#FFFFFFB8",
            "linewidth": 0.45,
        },
        zorder=Z_FIXED_UI_TEXT,
    )

    for row_index, (storm_number, typhoon, point, color) in enumerate(storms):
        row_top = top - TYPHOON_PANEL_HEADER_HEIGHT - row_index * TYPHOON_PANEL_ROW_HEIGHT
        row_bottom = row_top - TYPHOON_PANEL_ROW_HEIGHT + 0.004
        row_center = (row_top + row_bottom) / 2
        row = FancyBboxPatch(
            (left + 0.008, row_bottom),
            width - 0.016,
            TYPHOON_PANEL_ROW_HEIGHT - 0.008,
            transform=ax.transAxes,
            boxstyle="round,pad=0,rounding_size=0.010",
            facecolor=mcolors.to_rgba(color, 0.055),
            edgecolor="none",
            zorder=Z_FIXED_UI,
        )
        row.set_gid(f"typhoon-panel-row-{storm_number}")
        ax.add_patch(row)

        number_marker = ax.scatter(
            [left + 0.027],
            [row_center],
            s=128,
            c=color,
            edgecolors=SURFACE,
            linewidths=1.1,
            transform=ax.transAxes,
            zorder=Z_FIXED_UI_TEXT,
        )
        number_marker.set_gid(f"typhoon-panel-marker-{storm_number}")
        panel_number = ax.text(
            left + 0.027,
            row_center,
            str(storm_number),
            transform=ax.transAxes,
            color=SURFACE,
            fontsize=6.3,
            fontweight="bold",
            ha="center",
            va="center",
            zorder=Z_FIXED_UI_TEXT + 1,
        )
        panel_number.set_gid(f"typhoon-panel-number-{storm_number}")

        current = typhoon.current or point
        pressure = point.pressure_hpa if point.pressure_hpa is not None else current.pressure_hpa
        wind = point.wind_speed_ms if point.wind_speed_ms is not None else current.wind_speed_ms
        movement_point = point if point.move_direction or point.move_speed_kmh else current
        vitals: list[str] = []
        if pressure is not None:
            vitals.append(f"{pressure:.0f} hPa")
        if wind is not None:
            vitals.append(f"{wind:.0f} m/s")
        vitals_text = " · ".join(vitals) if vitals else "중심 정보 확인 중"
        movement = (
            _move_direction_ko(movement_point.move_direction)
            if movement_point.move_direction
            else "이동 정보 확인 중"
        )
        if movement_point.move_speed_kmh is not None:
            movement = f"{movement} · {movement_point.move_speed_kmh:.0f} km/h"

        ax.text(
            left + 0.049,
            row_center + 0.013,
            _compact_label_value(typhoon.name or "이름 확인 중", 9),
            transform=ax.transAxes,
            color=INK,
            fontsize=7.3,
            fontweight="bold",
            ha="left",
            va="center",
            zorder=Z_FIXED_UI_TEXT,
        )
        ax.text(
            left + width - 0.015,
            row_center + 0.013,
            _compact_label_value(typhoon.storm_id, 13),
            transform=ax.transAxes,
            color=MUTED,
            fontsize=4.8,
            fontweight="semibold",
            ha="right",
            va="center",
            zorder=Z_FIXED_UI_TEXT,
        )

        ax.text(
            left + 0.049,
            row_center - 0.014,
            vitals_text,
            transform=ax.transAxes,
            color="#4E5968",
            fontsize=5.4,
            fontweight="semibold",
            ha="left",
            va="center",
            zorder=Z_FIXED_UI_TEXT,
        )
        ax.text(
            left + width - 0.015,
            row_center - 0.014,
            movement,
            transform=ax.transAxes,
            color=MUTED,
            fontsize=5.0,
            fontweight="semibold",
            ha="right",
            va="center",
            zorder=Z_FIXED_UI_TEXT,
        )

    legend_y = bottom + TYPHOON_PANEL_BOTTOM_PADDING + TYPHOON_PANEL_FOOTER_HEIGHT / 2
    ax.plot(
        [left + 0.017, left + 0.044],
        [legend_y, legend_y],
        transform=ax.transAxes,
        color="#64748B",
        linewidth=1.7,
        linestyle="--",
        solid_capstyle="round",
        zorder=Z_FIXED_UI_TEXT,
    )
    ax.text(
        left + 0.050,
        legend_y,
        "제공 경로",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=5.1,
        fontweight="semibold",
        ha="left",
        va="center",
        zorder=Z_FIXED_UI_TEXT,
    )
    ax.plot(
        [left + 0.119, left + 0.146],
        [legend_y, legend_y],
        transform=ax.transAxes,
        color="#64748B",
        linewidth=1.6,
        linestyle=":",
        solid_capstyle="round",
        zorder=Z_FIXED_UI_TEXT,
    )
    ax.text(
        left + 0.152,
        legend_y,
        "GFS 모델",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=5.1,
        fontweight="semibold",
        ha="left",
        va="center",
        zorder=Z_FIXED_UI_TEXT,
    )


def _draw_typhoon_route_legend(ax: plt.Axes) -> None:
    left, bottom, width, height = 0.758, 0.048, 0.224, 0.046
    panel = FancyBboxPatch(
        (left, bottom),
        width,
        height,
        transform=ax.transAxes,
        boxstyle="round,pad=0.006,rounding_size=0.014",
        facecolor=GLASS_SURFACE,
        edgecolor=GLASS_EDGE,
        linewidth=0.8,
        zorder=Z_FIXED_UI,
    )
    panel.set_path_effects(_glass_path_effects(shadow_alpha=0.10))
    ax.add_patch(panel)
    ax.plot(
        [left + 0.014, left + width - 0.014],
        [bottom + height - 0.005, bottom + height - 0.005],
        transform=ax.transAxes,
        color=GLASS_HIGHLIGHT,
        linewidth=0.65,
        solid_capstyle="round",
        zorder=Z_FIXED_UI_TEXT,
    )

    route_y = bottom + height / 2
    ax.plot(
        [0.773, 0.805],
        [route_y, route_y],
        transform=ax.transAxes,
        color="#64748B",
        linewidth=2.3,
        linestyle="--",
        zorder=Z_FIXED_UI,
        path_effects=[
            path_effects.Stroke(linewidth=4.0, foreground="#FFFFFFD9"),
            path_effects.Normal(),
        ],
    )
    ax.text(
        0.811,
        route_y,
        "제공 경로",
        transform=ax.transAxes,
        color="#465466",
        fontsize=5.8,
        fontweight="semibold",
        va="center",
        zorder=Z_FIXED_UI_TEXT,
    )
    ax.plot(
        [0.885, 0.915],
        [route_y, route_y],
        transform=ax.transAxes,
        color="#64748B",
        linewidth=2.0,
        linestyle=":",
        zorder=Z_FIXED_UI,
        path_effects=[
            path_effects.Stroke(linewidth=3.7, foreground="#FFFFFFD9"),
            path_effects.Normal(),
        ],
    )
    ax.text(
        0.921,
        route_y,
        "GFS 모델",
        transform=ax.transAxes,
        color="#465466",
        fontsize=5.8,
        fontweight="semibold",
        va="center",
        zorder=Z_FIXED_UI_TEXT,
    )


def _draw_typhoons(
    ax: plt.Axes,
    frame_index: int,
    frame: FrameData,
    typhoons: list[Typhoon],
    model_tracks: dict[str, list[ModelTrackPoint]],
    occupied_boxes: list[ScreenRect],
) -> list[ScreenRect]:
    occupied = list(occupied_boxes)
    active_typhoons = sorted(
        (
            typhoon
            for typhoon in typhoons
            if typhoon.is_active and typhoon.current
        ),
        key=lambda typhoon: typhoon.storm_id,
    )[:3]
    displayed_storms: list[tuple[int, Typhoon, StormPoint, str]] = []
    for storm_index, typhoon in enumerate(active_typhoons):
        storm_number = storm_index + 1
        storm_color = STORM_COLORS[storm_index % len(STORM_COLORS)]

        history = [*typhoon.history, typhoon.current]
        forecast = [typhoon.current, *typhoon.forecast]
        _plot_track(
            ax,
            history,
            color=storm_color,
            linestyle="-",
            linewidth=2.7,
            gid=f"typhoon-track-{storm_number}-history",
            zorder=21,
        )
        _plot_track(
            ax,
            forecast,
            color=storm_color,
            linestyle="--",
            linewidth=2.8,
            marker="o",
            gid=f"typhoon-track-{storm_number}-provided",
            zorder=22,
        )
        model_points = [
            point
            for point in model_tracks.get(typhoon.storm_id, [])
            if point.frame_index <= frame_index
        ]
        _plot_track(
            ax,
            model_points,
            color=storm_color,
            linestyle=":",
            linewidth=2.1,
            marker="s" if len(model_points) < 14 else None,
            alpha=0.68,
            gid=f"typhoon-track-{storm_number}-gfs",
            zorder=20,
        )

        display_point = _storm_display_point(typhoon, frame.valid_time)
        _draw_typhoon_swirl(
            ax,
            display_point,
            storm_number=storm_number,
            color=storm_color,
        )
        displayed_storms.append(
            (storm_number, typhoon, display_point, storm_color)
        )

    if displayed_storms:
        _draw_typhoon_panel(ax, displayed_storms)
    return occupied


def _draw_rain_legend(ax: plt.Axes) -> None:
    left, bottom, width, height = 0.018, 0.034, 0.318, 0.084
    card = FancyBboxPatch(
        (left, bottom),
        width,
        height,
        transform=ax.transAxes,
        boxstyle="round,pad=0.008,rounding_size=0.015",
        facecolor=GLASS_SURFACE,
        edgecolor=GLASS_EDGE,
        linewidth=0.85,
        zorder=Z_FIXED_UI,
    )
    card.set_path_effects(_glass_path_effects(shadow_alpha=0.11))
    ax.add_patch(card)

    ax.plot(
        [left + 0.014, left + width - 0.014],
        [bottom + height - 0.006, bottom + height - 0.006],
        transform=ax.transAxes,
        color=GLASS_HIGHLIGHT,
        linewidth=0.7,
        solid_capstyle="round",
        zorder=Z_FIXED_UI_TEXT,
    )

    rain_icon_x = left + 0.018
    rain_icon_y = bottom + height - 0.022
    for offset in (-0.006, 0.0, 0.006):
        ax.plot(
            [rain_icon_x + offset + 0.002, rain_icon_x + offset - 0.002],
            [rain_icon_y + 0.005, rain_icon_y - 0.003],
            transform=ax.transAxes,
            color=PRIMARY,
            linewidth=1.35,
            solid_capstyle="round",
            zorder=Z_FIXED_UI_TEXT,
        )
    ax.text(
        left + 0.036,
        rain_icon_y,
        "3시간 예상 강수량",
        transform=ax.transAxes,
        color=INK,
        fontsize=7.6,
        fontweight="semibold",
        va="center",
        zorder=Z_FIXED_UI_TEXT,
    )
    ax.text(
        left + width - 0.014,
        rain_icon_y,
        "mm 기준",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=5.3,
        fontweight="semibold",
        ha="right",
        va="center",
        zorder=Z_FIXED_UI_TEXT,
    )

    for center_x, color, label, amount in (
        (left + 0.057, PRECIP_COLORS[1], "약한 비", "0.2–3 mm"),
        (left + 0.159, PRECIP_COLORS[4], "보통 비", "3–10 mm"),
        (left + 0.261, PRECIP_COLORS[6], "강한 비", "10 mm+"),
    ):
        swatch = FancyBboxPatch(
            (center_x - 0.018, bottom + 0.034),
            0.036,
            0.011,
            transform=ax.transAxes,
            boxstyle="round,pad=0,rounding_size=0.0055",
            facecolor=color,
            edgecolor="#FFFFFF99",
            linewidth=0.45,
            zorder=Z_FIXED_UI_TEXT,
        )
        ax.add_patch(swatch)
        ax.text(
            center_x,
            bottom + 0.024,
            label,
            transform=ax.transAxes,
            color="#4E5968",
            fontsize=6.2,
            fontweight="semibold",
            ha="center",
            va="center",
            zorder=Z_FIXED_UI_TEXT,
        )
        ax.text(
            center_x,
            bottom + 0.010,
            amount,
            transform=ax.transAxes,
            color=MUTED,
            fontsize=5.3,
            ha="center",
            va="center",
            zorder=Z_FIXED_UI_TEXT,
        )


def _forecast_label(hours: int) -> str:
    if hours <= 0:
        return "지금"
    days, remainder = divmod(hours, 24)
    if days == 0:
        return f"{remainder}시간 후"
    if remainder == 0:
        return f"{days}일 후"
    return f"{days}일 {remainder}시간 후"


def _korean_datetime(value: datetime) -> str:
    weekdays = ("월", "화", "수", "목", "금", "토", "일")
    return f"{value.month}월 {value.day}일 {weekdays[value.weekday()]}요일  {value:%H:%M}"


def render_frame(
    frame: FrameData,
    frame_index: int,
    frame_count: int,
    gfs_run: str,
    city_weather: dict[str, CityWeather],
    typhoons: list[Typhoon],
    model_tracks: dict[str, list[ModelTrackPoint]],
    settings: Settings,
    *,
    demo: bool = False,
) -> Image.Image:
    fig = plt.figure(figsize=(10, 6.25), dpi=100, facecolor=OCEAN)
    ax = fig.add_axes([0, 0, 1, 1], projection=ccrs.PlateCarree())
    ax.set_extent(settings.bounds, crs=ccrs.PlateCarree())
    # The viewport and canvas ratios differ only slightly. Filling the canvas
    # avoids detached header/footer bands and keeps every label inside the map.
    ax.set_aspect("auto")
    ax.set_facecolor(OCEAN)
    ax.add_feature(cfeature.OCEAN.with_scale("110m"), facecolor=OCEAN, zorder=0)
    ax.add_feature(cfeature.LAND.with_scale("110m"), facecolor=LAND, zorder=1)
    ax.add_feature(
        cfeature.LAKES.with_scale("110m"),
        facecolor=OCEAN,
        edgecolor="#C9DCE4",
        linewidth=0.3,
        zorder=3,
    )
    ax.add_feature(
        cfeature.BORDERS.with_scale("110m"),
        edgecolor="#D2D8DE",
        linewidth=0.45,
        zorder=4,
    )
    ax.add_feature(
        cfeature.COASTLINE.with_scale("110m"),
        edgecolor="#B9C3CC",
        linewidth=0.45,
        zorder=4,
    )

    china = _china_geometries()
    taiwan = _taiwan_geometries()
    if china:
        ax.add_geometries(
            china,
            crs=ccrs.PlateCarree(),
            facecolor="#FCFDFE",
            edgecolor=PRIMARY,
            linewidth=1.4,
            zorder=2,
        )
    if taiwan:
        ax.add_geometries(
            taiwan,
            crs=ccrs.PlateCarree(),
            facecolor="#F4F1FF",
            edgecolor=TAIWAN,
            linewidth=1.25,
            zorder=2,
        )

    provinces = _china_province_geometries()
    if provinces:
        ax.add_geometries(
            provinces,
            crs=ccrs.PlateCarree(),
            facecolor="none",
            edgecolor="#D7DEE5",
            linewidth=0.32,
            zorder=3,
        )

    lon_grid, lat_grid = np.meshgrid(frame.longitudes, frame.latitudes)
    precipitation = np.ma.masked_less(frame.precipitation_mm, PRECIP_LEVELS[0])
    ax.contourf(
        lon_grid,
        lat_grid,
        precipitation,
        levels=PRECIP_LEVELS + [160],
        cmap=PRECIP_CMAP,
        norm=PRECIP_NORM,
        extend="max",
        alpha=0.82,
        antialiased=True,
        transform=ccrs.PlateCarree(),
        zorder=5,
    )

    min_pressure = max(920, int(np.nanmin(frame.pressure_hpa) // 8 * 8))
    max_pressure = min(1048, int(np.nanmax(frame.pressure_hpa) // 8 * 8 + 8))
    pressure_levels = np.arange(min_pressure, max_pressure + 1, 8)
    if len(pressure_levels) > 1:
        ax.contour(
            lon_grid,
            lat_grid,
            frame.pressure_hpa,
            levels=pressure_levels,
            colors="#4E5968",
            linewidths=0.55,
            alpha=0.14,
            transform=ccrs.PlateCarree(),
            zorder=7,
        )

    stride = max(1, round(len(frame.longitudes) / 15))
    ax.quiver(
        lon_grid[::stride, ::stride],
        lat_grid[::stride, ::stride],
        frame.u10_ms[::stride, ::stride],
        frame.v10_ms[::stride, ::stride],
        color="#4E5968",
        alpha=0.16,
        width=0.00145,
        headwidth=3.0,
        headlength=3.8,
        headaxislength=3.2,
        scale=500,
        transform=ccrs.PlateCarree(),
        zorder=8,
    )

    # Repaint the national outline above the rain so China remains instantly legible.
    if china:
        ax.add_geometries(
            china,
            crs=ccrs.PlateCarree(),
            facecolor="none",
            edgecolor=PRIMARY,
            linewidth=1.65,
            zorder=12,
        )
    if taiwan:
        ax.add_geometries(
            taiwan,
            crs=ccrs.PlateCarree(),
            facecolor="none",
            edgecolor=TAIWAN,
            linewidth=1.5,
            zorder=12,
        )

    ax.text(
        0.39,
        0.56,
        "중국",
        transform=ax.transAxes,
        color=PRIMARY,
        fontsize=40,
        fontweight="bold",
        alpha=0.075,
        ha="center",
        va="center",
        zorder=9,
    )
    ax.text(
        123.2,
        27.0,
        "대만",
        transform=ccrs.PlateCarree(),
        color=TAIWAN,
        fontsize=8.5,
        fontweight="bold",
        alpha=0.55,
        ha="left",
        va="center",
        zorder=13,
    )

    anchors = _city_label_anchors(ax, city_weather)
    active_typhoon_count = min(
        3,
        sum(
            1
            for typhoon in typhoons
            if typhoon.is_active and typhoon.current
        ),
    )
    occupied_boxes = _label_reserved_boxes(ax, active_typhoon_count)
    occupied_boxes.extend(
        (anchor[0] - 5.0, anchor[1] - 5.0, anchor[0] + 5.0, anchor[1] + 5.0)
        for anchor in anchors.values()
    )
    # Resolve the city layout without any storm data. The same inputs produce
    # the same card coordinates in every frame, so cards never jump as a
    # typhoon passes. Active-storm information stays in the reserved west-side
    # panel, while only the numbered eyes move across the map.
    occupied_boxes = _draw_city_cards(
        ax,
        frame,
        city_weather,
        occupied_boxes,
        anchors,
    )
    _draw_typhoons(
        ax,
        frame_index,
        frame,
        typhoons,
        model_tracks,
        occupied_boxes,
    )
    _draw_rain_legend(ax)

    ax.spines["geo"].set_edgecolor("none")

    cst = frame.valid_time.astimezone(timezone(timedelta(hours=8)))
    title_effects = [
        path_effects.Stroke(linewidth=2.8, foreground="#FFFFFFE8"),
        path_effects.Normal(),
    ]
    ax.text(
        0.026,
        0.952,
        "중여커 날씨",
        transform=ax.transAxes,
        color=INK,
        fontsize=28.0,
        fontweight="bold",
        ha="left",
        va="center",
        path_effects=title_effects,
        zorder=Z_HEADER,
    )
    ax.text(
        0.028,
        0.899,
        "태풍 · 비 · 도시별 온도",
        transform=ax.transAxes,
        color="#4E5968",
        fontsize=9.0,
        fontweight="bold",
        ha="left",
        va="center",
        path_effects=[
            path_effects.Stroke(linewidth=1.9, foreground="#FFFFFFE8"),
            path_effects.Normal(),
        ],
        zorder=Z_HEADER,
    )
    time_card = FancyBboxPatch(
        (0.725, 0.925),
        0.255,
        0.060,
        transform=ax.transAxes,
        boxstyle="round,pad=0,rounding_size=0.014",
        facecolor=GLASS_SURFACE_BLUE,
        edgecolor=GLASS_EDGE,
        linewidth=0.85,
        zorder=Z_TIME,
    )
    time_card.set_path_effects(_glass_path_effects(shadow_alpha=0.12))
    ax.add_patch(time_card)
    ax.plot(
        [0.741, 0.964],
        [0.978, 0.978],
        transform=ax.transAxes,
        color=GLASS_HIGHLIGHT,
        linewidth=0.75,
        solid_capstyle="round",
        zorder=Z_TIME + 1,
    )
    ax.plot(
        [0.883, 0.883],
        [0.937, 0.973],
        transform=ax.transAxes,
        color=GLASS_SEPARATOR,
        linewidth=0.8,
        zorder=Z_TIME + 1,
    )

    # Small vector glyphs add finish without relying on platform-specific emoji
    # rendering, which keeps all GIF frames identical on Linux and macOS.
    calendar = FancyBboxPatch(
        (0.739, 0.946),
        0.014,
        0.018,
        transform=ax.transAxes,
        boxstyle="round,pad=0,rounding_size=0.0025",
        facecolor="#FFFFFF73",
        edgecolor=PRIMARY,
        linewidth=0.65,
        zorder=Z_TIME + 1,
    )
    ax.add_patch(calendar)
    ax.plot(
        [0.7405, 0.7515],
        [0.958, 0.958],
        transform=ax.transAxes,
        color=PRIMARY,
        linewidth=0.55,
        zorder=Z_TIME + 2,
    )
    clock = Circle(
        (0.9005, 0.955),
        radius=0.008,
        transform=ax.transAxes,
        facecolor="#FFFFFF73",
        edgecolor=PRIMARY,
        linewidth=0.65,
        zorder=Z_TIME + 1,
    )
    ax.add_patch(clock)
    ax.plot(
        [0.9005, 0.9005, 0.9040],
        [0.960, 0.955, 0.9525],
        transform=ax.transAxes,
        color=PRIMARY,
        linewidth=0.55,
        solid_capstyle="round",
        zorder=Z_TIME + 2,
    )
    ax.text(
        0.758,
        0.955,
        _korean_datetime(cst),
        transform=ax.transAxes,
        color=PRIMARY_DARK,
        fontsize=7.8,
        fontweight="semibold",
        ha="left",
        va="center",
        zorder=Z_TIME + 1,
    )
    ax.text(
        0.943,
        0.955,
        _forecast_label(frame.forecast_hour),
        transform=ax.transAxes,
        color=PRIMARY_DARK,
        fontsize=7.8,
        fontweight="semibold",
        ha="center",
        va="center",
        zorder=Z_TIME + 1,
    )
    if demo:
        preview_badge = ax.text(
            0.226,
            0.952,
            "미리보기",
            transform=ax.transAxes,
            color=PRIMARY_DARK,
            fontsize=5.7,
            fontweight="semibold",
            ha="center",
            va="center",
            bbox={
                "boxstyle": "round,pad=0.34,rounding_size=0.7",
                "facecolor": GLASS_SURFACE_BLUE,
                "edgecolor": GLASS_EDGE,
                "linewidth": 0.65,
            },
            zorder=Z_TIME,
        )
        preview_patch = preview_badge.get_bbox_patch()
        if preview_patch is not None:
            preview_patch.set_path_effects(_glass_path_effects(shadow_alpha=0.09))

    ax.text(
        0.978,
        0.041,
        "Weather model: NOAA/NCEP GFS  ·  Weather & Typhoon data: QWeather",
        transform=ax.transAxes,
        color="#6B7684",
        fontsize=4.8,
        ha="right",
        va="center",
        path_effects=[
            path_effects.Stroke(linewidth=2.1, foreground="#FFFFFFEE"),
            path_effects.Normal(),
        ],
        zorder=Z_FIXED_UI_TEXT,
    )

    progress = (frame_index + 1) / frame_count
    progress_track = FancyBboxPatch(
        (0.018, 0.014),
        0.964,
        0.007,
        transform=ax.transAxes,
        boxstyle="round,pad=0,rounding_size=0.003",
        facecolor="#FFFFFF70",
        edgecolor="#FFFFFF9C",
        linewidth=0.35,
        zorder=Z_FIXED_UI,
    )
    progress_value = FancyBboxPatch(
        (0.018, 0.014),
        max(0.002, 0.964 * progress),
        0.007,
        transform=ax.transAxes,
        boxstyle="round,pad=0,rounding_size=0.003",
        facecolor=PRIMARY,
        edgecolor="none",
        zorder=Z_FIXED_UI_TEXT,
    )
    ax.add_patch(progress_track)
    ax.add_patch(progress_value)

    fig.canvas.draw()
    image = Image.frombuffer(
        "RGBA",
        fig.canvas.get_width_height(),
        fig.canvas.buffer_rgba(),
        "raw",
        "RGBA",
        0,
        1,
    ).convert("RGB")
    result = image.copy()
    plt.close(fig)
    return result


def _global_palette(frames: list[Image.Image], colors: int) -> Image.Image:
    sample_indices = np.linspace(0, len(frames) - 1, min(12, len(frames)), dtype=int)
    thumbnails = [
        frames[index].resize((200, 125), Image.Resampling.LANCZOS)
        for index in sample_indices
    ]
    atlas = Image.new("RGB", (200, 125 * len(thumbnails)))
    for index, thumbnail in enumerate(thumbnails):
        atlas.paste(thumbnail, (0, index * 125))

    reserved_hex = [
        INK,
        "#4E5968",
        MUTED,
        SUBTLE,
        PRIMARY,
        PRIMARY_DARK,
        TYPHOON,
        "#E54856",
        WARM,
        TAIWAN,
        SURFACE,
        LAND,
        OCEAN,
        "#A8B2BD",
        "#FFB13B",
        "#DCE2E8",
        "#6B7684",
        "#E8F3FF",
        "#FFF1C2",
        "#7C4D00",
        *PRECIP_COLORS,
    ]
    reserved = [
        tuple(round(channel * 255) for channel in mcolors.to_rgb(value))
        for value in reserved_hex
    ]
    requested_colors = min(256, max(2, colors))
    adaptive_count = max(2, requested_colors - len(reserved))
    adaptive = atlas.quantize(
        colors=adaptive_count,
        method=Image.Quantize.MEDIANCUT,
    )
    adaptive_values = adaptive.getpalette() or []
    adaptive_colors = [
        tuple(adaptive_values[index : index + 3])
        for index in range(0, adaptive_count * 3, 3)
    ]

    merged: list[tuple[int, int, int]] = []
    for color in [*reserved, *adaptive_colors]:
        if color not in merged:
            merged.append(color)
        if len(merged) == requested_colors:
            break
    merged.extend([merged[-1]] * (256 - len(merged)))

    palette = Image.new("P", (1, 1))
    palette.putpalette([channel for color in merged for channel in color])
    return palette


def render_gif(
    frames: list[FrameData],
    city_weather: dict[str, CityWeather],
    typhoons: list[Typhoon],
    model_tracks: dict[str, list[ModelTrackPoint]],
    gfs_run: str,
    output_path: Path,
    settings: Settings,
    *,
    demo: bool = False,
) -> Path:
    if not frames:
        raise ValueError("At least one frame is required")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered: list[Image.Image] = []
    for index, frame in enumerate(frames):
        LOGGER.info(
            "Rendering frame %s/%s (+%03dh)",
            index + 1,
            len(frames),
            frame.forecast_hour,
        )
        rendered.append(
            render_frame(
                frame,
                index,
                len(frames),
                gfs_run,
                city_weather,
                typhoons,
                model_tracks,
                settings,
                demo=demo,
            )
        )

    palette = _global_palette(rendered, settings.gif_colors)
    quantized = [
        # The map already uses discrete rain bands. Disabling color dithering
        # keeps Korean labels and small weather icons crisp instead of adding
        # red/blue fringe pixels around dark text.
        frame.quantize(palette=palette, dither=Image.Dither.NONE)
        for frame in rendered
    ]
    quantized[0].save(
        output_path,
        save_all=True,
        append_images=quantized[1:],
        duration=settings.frame_duration_ms,
        loop=0,
        # Clearing before each frame keeps the frameless title intact in GIF
        # viewers that otherwise mishandle cropped delta frames.
        optimize=False,
        disposal=2,
        comment=b"Weather model: NOAA/NCEP GFS; Weather & Typhoon data: QWeather",
    )

    with Image.open(output_path) as check:
        actual_frames = getattr(check, "n_frames", 1)
        if actual_frames != len(frames):
            raise RuntimeError(
                f"GIF verification failed: expected {len(frames)} frames, got {actual_frames}"
            )
        disposal_methods = set()
        for index in range(actual_frames):
            check.seek(index)
            disposal_methods.add(getattr(check, "disposal_method", None))
        if disposal_methods != {2}:
            raise RuntimeError(
                "GIF verification failed: frames must clear before redraw"
            )
    LOGGER.info(
        "GIF written: %s (%0.2f MB)",
        output_path,
        output_path.stat().st_size / 1_048_576,
    )
    return output_path
