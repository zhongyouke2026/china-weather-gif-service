from __future__ import annotations

import logging
import math
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
from matplotlib.patches import Arc, Circle, Ellipse, FancyBboxPatch, Polygon, Rectangle
from matplotlib.text import Text
from matplotlib.transforms import IdentityTransform
from PIL import Image

from .models import CityWeather, FrameData, ModelTrackPoint, StormPoint, Typhoon

_cartopy_data_dir = Path(
    os.getenv("CARTOPY_DATA_DIR", str(_default_cache / "cartopy"))
)
_cartopy_data_dir.mkdir(parents=True, exist_ok=True)
cartopy.config["data_dir"] = str(_cartopy_data_dir)


LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Design system
#
# Every visible value in this module comes from one of the four scales below —
# color, type, space, radius. Nothing is tuned per component. The rules:
#
#   1. One accent color. Blue means "data we measured"; red/amber means "storm".
#      Everything else is a neutral gray so the weather is the only thing that
#      carries color.
#   2. Six type sizes, two weights. No in-between sizes.
#   3. All layout is expressed in pixels on a 1000x625 reference canvas and
#      snapped to a 4px grid, then scaled to whatever the real canvas is.
#      Chrome is drawn in display space so corner radii stay circular instead
#      of being stretched by the 1.6:1 canvas aspect ratio.
#   4. One surface style: near-opaque white, one hairline, one soft shadow.
# ---------------------------------------------------------------------------

# -- Color -------------------------------------------------------------------
LABEL = "#1D1D1F"           # primary text
LABEL_SECONDARY = "#565B62"  # supporting values
LABEL_TERTIARY = "#8B9199"   # captions, units, attribution

ACCENT = "#0071E3"
ACCENT_DEEP = "#0A4FA8"
ALERT = "#FF3B30"
WARM = "#FF9500"
COOL = "#3E9BE9"
TAIWAN = "#7D7BC4"

OCEAN = "#E6ECF2"            # canvas ground
LAND = "#F0F2F5"             # land outside the subject country
LAND_SUBJECT = "#FCFDFE"     # China and Taiwan read brighter than everything else
COASTLINE = "#CAD2DA"
BORDERLINE = "#D6DBE1"
SUBJECT_LINE = "#6FA0DE"

SURFACE = "#FFFFFF"
CARD_FILL = "#FFFFFFF2"
# City capsules sit directly on coastlines and rain, where a 95% fill lets the
# line underneath show through the text. They get a near-opaque fill instead.
CAPSULE_FILL = "#FFFFFFFC"
CARD_FILL_TINT = "#F4F9FFF2"
CARD_HAIRLINE = "#CFD6DE"
CARD_SHADOW = "#2A3644"
SEPARATOR = "#DDE2E8"

# Storm identity is encoded redundantly with color and a visible number, so a
# crossing track is still readable when two storms share the same coastline.
STORM_COLORS = (ALERT, "#FF9F0A", "#30B0C7")

ICON_CLOUD = "#AEB7C2"
ICON_SUN = "#FFB320"
ICON_RAIN = COOL

# -- Type (points at 100 dpi) ------------------------------------------------
TYPE_STAMP = 30.0        # the timestamp, the largest type in the frame
TYPE_STAMP_SUB = 17.0    # forecast offset under it
TYPE_HEADING = 11.0
TYPE_VALUE = 10.5        # city temperature — the number people look for
TYPE_BODY = 9.5
TYPE_LABEL = 9.5
TYPE_CAPTION = 7.6
TYPE_MICRO = 6.6

WEIGHT_REGULAR = "normal"
WEIGHT_BOLD = "bold"

# -- Space and radius (px on the reference canvas) ---------------------------
CANVAS_WIDTH_PX = 1000.0


def canvas_height(settings: Settings) -> float:
    """Frame height that renders the viewport without distorting shapes.

    The map fills the canvas with `set_aspect("auto")`, so the canvas itself
    has to carry the projection's aspect or the country comes out squashed.
    In Plate Carree one degree of longitude covers cos(latitude) of the ground
    that one degree of latitude does, which means:

        height = width * (lat span / lon span) / cos(mid latitude)

    Picking the height by eye instead is what flattened earlier versions: the
    original 625px frame stretched China 14% too wide, and cropping the top
    without recomputing the height took that to 19%. Deriving it here means
    changing `Settings.bounds` can never reintroduce the distortion.
    """

    left_lon, right_lon, bottom_lat, top_lat = settings.bounds
    middle = math.radians((bottom_lat + top_lat) / 2.0)
    ratio = (top_lat - bottom_lat) / (right_lon - left_lon)
    return round(CANVAS_WIDTH_PX * ratio / math.cos(middle))


CANVAS_HEIGHT_PX = canvas_height(Settings())
MARGIN = 24.0
RADIUS_CARD = 12.0
RADIUS_SMALL = 7.0
HAIRLINE = 0.7

ScreenRect = tuple[float, float, float, float]
LabelCandidate = tuple[tuple[float, float], tuple[float, float]]

# Layer contract, bottom to top:
# basemap/weather (0-13) -> typhoon tracks -> fixed city pills -> numbered
# typhoon eyes -> fixed chrome -> header. City pills never move for a passing
# storm; only the numbered eye travels across the map.
Z_TYPHOON_TRACK = 20
Z_CITY_LEADER = 34
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

# Every city uses one identical capsule. Its width, height, typography and
# icon slot never change as the temperature or the condition updates, so the
# map keeps a single rhythm instead of 22 differently sized boxes.
# Columns are sized from measured text rather than guessed: the widest Korean
# city name on the map ("타이베이") is 32.8pt at TYPE_LABEL and the widest
# temperature ("-15°") is 16.7pt at TYPE_VALUE. Padding and the icon are kept
# tight because every extra point of capsule width costs label placement on
# the crowded south east coast.
#   4 pad | 12 icon | 3.5 | 33 name | 3.5 | 17 value | 4 pad  =  77
CITY_CARD_WIDTH_POINTS = 77.0
CITY_CARD_HEIGHT_POINTS = 19.0
CITY_NAME_FONT_SIZE = TYPE_LABEL
CITY_TEMPERATURE_FONT_SIZE = TYPE_VALUE
CITY_ICON_SCALE = 0.60
CITY_LEADER_MIN_PX = 10.0

# Sea south-east of Taiwan: far enough from the island to stay legible, close
# enough to read as its label. Reserved so no city capsule lands on top of it.
TAIWAN_LABEL_LONLAT = (122.5, 22.1)

