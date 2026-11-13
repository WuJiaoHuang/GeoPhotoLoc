import pytest

from geophotoloc.geometry import bearing, signed_angle_difference


@pytest.mark.parametrize("point,expected", [
    ((0, 1), 0), ((1, 0), 90), ((0, -1), 180), ((-1, 0), 270),
    ((1, 1), 45), ((-1, 1), 315),
])
def test_cardinal_bearings(point, expected):
    assert bearing((0, 0), point) == pytest.approx(expected)


def test_bearing_translation():
    assert bearing((100, 200), (101, 201)) == pytest.approx(45)


@pytest.mark.parametrize("start,end,expected", [
    (350, 10, 20), (10, 350, -20), (0, 360, 0), (360, 0, 0),
    (0, 180, -180), (180, 0, -180), (-10, 370, 20), (90, 180, 90),
])
def test_signed_difference(start, end, expected):
    assert signed_angle_difference(start, end) == pytest.approx(expected)


@pytest.mark.parametrize("point", [(0, 0), (float("nan"), 1), (float("inf"), 0)])
def test_invalid_bearing(point):
    with pytest.raises(ValueError):
        bearing((0, 0), point)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_angle(value):
    with pytest.raises(ValueError):
        signed_angle_difference(0, value)
