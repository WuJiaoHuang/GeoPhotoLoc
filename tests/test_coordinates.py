import pytest

from geophotoloc.geometry import LocalCoordinateSystem, horizontal_distance
from geophotoloc.models import GeoPoint


@pytest.mark.parametrize("lat,lon,target_lat,target_lon", [
    (31.23, 121.47, 31.231, 121.472),
    (-33.86, 151.21, -33.861, 151.213),
    (0, 179.999, 0.001, -179.999),
    (80, 10, 80.001, 10.01),
])
def test_round_trip(lat, lon, target_lat, target_lon):
    origin = GeoPoint(latitude=lat, longitude=lon)
    point = GeoPoint(latitude=target_lat, longitude=target_lon)
    system = LocalCoordinateSystem(origin)
    assert system.to_local(origin) == pytest.approx((0, 0), abs=1e-6)
    xy = system.to_local(point)
    restored = system.to_geographic(xy)
    assert restored.latitude == pytest.approx(target_lat, abs=1e-8)
    assert restored.longitude == pytest.approx(target_lon, abs=1e-8)
    assert (xy[0] ** 2 + xy[1] ** 2) ** 0.5 == pytest.approx(
        horizontal_distance(origin, point), abs=1e-5,
    )


def test_distance_and_axis_units():
    origin = GeoPoint(latitude=0, longitude=0)
    east = GeoPoint(latitude=0, longitude=1)
    north = GeoPoint(latitude=1, longitude=0)
    system = LocalCoordinateSystem(origin)
    assert system.to_local(east) == pytest.approx((111319.490793, 0), abs=1e-5)
    assert system.to_local(north) == pytest.approx((0, 110574.388558), abs=1e-5)
    assert horizontal_distance(origin, east) == pytest.approx(111319.490793, abs=1e-5)
    assert horizontal_distance(east, origin) == horizontal_distance(origin, east)
    assert horizontal_distance(origin, origin) == 0


def test_invalid_planar_coordinate():
    with pytest.raises(ValueError):
        LocalCoordinateSystem(GeoPoint(latitude=0, longitude=0)).to_geographic((float("inf"), 0))