# -- Chrome layout (px from the left, and from the top or the bottom) --------
# The frame carries no title. The only thing at the top is the timestamp, set
# large enough to read at a glance, over the empty land in the north west.
# Line tops, not baselines. The gaps between them are deliberate: at these
# sizes the rendered lines are 36px, 21px and 12px tall, so an 18px gap is what
# keeps the block from reading as one dense lump.
STAMP_DATE_TOP = 26.0
STAMP_OFFSET_TOP = 80.0
STAMP_BADGE_TOP = 118.0
STAMP_BLOCK_WIDTH = 360.0
STAMP_BLOCK_BOTTOM = 150.0

# One information column in the bottom left, over Tibet and Xinjiang — the
# only large area of the map with no cities in it. Both cards share a width
# so the column reads as a single block.
COLUMN_LEFT = MARGIN
COLUMN_WIDTH = 272.0
COLUMN_GAP = 12.0

LEGEND_BOTTOM = 30.0
LEGEND_HEIGHT = 68.0
LEGEND_BAR_INSET = 16.0
LEGEND_BAR_HEIGHT = 9.0

PANEL_BOTTOM = LEGEND_BOTTOM + LEGEND_HEIGHT + COLUMN_GAP
PANEL_HEADER_HEIGHT = 38.0
PANEL_ROW_HEIGHT = 56.0
PANEL_FOOTER_HEIGHT = 30.0
PANEL_PADDING = 8.0

PROGRESS_HEIGHT = 3.0
# The credit sits bottom left, under the legend it belongs with. The old
# bottom-right corner is exactly where Pacific typhoons enter the frame.
ATTRIBUTION_BOTTOM = 15.0

PRECIP_LEVELS = [0.2, 1, 3, 6, 10, 20, 40, 80]
# One hue, eight steps, monotonically darker. A single ramp keeps the rain
# readable as an amount rather than as a set of unrelated colors.
PRECIP_COLORS = [
    "#DCEAF9",
    "#C1DCF6",
    "#A1CAF2",
    "#7CB4EC",
    "#569BE4",
    "#2F80DA",
    "#1961BE",
    "#0C4593",
]
PRECIP_CMAP = mcolors.ListedColormap(PRECIP_COLORS)
PRECIP_NORM = mcolors.BoundaryNorm(PRECIP_LEVELS + [160], PRECIP_CMAP.N)


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


def _bold_is_synthetic(family: str) -> bool:
    """True when asking for bold would silently render at regular weight.

    Korean families are usually shipped as a single `.ttc` collection, and
    matplotlib registers only one face out of it — on macOS every weight of
    Apple SD Gothic Neo resolves to the same file, so `fontweight="bold"`
    changes nothing at all. When that is the case the renderer thickens the
    glyph outline itself instead, which looks the same on any machine.
    """

    normal = font_manager.findfont(
        font_manager.FontProperties(family=family, weight="normal")
    )
    bold = font_manager.findfont(
        font_manager.FontProperties(family=family, weight="bold")
    )
    return normal == bold


SYNTHETIC_BOLD = _bold_is_synthetic(FONT_FAMILY)
if SYNTHETIC_BOLD:
    LOGGER.info("%s has no bold face; emphasis is drawn by stroking", FONT_FAMILY)


def _text_effects(
    color: str,
    size_points: float,
    *,
    bold: bool = False,
    halo: bool = False,
) -> list[path_effects.AbstractPathEffect]:
    """Weight and legibility treatment for one piece of type.

    Both strokes scale with the font size so the optical weight stays constant
    from the 6pt captions to the 21pt timestamp.
    """

    effects: list[path_effects.AbstractPathEffect] = []
    if halo:
        effects.append(
            path_effects.Stroke(
                linewidth=max(2.0, size_points * 0.22),
                foreground="#FFFFFFDD",
            )
        )
    if bold and SYNTHETIC_BOLD:
        effects.append(
            path_effects.Stroke(linewidth=size_points * 0.075, foreground=color)
        )
    effects.append(path_effects.Normal())
    return effects


def _card_shadow(alpha: float = 0.10) -> list[path_effects.AbstractPathEffect]:
    """The single elevation treatment shared by every floating surface."""

    return [
        path_effects.SimplePatchShadow(
            offset=(0.0, -1.4),
            shadow_rgbFace=CARD_SHADOW,
            alpha=alpha,
        ),
        path_effects.Normal(),
    ]


def _halo(width: float = 2.4, color: str = "#FFFFFFD9") -> list[path_effects.AbstractPathEffect]:
    """Keeps small type legible where it sits directly on the weather layer."""

    return [
        path_effects.Stroke(linewidth=width, foreground=color),
        path_effects.Normal(),
    ]


