from weather_pipeline.config import Settings
from weather_pipeline.qweather import CITIES, QWeatherClient


def test_city_catalog_includes_china_and_taiwan_travel_cities() -> None:
    keys = {city.key for city in CITIES}
    assert len(CITIES) == 22
    assert {"harbin", "dalian", "hangzhou", "xiamen", "sanya", "macau"} <= keys
    assert {"taipei", "taichung", "kaohsiung"} <= keys
    assert all(72 <= city.longitude <= 136 and 17 <= city.latitude <= 55 for city in CITIES)
    assert next(city for city in CITIES if city.key == "dalian").label == "대련"


def test_storm_point_parses_qweather_fields() -> None:
    point = QWeatherClient._storm_point(
        {
            "pubTime": "2026-08-21T08:00+08:00",
            "lat": "21.5",
            "lon": "132.2",
            "type": "TY",
            "pressure": "965",
            "windSpeed": "40",
            "moveSpeed": "18",
            "moveDir": "NW",
        },
        "pubTime",
    )
    assert point is not None
    assert point.longitude == 132.2
    assert point.latitude == 21.5
    assert point.pressure_hpa == 965
    assert point.move_direction == "NW"


def test_storm_point_rejects_missing_coordinates() -> None:
    assert QWeatherClient._storm_point({"time": "2026-08-21T00:00Z"}, "time") is None


def test_modern_city_response_is_normalized(monkeypatch, tmp_path) -> None:
    client = QWeatherClient(
        Settings(
            qweather_api_host="https://example.qweatherapi.com",
            qweather_api_key="test-key",
            work_dir=tmp_path,
        )
    )

    def fake_get(path, params, cache_seconds):
        del params, cache_seconds
        if "/current/" in path:
            return {
                "condition": {"text": "Cloudy"},
                "temperature": {"value": 27.4},
                "wind": {"speed": {"value": 3.2}},
            }
        return {
            "hours": [
                {
                    "forecastTime": "2026-08-21T03:00:00Z",
                    "condition": {"text": "Rain"},
                    "temperature": {"value": 24.8},
                    "wind": {"speed": {"value": 5.1}},
                }
            ]
        }

    monkeypatch.setattr(client, "_get", fake_get)
    weather = client._fetch_city_modern(CITIES[0])
    assert weather.current is not None
    assert weather.current.temperature_c == 27.4
    assert weather.hourly[0].condition == "Rain"
    assert weather.hourly[0].wind_speed_ms == 5.1
