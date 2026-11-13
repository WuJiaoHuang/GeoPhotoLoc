"""Clockwise bearings: north=0°, east=90°, south=180°, west=270°."""

from math import atan2, degrees, isfinite

from .coordinates import PlanarPoint, validate_planar


def bearing(observer: PlanarPoint, landmark: PlanarPoint) -> float:
    """Return observer → landmark bearing in [0, 360); coincidence is invalid."""
    px, py = validate_planar(observer)
    ax, ay = validate_planar(landmark)
    dx, dy = ax - px, ay - py
    if not isfinite(dx) or not isfinite(dy):
        raise ValueError("Coordinate differences must be finite")
    if dx == 0 and dy == 0:
        raise ValueError("Coincident points have no bearing")
    return degrees(atan2(dx, dy)) % 360


def signed_angle_difference(from_angle: float, to_angle: float) -> float:
    """Smallest rotation from first to second, in [-180, 180) degrees.

    Positive means clockwise (towards image right in a common forward view);
    negative means counterclockwise. Exact opposition is represented by -180°
    and must not be interpreted as a definite left/right relation.
    """
    if not isfinite(from_angle) or not isfinite(to_angle):
        raise ValueError("Angles must be finite")
    return ((to_angle % 360) - (from_angle % 360) + 180) % 360 - 180