class _Chrome:
    """Pixel-space layout helper for the fixed user interface.

    Chrome is drawn in display coordinates rather than axes fractions so that
    a 12px corner radius is 12px on both axes. Everything is authored against
    the 1000x618 reference canvas and multiplied by one scale factor, so the
    same code renders correctly at another figure size or dpi.

    Vertical positions are measured up from the bottom, because every card
    lives in the bottom left column. The one top-anchored element, the
    timestamp, converts through `from_top`.
    """

    def __init__(self, ax: plt.Axes) -> None:
        width, height = ax.figure.canvas.get_width_height()
        self.ax = ax
        self.width = float(width)
        self.height = float(height)
        self.scale = self.width / CANVAS_WIDTH_PX
        self.transform = IdentityTransform()

    # -- coordinates --------------------------------------------------------
    def x(self, px: float) -> float:
        return px * self.scale

    def up(self, px_from_bottom: float) -> float:
        return px_from_bottom * self.scale

    def from_top(self, px_from_top: float) -> float:
        """Reference-space y for something pinned to the top of the canvas."""

        return self.height / self.scale - px_from_top

    def s(self, px: float) -> float:
        return px * self.scale

    def f(self, points: float) -> float:
        return points * self.scale

    # -- primitives ---------------------------------------------------------
    def card(
        self,
        left: float,
        bottom: float,
        width: float,
        height: float,
        *,
        radius: float = RADIUS_CARD,
        facecolor: str = CARD_FILL,
        edgecolor: str = CARD_HAIRLINE,
        shadow: float = 0.10,
        zorder: int = Z_FIXED_UI,
        gid: str | None = None,
    ) -> FancyBboxPatch:
        """`bottom` is measured up from the bottom edge of the canvas."""

        patch = FancyBboxPatch(
            (self.x(left), self.up(bottom)),
            self.s(width),
            self.s(height),
            transform=self.transform,
            boxstyle=f"round,pad=0,rounding_size={self.s(radius)}",
            mutation_aspect=1.0,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=HAIRLINE,
            clip_on=False,
            zorder=zorder,
        )
        if gid:
            patch.set_gid(gid)
        if shadow:
            patch.set_path_effects(_card_shadow(shadow))
        self.ax.add_patch(patch)
        return patch

    def text(
        self,
        left: float,
        bottom: float,
        value: str,
        *,
        size: float = TYPE_BODY,
        color: str = LABEL,
        weight: str = WEIGHT_REGULAR,
        ha: str = "left",
        va: str = "center",
        zorder: int = Z_FIXED_UI_TEXT,
        halo: bool = False,
        gid: str | None = None,
    ) -> Text:
        artist = self.ax.text(
            self.x(left),
            self.up(bottom),
            value,
            transform=self.transform,
            color=color,
            fontsize=self.f(size),
            fontweight=weight,
            fontfamily=FONT_FAMILY,
            ha=ha,
            va=va,
            clip_on=False,
            zorder=zorder,
        )
        artist.set_path_effects(
            _text_effects(
                color,
                self.f(size),
                bold=weight == WEIGHT_BOLD,
                halo=halo,
            )
        )
        if gid:
            artist.set_gid(gid)
        return artist

    def rule(
        self,
        left: float,
        bottom: float,
        length: float,
        *,
        vertical: bool = False,
        color: str = SEPARATOR,
        linewidth: float = HAIRLINE,
        zorder: int = Z_FIXED_UI_TEXT,
    ) -> None:
        if vertical:
            xs = [self.x(left), self.x(left)]
            ys = [self.up(bottom), self.up(bottom + length)]
        else:
            xs = [self.x(left), self.x(left + length)]
            ys = [self.up(bottom), self.up(bottom)]
        self.ax.plot(
            xs,
            ys,
            transform=self.transform,
            color=color,
            linewidth=linewidth,
            solid_capstyle="butt",
            clip_on=False,
            zorder=zorder,
        )

    def rect(self, left: float, bottom: float, width: float, height: float) -> ScreenRect:
        """Reserved-area rectangle in the (x0, y0, x1, y1) screen convention."""

        return (
            self.x(left),
            self.up(bottom),
            self.x(left + width),
            self.up(bottom + height),
        )


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
    scale: float = 1.0,
) -> DrawingArea:
    """Draw one glyph from the weather set inside a nominal 20x18 point box.

    Every glyph is built from the same three primitives (disc, cloud, stroke)
    at the same optical weight, so a sunny city and a rainy city carry equal
    visual mass in the layout.
    """

    kind = _condition_kind(condition)
    drawing = drawing or DrawingArea(20 * scale, 18 * scale, 0, 0)
    stroke = 1.2 * scale

    def x(value: float) -> float:
        return origin_x + value * scale

    def y(value: float) -> float:
        return origin_y + value * scale

    def add_sun(cx: float = 9.5, cy: float = 9.5, radius: float = 4.0) -> None:
        for angle in range(0, 360, 45):
            radians = np.radians(angle)
            drawing.add_artist(
                Line2D(
                    [x(cx + np.cos(radians) * 5.4), x(cx + np.cos(radians) * 7.0)],
                    [y(cy + np.sin(radians) * 5.4), y(cy + np.sin(radians) * 7.0)],
                    color=ICON_SUN,
                    linewidth=stroke,
                    solid_capstyle="round",
                )
            )
        drawing.add_artist(
            Circle((x(cx), y(cy)), radius * scale, facecolor=ICON_SUN, edgecolor="none")
        )

    def add_cloud(cx: float = 10.0, cy: float = 9.0, size: float = 1.0) -> None:
        body = size * scale
        drawing.add_artist(
            Ellipse(
                (x(cx), y(cy - 1.2 * size)),
                15 * body,
                6.5 * body,
                facecolor=ICON_CLOUD,
                edgecolor="none",
            )
        )
        for offset_x, offset_y, radius in (
            (-4.0, 0.4, 3.4),
            (0.2, 2.0, 4.2),
            (4.1, 0.2, 3.2),
        ):
            drawing.add_artist(
                Circle(
                    (x(cx + offset_x * size), y(cy + offset_y * size)),
                    radius * body,
                    facecolor=ICON_CLOUD,
                    edgecolor="none",
                )
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
                        [x(rain_x), x(rain_x - 1.0)],
                        [y(5.2), y(2.2)],
                        color=ICON_RAIN,
                        linewidth=1.35 * scale,
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
                    facecolor=ICON_SUN,
                    edgecolor="none",
                )
            )
        else:
            for cx in (7, 13):
                for x1, y1, x2, y2 in (
                    (cx - 2, 2.6, cx + 2, 2.6),
                    (cx, 0.6, cx, 4.6),
                    (cx - 1.5, 1.1, cx + 1.5, 4.1),
                    (cx - 1.5, 4.1, cx + 1.5, 1.1),
                ):
                    drawing.add_artist(
                        Line2D(
                            [x(x1), x(x2)],
                            [y(y1), y(y2)],
                            color=ICON_RAIN,
                            linewidth=0.9 * scale,
                            solid_capstyle="round",
                        )
                    )
    elif kind == "fog":
        for fog_y, width in ((12, 13), (8, 17), (4, 12)):
            drawing.add_artist(
                Line2D(
                    [x(10 - width / 2), x(10 + width / 2)],
                    [y(fog_y), y(fog_y)],
                    color=LABEL_TERTIARY,
                    linewidth=1.6 * scale,
                    solid_capstyle="round",
                )
            )
    else:
        add_cloud(10, 9, 0.9)
    return drawing


def _temperature_color(temperature_c: float | None) -> str:
    """Four steps only, so the map never shows a gradient of near-identical reds."""

    if temperature_c is None:
        return LABEL_TERTIARY
    if temperature_c <= 12:
        return COOL
    if temperature_c >= 30:
        return ALERT
    if temperature_c >= 27:
        return WARM
    return LABEL


