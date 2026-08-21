from datetime import datetime, timezone

from weather_pipeline.config import Settings
from weather_pipeline.gfs import candidate_runs, filter_request, gfs_index_url


def test_candidate_runs_rolls_back_to_previous_cycle() -> None:
    now = datetime(2026, 8, 21, 2, 15, tzinfo=timezone.utc)
    assert candidate_runs(now, count=3) == [
        "2026082100",
        "2026082018",
        "2026082012",
    ]


def test_filter_request_only_selects_required_fields_and_bounds() -> None:
    settings = Settings(noaa_base_url="https://nomads.example")
    url, params = filter_request(settings, "2026082100", 168)
    assert url.endswith("/cgi-bin/filter_gfs_0p25.pl")
    assert params["file"] == "gfs.t00z.pgrb2.0p25.f168"
    assert params["leftlon"] == "72"
    assert params["rightlon"] == "136"
    assert params["bottomlat"] == "17"
    assert params["toplat"] == "55"
    assert {key for key in params if key.startswith("var_")} == {
        "var_APCP",
        "var_PRMSL",
        "var_UGRD",
        "var_VGRD",
    }


def test_index_url_checks_the_last_required_frame() -> None:
    settings = Settings(noaa_base_url="https://nomads.example")
    assert gfs_index_url(settings, "2026082112", 168).endswith(
        "/gfs.20260821/12/atmos/gfs.t12z.pgrb2.0p25.f168.idx"
    )
