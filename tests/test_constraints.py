from math import cos, radians, sin

import pytest

from geophotoloc.geometry import check_left_right


def ray(angle, distance=10):
    return (distance * sin(radians(angle)), distance * cos(radians(angle)))


@pytest.mark.parametrize("heading", [0, 30, 90, 180, 270, 355])
def test_order_in_common_view(heading):
    a, b = ray(heading - 20, 10), ray(heading + 20, 30)
    result = check_left_right((0, 0), a, b, "LEFT_OF")
    assert result.satisfied is True
    assert result.reason == "determinate"
    assert result.signed_separation_deg == pytest.approx(40)
    assert result.view_heading_deg == pytest.approx(heading)
    assert result.projected_x_a == pytest.approx(-0.3639702343)
    assert result.projected_x_b == pytest.approx(0.3639702343)
    assert check_left_right((0, 0), a, b, "RIGHT_OF").satisfied is False
    swapped = check_left_right((0, 0), b, a, "LEFT_OF")
    assert swapped.satisfied is False
    assert swapped.signed_separation_deg == pytest.approx(-40)
    assert check_left_right((0, 0), b, a, "RIGHT_OF").satisfied is True


def test_map_east_is_not_always_image_right():
    # Looking south, the geographically eastern landmark appears on the left.
    assert check_left_right((0, 0), (1, -10), (-1, -10), "LEFT_OF").satisfied is True


def test_position_not_unique_and_translation_invariant():
    for p in [(0, 0), (0, -10), (1, 0)]:
        assert check_left_right(p, (-2, 10), (2, 10), "LEFT_OF").satisfied is True
    result = check_left_right((100, 200), (98, 210), (102, 210), "LEFT_OF")
    assert result.satisfied is True


@pytest.mark.parametrize("a,b,reason", [
    ((0, 0), (1, 1), "observer_on_landmark"),
    ((1, 1), (0, 0), "observer_on_landmark"),
    ((1e-8, 0), (1, 1), "observer_on_landmark"),
    ((1, 1), (1, 1), "coincident_landmarks"),
    ((0, 1), (0, 2), "same_direction"),
    (ray(0), ray(0.05), "same_direction"),
    ((0, 1), (0, -1), "opposite_directions"),
    (ray(0), ray(179.95), "opposite_directions"),
    (ray(0), ray(180.05), "opposite_directions"),
])
def test_degenerate(a, b, reason):
    result = check_left_right((0, 0), a, b, "LEFT_OF")
    assert result.satisfied is None
    assert result.reason == reason
    assert result.projected_x_a is None


@pytest.mark.parametrize("relation", ["ABOVE", "INVALID"])
def test_invalid_relation(relation):
    with pytest.raises(ValueError):
        check_left_right((0, 0), (-1, 10), (1, 10), relation)


def test_nonfinite_input():
    with pytest.raises(ValueError):
        check_left_right((0, 0), (float("nan"), 1), (1, 1), "LEFT_OF")