def _city_card_content(
    key: str,
    label: str,
    temperature: float | None,
    condition: str,
) -> DrawingArea:
    """One capsule: icon, city, temperature — always in the same three columns."""

    temperature_label = f"{temperature:.0f}°" if temperature is not None else "--°"
    drawing = DrawingArea(
        CITY_CARD_WIDTH_POINTS,
        CITY_CARD_HEIGHT_POINTS,
        0,
        0,
    )
    name = Text(
        36.0,
        9.7,
        label,
        color=LABEL,
        fontsize=CITY_NAME_FONT_SIZE,
        fontweight=WEIGHT_BOLD,
        fontfamily=FONT_FAMILY,
        ha="center",
        va="center",
    )
    name.set_path_effects(_text_effects(LABEL, CITY_NAME_FONT_SIZE, bold=True))
    drawing.add_artist(name)

    _weather_icon(
        condition,
        drawing,
        origin_x=4.0,
        origin_y=4.1,
        scale=CITY_ICON_SCALE,
    )

    temperature_color = _temperature_color(temperature)
    value = Text(
        64.5,
        9.5,
        temperature_label,
        color=temperature_color,
        fontsize=CITY_TEMPERATURE_FONT_SIZE,
        fontweight=WEIGHT_BOLD,
        fontfamily=FONT_FAMILY,
        ha="center",
        va="center",
    )
    value.set_path_effects(
        _text_effects(temperature_color, CITY_TEMPERATURE_FONT_SIZE, bold=True)
    )
    drawing.add_artist(value)
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
    """Panel box in reference pixels: (left, bottom, width, height)."""

    visible_count = min(3, max(0, storm_count))
    height = (
        PANEL_HEADER_HEIGHT
        + visible_count * PANEL_ROW_HEIGHT
        + PANEL_FOOTER_HEIGHT
        + PANEL_PADDING
    )
    return COLUMN_LEFT, PANEL_BOTTOM, COLUMN_WIDTH, height


def _label_reserved_boxes(
    ax: plt.Axes,
    typhoon_count: int = 0,
) -> list[ScreenRect]:
    """Screen areas the fixed chrome owns; city capsules must avoid them."""

    chrome = _Chrome(ax)
    boxes = [
        # Timestamp block, top left, plus the sample badge under it.
        chrome.rect(
            MARGIN - 8.0,
            chrome.from_top(STAMP_BLOCK_BOTTOM),
            STAMP_BLOCK_WIDTH,
            STAMP_BLOCK_BOTTOM - 16.0,
        ),
        # Rain legend, the credit line beneath it and the progress line.
        chrome.rect(
            COLUMN_LEFT - 8.0,
            LEGEND_BOTTOM - 8.0,
            COLUMN_WIDTH + 16.0,
            LEGEND_HEIGHT + 16.0,
        ),
        chrome.rect(0.0, 0.0, 420.0, 24.0),
        chrome.rect(0.0, 0.0, CANVAS_WIDTH_PX, 8.0),
    ]
    # The one map label that is not a city.
    label_x, label_y = ccrs.PlateCarree()._as_mpl_transform(ax).transform(
        TAIWAN_LABEL_LONLAT
    )
    boxes.append((label_x - 6.0, label_y - 11.0, label_x + 34.0, label_y + 11.0))
    # Reserve the tallest supported panel even when no storm is active, so the
    # city layout is identical whether or not a storm exists in this GFS run.
    left, bottom, width, height = _typhoon_panel_geometry(3)
    boxes.append(chrome.rect(left - 8.0, bottom - 8.0, width + 16.0, height + 16.0))
    return boxes


def _preferred_label_direction(offset: tuple[int, int]) -> tuple[float, float]:
    horizontal = -1.0 if offset[0] < 0 else 1.0
    if offset[1] >= 12:
        return (horizontal, 1.0)
    if offset[1] <= -12:
        return (horizontal, -1.0)
    return (horizontal, 0.0)


def _city_label_candidates(offset: tuple[int, int]) -> list[LabelCandidate]:
    """Positions for one capsule, nearest first.

    The old ladder walked eight directions at each ring before widening, so a
    collision-free but very distant slot could win over a close one. Here every
    candidate is scored by the capsule's actual centre-to-city distance plus a
    small penalty for leaving the city's preferred side, and the whole pool is
    sorted by that score. The result is that capsules stay next to their dot.
    """

    width = CITY_CARD_WIDTH_POINTS
    height = CITY_CARD_HEIGHT_POINTS
    preferred_x, preferred_y = _preferred_label_direction(offset)
    # The tightest ring sits ~6pt off the dot, close enough that the capsule
    # reads as attached and needs no leader line at all.
    x_gaps = (6.0, 11.0, 17.0, 25.0, 35.0, 47.0, 62.0, 82.0, 106.0, 134.0)
    y_gaps = (0.0, 8.0, 15.0, 24.0, 35.0, 48.0, 64.0, 84.0, 110.0)
    pool: list[tuple[LabelCandidate, float, float]] = []

    for x_direction in (preferred_x, -preferred_x):
        for y_direction in (1.0, -1.0):
            for x_gap in x_gaps:
                for y_gap in y_gaps:
                    x_offset = x_direction * x_gap
                    y_offset = y_direction * y_gap
                    alignment = (1.0, 0.5) if x_offset < 0 else (0.0, 0.5)
                    pool.append(
                        (
                            ((x_offset, y_offset), alignment),
                            x_direction,
                            y_direction if y_gap else 0.0,
                        )
                    )
    # Stacked directly over or under the dot. Without these the only way to sit
    # above a city is a wide diagonal, which wastes the vertical room that the
    # crowded east coast actually has.
    for y_direction in (1.0, -1.0):
        for y_gap in (6.0, 11.0, 17.0, 25.0, 35.0, 47.0, 62.0):
            for x_shift in (0.0, 20.0, -20.0, 38.0, -38.0):
                alignment = (0.5, 0.0) if y_direction > 0 else (0.5, 1.0)
                pool.append(
                    (
                        ((x_shift, y_direction * y_gap), alignment),
                        1.0 if x_shift >= 0 else -1.0,
                        y_direction,
                    )
                )

    ranked: list[tuple[float, LabelCandidate]] = []
    for candidate, x_direction, y_direction in pool:
        (x_offset, y_offset), alignment = candidate
        left = x_offset - alignment[0] * width
        bottom = y_offset - alignment[1] * height
        gap = float(
            np.hypot(
                max(left, 0.0, -(left + width)),
                max(bottom, 0.0, -(bottom + height)),
            )
        )
        # The city table's label_offset is a hint about which side looks best,
        # not a rule; a modest penalty keeps it honoured whenever the room is
        # there without exiling the capsule when it is not.
        penalty = 0.0
        if x_direction != preferred_x:
            penalty += 10.0
        if preferred_y and y_direction and y_direction != preferred_y:
            penalty += 6.0
        ranked.append((gap + penalty, candidate))

    candidates: list[LabelCandidate] = []
    for _, candidate in sorted(ranked, key=lambda item: item[0]):
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


