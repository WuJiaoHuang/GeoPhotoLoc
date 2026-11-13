"""Left/right compatibility in a shared local forward camera view.

Both landmarks are projected onto a virtual camera with heading at the minor
arc bisector. Its right/forward coordinates give normalized horizontal image
positions x=right/forward (unit focal length). This assumes an upright camera
and a forward field of view below 180°. No actual camera heading/FOV is known;
the result is an order compatibility check, not a unique position or visibility
proof. All inputs must use the same local metric coordinate system.
"""

from dataclasses import dataclass
from math import isfinite

import numpy as np

from geophotoloc.config import GeometryConfig
from geophotoloc.models import RelationType

from .bearing import bearing, signed_angle_difference
from .coordinates import PlanarPoint, validate_planar


@dataclass(frozen=True)
class ConstraintResult:
    satisfied: bool | None
    reason: str
    bearing_a_deg: float | None = None
    bearing_b_deg: float | None = None
    signed_separation_deg: float | None = None
    view_heading_deg: float | None = None
    projected_x_a: float | None = None
    projected_x_b: float | None = None


def check_left_right(
    observer: PlanarPoint,
    landmark_a: PlanarPoint,
    landmark_b: PlanarPoint,
    relation: RelationType | str,
    config: GeometryConfig | None = None,
) -> ConstraintResult:
    """Check whether A is LEFT_OF/RIGHT_OF B; None means indeterminate.

    Degenerate: observer on a landmark, coincident landmarks, almost identical
    rays, or nearly opposite rays. Defaults: 1e-6 m and 0.1° tolerances.
    Unsupported relations and nonfinite inputs raise ValueError.
    """
    relation = RelationType(relation)
    if relation not in (RelationType.LEFT_OF, RelationType.RIGHT_OF):
        raise ValueError("Only LEFT_OF and RIGHT_OF are supported")
    config = config or GeometryConfig()
    p, a, b = [np.asarray(validate_planar(point))
               for point in (observer, landmark_a, landmark_b)]
    with np.errstate(over="ignore", invalid="ignore"):
        va, vb, ab = a - p, b - p, a - b
    if not all(np.isfinite(vector).all() for vector in (va, vb, ab)):
        raise ValueError("Coordinate differences must be finite")
    distances = [float(np.hypot(*vector)) for vector in (va, vb, ab)]
    if not all(isfinite(distance) for distance in distances):
        raise ValueError("Distances must be finite")
    if min(distances[:2]) <= config.distance_tolerance_m:
        return ConstraintResult(None, "observer_on_landmark")
    if distances[2] <= config.distance_tolerance_m:
        return ConstraintResult(None, "coincident_landmarks")
    ba, bb = bearing(observer, landmark_a), bearing(observer, landmark_b)
    delta = signed_angle_difference(ba, bb)
    info = dict(bearing_a_deg=ba, bearing_b_deg=bb, signed_separation_deg=delta)
    if abs(delta) <= config.angular_tolerance_deg:
        return ConstraintResult(None, "same_direction", **info)
    if 180 - abs(delta) <= config.angular_tolerance_deg:
        return ConstraintResult(None, "opposite_directions", **info)
    heading = (ba + delta / 2) % 360
    radians = np.deg2rad(heading)
    forward = np.array([np.sin(radians), np.cos(radians)])
    right = np.array([np.cos(radians), -np.sin(radians)])
    xa = float(np.dot(va, right) / np.dot(va, forward))
    xb = float(np.dot(vb, right) / np.dot(vb, forward))
    satisfied = xa < xb if relation == RelationType.LEFT_OF else xa > xb
    return ConstraintResult(
        bool(satisfied), "determinate", **info, view_heading_deg=heading,
        projected_x_a=xa, projected_x_b=xb,
    )
