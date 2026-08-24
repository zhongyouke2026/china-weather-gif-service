import cartopy.crs as ccrs
import matplotlib.pyplot as plt
from datetime import timedelta

from weather_pipeline.config import Settings
from weather_pipeline.demo import build_demo_data
from weather_pipeline.model_track import derive_all_model_tracks
from weather_pipeline.models import StormPoint, Typhoon
from weather_pipeline.render import (
    CANVAS_HEIGHT_PX,
    CANVAS_WIDTH_PX,
    CITY_CARD_HEIGHT_POINTS,
    CITY_CARD_WIDTH_POINTS,
    CITY_NAME_FONT_SIZE,
    STORM_COLORS,
    _city_label_anchors,
    _city_card_content,
    _draw_city_cards,
    _draw_typhoons,
    _label_reserved_boxes,
    _rectangles_overlap,
)


def test_city_labels_and_typhoon_panel_stay_fixed() -> None:
    frames, city_weather, typhoons = build_demo_data()
    model_tracks = derive_all_model_tracks(frames, typhoons)
    settings = Settings()
    reference_city_rectangles = None
    reference_rendered_card_sizes = None
    reference_panel_rectangle = None

    for frame_index, frame in enumerate(frames):
        figure = plt.figure(figsize=(CANVAS_WIDTH_PX / 100, CANVAS_HEIGHT_PX / 100), dpi=100)
        axis = figure.add_axes([0, 0, 1, 1], projection=ccrs.PlateCarree())
        axis.set_extent(settings.bounds, crs=ccrs.PlateCarree())
        axis.set_aspect("auto")

        anchors = _city_label_anchors(axis, city_weather)
        occupied = _label_reserved_boxes(axis, typhoon_count=1)
        panel_rectangle = occupied[-1]
        if reference_panel_rectangle is None:
            reference_panel_rectangle = panel_rectangle
        else:
            assert panel_rectangle == reference_panel_rectangle
        occupied.extend(
            (
                anchor[0] - 5.0,
                anchor[1] - 5.0,
                anchor[0] + 5.0,
                anchor[1] + 5.0,
            )
            for anchor in anchors.values()
        )
        city_start = len(occupied)
        city_occupied = _draw_city_cards(
            axis,
            frame,
            city_weather,
            occupied,
            anchors,
        )
        city_rectangles = city_occupied[city_start:]

        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        city_artists = list(axis.artists)[-len(city_weather) :]
        rendered_card_sizes = [
            (
                round(artist.patch.get_window_extent(renderer).width, 3),
                round(artist.patch.get_window_extent(renderer).height, 3),
            )
            for artist in city_artists
        ]
        assert len(set(rendered_card_sizes)) == 1

        if reference_city_rectangles is None:
            reference_city_rectangles = city_rectangles
            reference_rendered_card_sizes = rendered_card_sizes
        else:
            assert city_rectangles == reference_city_rectangles
            assert rendered_card_sizes == reference_rendered_card_sizes

        assert len(city_rectangles) == len(city_weather)
        for index, rectangle in enumerate(city_rectangles):
            assert rectangle[0] >= 6.0
            assert rectangle[1] >= 6.0
            assert rectangle[2] <= CANVAS_WIDTH_PX - 6.0
            assert rectangle[3] <= CANVAS_HEIGHT_PX - 6.0
            assert not any(
                _rectangles_overlap(rectangle, other)
                for other in city_occupied[:city_start]
            )
            assert not any(
                _rectangles_overlap(rectangle, other)
                for other in city_rectangles[index + 1 :]
            )

        with_typhoon = _draw_typhoons(
            axis,
            frame_index,
            frame,
            typhoons,
            model_tracks,
            city_occupied,
        )
        assert with_typhoon == city_occupied
        assert len(axis.artists) == len(city_weather)
        assert any(
            patch.get_gid() == "typhoon-status-panel" for patch in axis.patches
        )
        text_gids = {text.get_gid() for text in axis.texts}
        assert "typhoon-map-number-1" in text_gids
        assert "typhoon-panel-number-1" in text_gids

        plt.close(figure)