def _anchor_gap(anchor: tuple[float, float], rectangle: ScreenRect) -> float:
    """Shortest distance from a city dot to the edge of its capsule."""

    return float(
        np.hypot(
            max(rectangle[0] - anchor[0], 0.0, anchor[0] - rectangle[2]),
            max(rectangle[1] - anchor[1], 0.0, anchor[1] - rectangle[3]),
        )
    )


def _resolve_city_layout(
    ax: plt.Axes,
    city_weather: dict[str, CityWeather],
    occupied_boxes: list[ScreenRect],
    anchors: dict[str, tuple[float, float]],
) -> tuple[list[CityWeather], dict[str, tuple[tuple[float, float], tuple[float, float], ScreenRect]]]:
    """Decide where every capsule sits, before anything is drawn.

    Placement is greedy and therefore order-dependent: whichever city is
    resolved last has to take what is left, which is how Macau used to end up
    six hundred kilometres inland. So the greedy pass is followed by a few
    improvement rounds — each capsule, worst-placed first, is lifted out and
    re-resolved against everyone else's final position, and kept only if it
    lands closer to its own dot. Both passes depend only on the city table and
    the fixed viewport, so every frame gets the identical layout.
    """

    points_to_pixels = ax.figure.dpi / 72.0
    width = CITY_CARD_WIDTH_POINTS * points_to_pixels
    height = CITY_CARD_HEIGHT_POINTS * points_to_pixels

    def crowding(weather: CityWeather) -> float:
        anchor = anchors[weather.city.key]
        pressure = 0.0
        for other in anchors.values():
            distance = float(np.hypot(other[0] - anchor[0], other[1] - anchor[1]))
            if distance < 200.0:
                # Weighted by nearness, so Macau (three neighbours within one
                # capsule width) outranks Sanya (neighbours, but none touching).
                pressure += 1.0 - distance / 200.0
        return pressure

    ordered_weather = sorted(
        city_weather.values(),
        key=lambda weather: (
            -round(crowding(weather), 6),
            weather.city.key not in PRIMARY_CITY_KEYS,
            -weather.city.longitude,
        ),
    )
    candidates = {
        weather.city.key: _city_label_candidates(weather.city.label_offset)
        for weather in ordered_weather
    }
    placements: dict[
        str, tuple[tuple[float, float], tuple[float, float], ScreenRect]
    ] = {}

    def resolve(weather: CityWeather) -> tuple[
        tuple[float, float], tuple[float, float], ScreenRect, bool
    ]:
        key = weather.city.key
        blocked = list(occupied_boxes)
        blocked.extend(
            placement[2] for other, placement in placements.items() if other != key
        )
        return _select_label_placement(
            ax,
            anchors[key],
            width,
            height,
            candidates[key],
            blocked,
        )

    for weather in ordered_weather:
        offset, alignment, rectangle, collision_free = resolve(weather)
        if not collision_free:
            LOGGER.warning(
                "City label placement required overlap fallback: %s",
                weather.city.label,
            )
        placements[weather.city.key] = (offset, alignment, rectangle)

    for _ in range(3):
        improved = False
        worst_first = sorted(
            ordered_weather,
            key=lambda weather: (
                -_anchor_gap(anchors[weather.city.key], placements[weather.city.key][2]),
                weather.city.key,
            ),
        )
        for weather in worst_first:
            key = weather.city.key
            current_gap = _anchor_gap(anchors[key], placements[key][2])
            offset, alignment, rectangle, collision_free = resolve(weather)
            if collision_free and _anchor_gap(anchors[key], rectangle) < current_gap - 0.5:
                placements[key] = (offset, alignment, rectangle)
                improved = True
        if not improved:
            break

    return ordered_weather, placements


def _draw_city_cards(
    ax: plt.Axes,
    frame: FrameData,
    city_weather: dict[str, CityWeather],
    occupied_boxes: list[ScreenRect],
    anchors: dict[str, tuple[float, float]],
) -> list[ScreenRect]:
    coordinate_transform = ccrs.PlateCarree()._as_mpl_transform(ax)
    ordered_weather, placements = _resolve_city_layout(
        ax,
        city_weather,
        occupied_boxes,
        anchors,
    )
    occupied = list(occupied_boxes)
    estimated_height = CITY_CARD_HEIGHT_POINTS * ax.figure.dpi / 72.0

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
        dot_color = (
            TAIWAN
            if city.key in {"taipei", "taichung", "kaohsiung"}
            else ACCENT
        )

        ax.scatter(
            [city.longitude],
            [city.latitude],
            s=17,
            c=dot_color,
            edgecolors=SURFACE,
            linewidths=1.1,
            transform=ccrs.PlateCarree(),
            zorder=Z_CITY_PRIMARY_POINT if is_primary else Z_CITY_SECONDARY_POINT,
        )

        offset, alignment, rectangle = placements[city.key]
        occupied.append(rectangle)

        # A capsule touching its dot needs no leader; one pushed away by the
        # coastal crowd gets a hairline that is actually visible, unlike the
        # 38%-alpha line the old layout drew under every card.
        #
        # The leader is a separate line rather than the annotation's own arrow
        # because an AnnotationBbox draws its arrow at its own z, so Taipei's
        # leader used to run straight across the Kaohsiung capsule below it.
        # Drawn here it sits under every capsule and simply disappears behind
        # the one it points at.
        anchor = anchors[city.key]
        if _anchor_gap(anchor, rectangle) > CITY_LEADER_MIN_PX:
            leader = ax.plot(
                [anchor[0], (rectangle[0] + rectangle[2]) / 2.0],
                [anchor[1], (rectangle[1] + rectangle[3]) / 2.0],
                transform=IdentityTransform(),
                color=LABEL_TERTIARY,
                linewidth=0.9,
                solid_capstyle="round",
                clip_on=False,
                zorder=Z_CITY_LEADER,
            )[0]
            leader.set_path_effects(
                [
                    path_effects.Stroke(linewidth=2.6, foreground="#FFFFFFCC"),
                    path_effects.Normal(),
                ]
            )

        # An AnnotationBbox draws its frame in display pixels and multiplies
        # the boxstyle by the mutation scale, which it takes from `prop`.
        # Pinning the scale to 1 pt makes rounding_size a plain pixel value,
        # so half the capsule height is a true pill at any dpi.
        annotation = AnnotationBbox(
            card,
            (city.longitude, city.latitude),
            xybox=offset,
            xycoords=coordinate_transform,
            boxcoords="offset points",
            box_alignment=alignment,
            frameon=True,
            pad=0.0,
            fontsize=1.0,
            bboxprops={
                "boxstyle": f"round,pad=0,rounding_size={estimated_height / 2}",
                "mutation_aspect": 1.0,
                "facecolor": CAPSULE_FILL,
                "edgecolor": CARD_HAIRLINE,
                "linewidth": HAIRLINE,
            },
            zorder=Z_CITY_PRIMARY_CARD if is_primary else Z_CITY_SECONDARY_CARD,
        )
        annotation.patch.set_path_effects(_card_shadow(0.09))
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
        markersize=3.6,
        markerfacecolor=SURFACE,
        markeredgecolor=color,
        markeredgewidth=1.1,
        transform=ccrs.PlateCarree(),
        zorder=zorder,
        solid_capstyle="round",
        dash_capstyle="round",
        path_effects=[
            path_effects.Stroke(linewidth=linewidth + 2.4, foreground="#FFFFFFCC"),
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
    """The eye: a soft halo, a solid disc, two arcs and the storm number."""

    transform = ccrs.PlateCarree()
    ax.scatter(
        [point.longitude],
        [point.latitude],
        s=760,
        c=color,
        alpha=0.16,
        edgecolors="none",
        transform=transform,
        zorder=Z_TYPHOON_CORE - 1,
    )
    core = ax.scatter(
        [point.longitude],
        [point.latitude],
        s=320,
        c=color,
        edgecolors=SURFACE,
        linewidths=2.0,
        transform=transform,
        zorder=Z_TYPHOON_CORE,
    )
    core.set_gid(f"typhoon-map-core-{storm_number}")
    for theta1, theta2 in ((24, 160), (204, 340)):
        ax.add_patch(
            Arc(
                (point.longitude, point.latitude),
                width=1.35,
                height=1.35 * 0.82,
                theta1=theta1,
                theta2=theta2,
                color=SURFACE,
                linewidth=1.6,
                transform=transform,
                zorder=Z_TYPHOON_CORE + 1,
            )
        )
    ax.add_patch(
        Circle(
            (point.longitude, point.latitude),
            radius=0.32,
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
        fontsize=TYPE_CAPTION,
        fontweight=WEIGHT_BOLD,
        ha="center",
        va="center",
        zorder=Z_TYPHOON_CORE + 3,
    )
    number.set_path_effects(_text_effects(color, TYPE_CAPTION, bold=True))
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


def _storm_vitals(typhoon: Typhoon, point: StormPoint) -> tuple[str, str]:
    current = typhoon.current or point
    pressure = point.pressure_hpa if point.pressure_hpa is not None else current.pressure_hpa
    wind = point.wind_speed_ms if point.wind_speed_ms is not None else current.wind_speed_ms
    movement_point = point if point.move_direction or point.move_speed_kmh else current

    vitals: list[str] = []
    if pressure is not None:
        vitals.append(f"{pressure:.0f} hPa")
    if wind is not None:
        vitals.append(f"{wind:.0f} m/s")
    vitals_text = "  ·  ".join(vitals) if vitals else "중심 정보 확인 중"

    movement = (
        _move_direction_ko(movement_point.move_direction)
        if movement_point.move_direction
        else "이동 정보 확인 중"
    )
    if movement_point.move_speed_kmh is not None:
        movement = f"{movement}  ·  {movement_point.move_speed_kmh:.0f} km/h"
    return vitals_text, movement


def _draw_typhoon_panel(
    ax: plt.Axes,
    storms: list[tuple[int, Typhoon, StormPoint, str]],
) -> None:
    """One card, one row per storm, the same rhythm as the rest of the chrome."""

    if not storms:
        return

    chrome = _Chrome(ax)
    left, bottom, width, height = _typhoon_panel_geometry(len(storms))
    top = bottom + height
    chrome.card(left, bottom, width, height, gid="typhoon-status-panel")
    chrome.text(
        left + 16.0,
        top - 21.0,
        "태풍 현황",
        size=TYPE_HEADING,
        weight=WEIGHT_BOLD,
        color=LABEL,
    )
    chrome.text(
        left + width - 16.0,
        top - 21.0,
        f"{len(storms)}개 활동 중",
        size=TYPE_CAPTION,
        weight=WEIGHT_BOLD,
        color=ALERT,
        ha="right",
    )

    for row_index, (storm_number, typhoon, point, color) in enumerate(storms):
        row_top = top - PANEL_HEADER_HEIGHT - row_index * PANEL_ROW_HEIGHT
        row_middle = row_top - PANEL_ROW_HEIGHT / 2.0 + 2.0
        row = FancyBboxPatch(
            (chrome.x(left + 8.0), chrome.up(row_top - PANEL_ROW_HEIGHT + 4.0)),
            chrome.s(width - 16.0),
            chrome.s(PANEL_ROW_HEIGHT - 8.0),
            transform=chrome.transform,
            boxstyle=f"round,pad=0,rounding_size={chrome.s(RADIUS_SMALL)}",
            mutation_aspect=1.0,
            facecolor=mcolors.to_rgba(color, 0.07),
            edgecolor="none",
            clip_on=False,
            zorder=Z_FIXED_UI,
        )
        row.set_gid(f"typhoon-panel-row-{storm_number}")
        ax.add_patch(row)

        marker = ax.scatter(
            [chrome.x(left + 26.0)],
            [chrome.up(row_middle)],
            s=150 * chrome.scale ** 2,
            c=color,
            edgecolors="none",
            transform=chrome.transform,
            clip_on=False,
            zorder=Z_FIXED_UI_TEXT,
        )
        marker.set_gid(f"typhoon-panel-marker-{storm_number}")
        chrome.text(
            left + 26.0,
            row_middle,
            str(storm_number),
            size=TYPE_CAPTION,
            weight=WEIGHT_BOLD,
            color=SURFACE,
            ha="center",
            zorder=Z_FIXED_UI_TEXT + 1,
            gid=f"typhoon-panel-number-{storm_number}",
        )

        vitals_text, movement = _storm_vitals(typhoon, point)
        chrome.text(
            left + 44.0,
            row_middle + 9.0,
            _compact_label_value(typhoon.name or "이름 확인 중", 9),
            size=TYPE_BODY,
            weight=WEIGHT_BOLD,
            color=LABEL,
        )
        chrome.text(
            left + width - 16.0,
            row_middle + 9.0,
            _compact_label_value(typhoon.storm_id, 12),
            size=TYPE_MICRO,
            color=LABEL_TERTIARY,
            ha="right",
        )
        chrome.text(
            left + 44.0,
            row_middle - 10.0,
            vitals_text,
            size=TYPE_CAPTION,
            color=LABEL_SECONDARY,
        )
        chrome.text(
            left + width - 16.0,
            row_middle - 10.0,
            movement,
            size=TYPE_CAPTION,
            color=LABEL_TERTIARY,
            ha="right",
        )

    footer_middle = bottom + PANEL_PADDING + PANEL_FOOTER_HEIGHT / 2.0
    chrome.rule(left + 12.0, bottom + PANEL_PADDING + PANEL_FOOTER_HEIGHT, width - 24.0)
    for line_left, style, caption, caption_left in (
        (left + 16.0, (0, (5, 3)), "실황 · 예보", left + 48.0),
        (left + 124.0, (0, (1, 2.4)), "GFS 모델", left + 156.0),
    ):
        ax.plot(
            [chrome.x(line_left), chrome.x(line_left + 24.0)],
            [chrome.up(footer_middle), chrome.up(footer_middle)],
            transform=chrome.transform,
            color=LABEL_TERTIARY,
            linewidth=1.6,
            linestyle=style,
            solid_capstyle="round",
            dash_capstyle="round",
            clip_on=False,
            zorder=Z_FIXED_UI_TEXT,
        )
        chrome.text(
            caption_left,
            footer_middle,
            caption,
            size=TYPE_MICRO,
            color=LABEL_TERTIARY,
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
            linewidth=2.3,
            gid=f"typhoon-track-{storm_number}-history",
            zorder=21,
        )
        _plot_track(
            ax,
            forecast,
            color=storm_color,
            linestyle=(0, (5, 3)),
            linewidth=2.3,
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
            linestyle=(0, (1, 2.4)),
            linewidth=1.8,
            marker="s" if len(model_points) < 14 else None,
            alpha=0.6,
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
    """The legend shows the same eight bands the map uses — no simplification.

    The previous version reduced eight painted bands to three word swatches,
    so a reader could not tell 10 mm from 80 mm. Here the ramp is continuous
    and every band boundary is labelled.
    """

    chrome = _Chrome(ax)
    top = LEGEND_BOTTOM + LEGEND_HEIGHT
    chrome.card(COLUMN_LEFT, LEGEND_BOTTOM, COLUMN_WIDTH, LEGEND_HEIGHT)
    chrome.text(
        COLUMN_LEFT + LEGEND_BAR_INSET,
        top - 18.0,
        "3시간 강수량",
        size=TYPE_BODY,
        weight=WEIGHT_BOLD,
        color=LABEL,
    )
    chrome.text(
        COLUMN_LEFT + COLUMN_WIDTH - LEGEND_BAR_INSET,
        top - 18.0,
        "mm",
        size=TYPE_MICRO,
        color=LABEL_TERTIARY,
        ha="right",
    )

    bar_left = COLUMN_LEFT + LEGEND_BAR_INSET
    bar_width = COLUMN_WIDTH - LEGEND_BAR_INSET * 2
    bar_bottom = top - 32.0 - LEGEND_BAR_HEIGHT
    segment = bar_width / len(PRECIP_COLORS)
    for index, color in enumerate(PRECIP_COLORS):
        ax.add_patch(
            Rectangle(
                (
                    chrome.x(bar_left + index * segment),
                    chrome.up(bar_bottom),
                ),
                chrome.s(segment) + 0.5,
                chrome.s(LEGEND_BAR_HEIGHT),
                transform=chrome.transform,
                facecolor=color,
                edgecolor="none",
                clip_on=False,
                zorder=Z_FIXED_UI_TEXT,
            )
        )
    # Two passes over the same rounded rectangle: the thick surface-colored
    # stroke clips the square band ends into a capsule, the hairline then
    # gives the lightest band an edge it would otherwise lack on white.
    for width, color in ((2.4, CARD_FILL), (HAIRLINE, CARD_HAIRLINE)):
        ax.add_patch(
            FancyBboxPatch(
                (chrome.x(bar_left), chrome.up(bar_bottom)),
                chrome.s(bar_width),
                chrome.s(LEGEND_BAR_HEIGHT),
                transform=chrome.transform,
                boxstyle=f"round,pad=0,rounding_size={chrome.s(LEGEND_BAR_HEIGHT / 2)}",
                mutation_aspect=1.0,
                facecolor="none",
                edgecolor=color,
                linewidth=width,
                clip_on=False,
                zorder=Z_FIXED_UI_TEXT + 1,
            )
        )

    for index, level in enumerate(PRECIP_LEVELS):
        chrome.text(
            bar_left + index * segment,
            bar_bottom - 10.0,
            f"{level:g}",
            size=TYPE_MICRO - 0.4,
            color=LABEL_TERTIARY,
            ha="center",
        )


def _draw_timestamp(
    ax: plt.Axes,
    valid_time_cst: datetime,
    forecast_hour: int,
    *,
    demo: bool,
) -> None:
    """The only thing at the top of the frame: when this frame is valid.

    It carries no card. Bare type on the empty north western land reads
    cleaner at this size than a box would, and a soft halo keeps it legible
    on the rare frame where rain reaches the corner.
    """

    chrome = _Chrome(ax)
    chrome.text(
        MARGIN,
        chrome.from_top(STAMP_DATE_TOP),
        _korean_datetime(valid_time_cst),
        size=TYPE_STAMP,
        weight=WEIGHT_BOLD,
        color=LABEL,
        va="top",
        zorder=Z_HEADER,
        halo=True,
    )
    chrome.text(
        MARGIN + 1.0,
        chrome.from_top(STAMP_OFFSET_TOP),
        _forecast_label(forecast_hour),
        size=TYPE_STAMP_SUB,
        weight=WEIGHT_BOLD,
        color=ACCENT,
        va="top",
        zorder=Z_HEADER,
        halo=True,
    )
    if demo:
        badge = chrome.text(
            MARGIN + 2.0,
            chrome.from_top(STAMP_BADGE_TOP),
            "미리보기",
            size=TYPE_BODY,
            weight=WEIGHT_BOLD,
            color=ACCENT_DEEP,
            va="top",
            zorder=Z_HEADER,
        )
        badge.set_bbox(
            {
                "boxstyle": "round,pad=0.42,rounding_size=0.9",
                "facecolor": CARD_FILL_TINT,
                "edgecolor": CARD_HAIRLINE,
                "linewidth": HAIRLINE,
            }
        )


def _draw_footer(ax: plt.Axes, progress: float) -> None:
    chrome = _Chrome(ax)
    chrome.text(
        MARGIN,
        ATTRIBUTION_BOTTOM,
        "Weather model: NOAA/NCEP GFS  ·  Weather & Typhoon data: QWeather",
        size=TYPE_MICRO - 0.6,
        color=LABEL_TERTIARY,
        halo=True,
    )
    # A full-bleed scrubber reads as elapsed time without adding one more box.
    ax.add_patch(
        Rectangle(
            (0.0, 0.0),
            chrome.width,
            chrome.s(PROGRESS_HEIGHT),
            transform=chrome.transform,
            facecolor="#FFFFFFB3",
            edgecolor="none",
            clip_on=False,
            zorder=Z_FIXED_UI,
        )
    )
    ax.add_patch(
        Rectangle(
            (0.0, 0.0),
            max(chrome.s(2.0), chrome.width * progress),
            chrome.s(PROGRESS_HEIGHT),
            transform=chrome.transform,
            facecolor=ACCENT,
            edgecolor="none",
            clip_on=False,
            zorder=Z_FIXED_UI_TEXT,
        )
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
    return f"{value.month}월 {value.day}일 ({weekdays[value.weekday()]}) {value:%H:%M}"


def _draw_basemap(ax: plt.Axes) -> None:
    """Value, not outline weight, is what separates the subject from the rest.

    Foreign land is one step darker than the sea, China and Taiwan one step
    brighter than anything else. That reads instantly at GIF scale and leaves
    saturated color free for the weather.
    """

    ax.set_facecolor(OCEAN)
    ax.add_feature(cfeature.OCEAN.with_scale("110m"), facecolor=OCEAN, zorder=0)
    ax.add_feature(cfeature.LAND.with_scale("110m"), facecolor=LAND, zorder=1)
    ax.add_feature(
        cfeature.LAKES.with_scale("110m"),
        facecolor=OCEAN,
        edgecolor=COASTLINE,
        linewidth=0.3,
        zorder=3,
    )
    ax.add_feature(
        cfeature.BORDERS.with_scale("110m"),
        edgecolor=BORDERLINE,
        linewidth=0.45,
        zorder=4,
    )
    ax.add_feature(
        cfeature.COASTLINE.with_scale("110m"),
        edgecolor=COASTLINE,
        linewidth=0.45,
        zorder=4,
    )

    china = _china_geometries()
    taiwan = _taiwan_geometries()
    if china:
        ax.add_geometries(
            china,
            crs=ccrs.PlateCarree(),
            facecolor=LAND_SUBJECT,
            edgecolor=SUBJECT_LINE,
            linewidth=1.0,
            zorder=2,
        )
    if taiwan:
        ax.add_geometries(
            taiwan,
            crs=ccrs.PlateCarree(),
            facecolor=LAND_SUBJECT,
            edgecolor=TAIWAN,
            linewidth=1.0,
            zorder=2,
        )

    provinces = _china_province_geometries()
    if provinces:
        ax.add_geometries(
            provinces,
            crs=ccrs.PlateCarree(),
            facecolor="none",
            edgecolor="#DFE4EA",
            linewidth=0.3,
            zorder=3,
        )


def _draw_weather_layers(ax: plt.Axes, frame: FrameData) -> None:
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
        alpha=0.88,
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
            colors=LABEL_SECONDARY,
            linewidths=0.5,
            alpha=0.10,
            transform=ccrs.PlateCarree(),
            zorder=7,
        )

    # Wind is texture, not a readable value here, so it stays below the
    # threshold where it would compete with the rain bands.
    stride = max(1, round(len(frame.longitudes) / 13))
    ax.quiver(
        lon_grid[::stride, ::stride],
        lat_grid[::stride, ::stride],
        frame.u10_ms[::stride, ::stride],
        frame.v10_ms[::stride, ::stride],
        color=LABEL_SECONDARY,
        alpha=0.13,
        width=0.0013,
        headwidth=3.0,
        headlength=3.8,
        headaxislength=3.2,
        scale=500,
        transform=ccrs.PlateCarree(),
        zorder=8,
    )

    china = _china_geometries()
    taiwan = _taiwan_geometries()
    if china:
        ax.add_geometries(
            china,
            crs=ccrs.PlateCarree(),
            facecolor="none",
            edgecolor=SUBJECT_LINE,
            linewidth=1.1,
            zorder=12,
        )
    if taiwan:
        ax.add_geometries(
            taiwan,
            crs=ccrs.PlateCarree(),
            facecolor="none",
            edgecolor=TAIWAN,
            linewidth=1.1,
            zorder=12,
        )
    ax.text(
        TAIWAN_LABEL_LONLAT[0],
        TAIWAN_LABEL_LONLAT[1],
        "대만",
        transform=ccrs.PlateCarree(),
        color=TAIWAN,
        fontsize=TYPE_CAPTION,
        fontweight=WEIGHT_BOLD,
        alpha=0.7,
        ha="left",
        va="center",
        zorder=13,
        path_effects=_halo(2.0),
    )


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
    fig = plt.figure(
        figsize=(CANVAS_WIDTH_PX / 100.0, canvas_height(settings) / 100.0),
        dpi=100,
        facecolor=OCEAN,
    )
    ax = fig.add_axes([0, 0, 1, 1], projection=ccrs.PlateCarree())
    ax.set_extent(settings.bounds, crs=ccrs.PlateCarree())
    # The viewport and canvas ratios differ only slightly. Filling the canvas
    # avoids detached header/footer bands and keeps every label inside the map.
    ax.set_aspect("auto")

    _draw_basemap(ax)
    _draw_weather_layers(ax, frame)

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
    # the same capsule coordinates in every frame, so nothing jumps as a
    # typhoon passes; only the numbered eyes move across the map.
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
    cst = frame.valid_time.astimezone(timezone(timedelta(hours=8)))
    _draw_timestamp(ax, cst, frame.forecast_hour, demo=demo)
    _draw_footer(ax, (frame_index + 1) / frame_count)

    ax.spines["geo"].set_edgecolor("none")

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
        LABEL,
        LABEL_SECONDARY,
        LABEL_TERTIARY,
        ACCENT,
        ACCENT_DEEP,
        ALERT,
        WARM,
        COOL,
        TAIWAN,
        SURFACE,
        OCEAN,
        LAND,
        LAND_SUBJECT,
        COASTLINE,
        BORDERLINE,
        SUBJECT_LINE,
        SEPARATOR,
        CARD_HAIRLINE,
        ICON_CLOUD,
        ICON_SUN,
        *STORM_COLORS,
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