def test_two_typhoons_use_matching_numbers_and_colors_without_leader_cards() -> None:
    frames, city_weather, typhoons = build_demo_data()
    frame = frames[0]
    start = frame.valid_time
    second = Typhoon(
        storm_id="NP_DEMO02",
        name="NARI",
        is_active=True,
        current=StormPoint(
            time=start,
            longitude=133.0,
            latitude=31.0,
            pressure_hpa=985,
            wind_speed_ms=27,
            move_speed_kmh=15,
            move_direction="WNW",
        ),
        forecast=[
            StormPoint(
                time=start + timedelta(hours=6 * step),
                longitude=133.0 - step * 1.45,
                latitude=31.0 + step * 0.38,
                pressure_hpa=985 + step,
                wind_speed_ms=27 - step * 0.8,
                move_speed_kmh=15,
                move_direction="WNW",
            )
            for step in range(5)
        ],
    )
    typhoons.append(second)
    typhoons.append(
        Typhoon(
            storm_id="NP_INACTIVE",
            name="OLD",
            is_active=False,
            current=StormPoint(
                time=start,
                longitude=120.0,
                latitude=20.0,
            ),
        )
    )

    figure = plt.figure(figsize=(CANVAS_WIDTH_PX / 100, CANVAS_HEIGHT_PX / 100), dpi=100)
    axis = figure.add_axes([0, 0, 1, 1], projection=ccrs.PlateCarree())
    settings = Settings()
    axis.set_extent(settings.bounds, crs=ccrs.PlateCarree())
    axis.set_aspect("auto")

    anchors = _city_label_anchors(axis, city_weather)
    occupied = _label_reserved_boxes(axis, typhoon_count=2)
    occupied.extend(
        (anchor[0] - 5.0, anchor[1] - 5.0, anchor[0] + 5.0, anchor[1] + 5.0)
        for anchor in anchors.values()
    )
    city_occupied = _draw_city_cards(axis, frame, city_weather, occupied, anchors)
    city_artist_count = len(axis.artists)
    _draw_typhoons(axis, 0, frame, typhoons, {}, city_occupied)

    assert len(axis.artists) == city_artist_count
    text_gids = {text.get_gid() for text in axis.texts}
    assert {
        "typhoon-map-number-1",
        "typhoon-map-number-2",
        "typhoon-panel-number-1",
        "typhoon-panel-number-2",
    }.issubset(text_gids)
    assert "typhoon-map-number-3" not in text_gids
    assert "typhoon-panel-number-3" not in text_gids

    collections_by_gid = {
        collection.get_gid(): collection for collection in axis.collections
    }
    for storm_number, expected_color in enumerate(STORM_COLORS[:2], start=1):
        map_core = collections_by_gid[f"typhoon-map-core-{storm_number}"]
        panel_marker = collections_by_gid[f"typhoon-panel-marker-{storm_number}"]
        assert map_core.get_facecolor()[0][:3].tolist() == panel_marker.get_facecolor()[0][:3].tolist()

        provided_track = next(
            line
            for line in axis.lines
            if line.get_gid() == f"typhoon-track-{storm_number}-provided"
        )
        assert provided_track.get_color().lower() == expected_color.lower()

    plt.close(figure)


def test_city_layout_reservation_does_not_change_with_typhoon_count() -> None:
    frames, city_weather, _ = build_demo_data()
    settings = Settings()
    frame = frames[0]
    layouts = []

    for typhoon_count in (0, 1, 2, 3):
        figure = plt.figure(figsize=(CANVAS_WIDTH_PX / 100, CANVAS_HEIGHT_PX / 100), dpi=100)
        axis = figure.add_axes([0, 0, 1, 1], projection=ccrs.PlateCarree())
        axis.set_extent(settings.bounds, crs=ccrs.PlateCarree())
        axis.set_aspect("auto")
        anchors = _city_label_anchors(axis, city_weather)
        occupied = _label_reserved_boxes(axis, typhoon_count=typhoon_count)
        occupied.extend(
            (
                anchor[0] - 5.0,
                anchor[1] - 5.0,
                anchor[0] + 5.0,
                anchor[1] + 5.0,
            )
            for anchor in anchors.values()
        )
        city_start = len(occupied)
        city_occupied = _draw_city_cards(
            axis,
            frame,
            city_weather,
            occupied,
            anchors,
        )
        layouts.append(city_occupied[city_start:])
        plt.close(figure)

    assert layouts[1:] == [layouts[0], layouts[0], layouts[0]]


def test_every_city_uses_the_same_card_size_and_has_a_weather_icon() -> None:
    frames, city_weather, _ = build_demo_data()
    frame = frames[0]

    for weather in city_weather.values():
        point = weather.at(frame.valid_time)
        card = _city_card_content(
            weather.city.key,
            weather.city.label,
            point.temperature_c if point else None,
            point.condition if point else "",
        )
        assert card.width == CITY_CARD_WIDTH_POINTS
        assert card.height == CITY_CARD_HEIGHT_POINTS
        # Two Text artists plus at least one shape/line from the full icon.
        children = card.get_children()
        assert len(children) >= 3
        city_name = children[0]
        temperature = children[-1]
        assert city_name.get_ha() == "center"
        assert temperature.get_ha() == "center"
        assert city_name.get_fontsize() == CITY_NAME_FONT_SIZE
        assert city_name.get_fontweight() == "bold"
