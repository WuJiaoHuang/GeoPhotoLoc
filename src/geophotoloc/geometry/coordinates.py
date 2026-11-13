"""WGS84 degrees ↔ local azimuthal equidistant (AEQD) metres.

Public geographic values are GeoPoint(latitude, longitude). PyProj transformers
always use longitude first (always_xy=True); planar tuples are (east, north).
Reuse one local system for every point in a scene, with origin near the scene.
AEQD is a local approximation, not a global Cartesian map. No altitude is used.
"""

from math import isfinite

from pyproj import CRS, Geod, Transformer

from geophotoloc.models import GeoPoint

PlanarPoint = tuple[float, float]
_GEOD = Geod(ellps="WGS84")


def validate_planar(point: PlanarPoint) -> PlanarPoint:
    if len(point) != 2 or not all(isfinite(value) for value in point):
        raise ValueError("A planar point must contain two finite coordinates")
    return float(point[0]), float(point[1])


class LocalCoordinateSystem:
    """A reusable projection centred on a WGS84 origin."""

    def __init__(self, origin: GeoPoint):
        self.origin = origin.model_copy(deep=True)
        local = CRS.from_proj4(
            f"+proj=aeqd +lat_0={origin.latitude} +lon_0={origin.longitude} "
            "+datum=WGS84 +units=m +no_defs"
        )
        self._forward = Transformer.from_crs("EPSG:4326", local, always_xy=True)
        self._inverse = Transformer.from_crs(local, "EPSG:4326", always_xy=True)

    def to_local(self, point: GeoPoint) -> PlanarPoint:
        return validate_planar(self._forward.transform(
            point.longitude, point.latitude, errcheck=True,
        ))

    def to_geographic(self, point: PlanarPoint) -> GeoPoint:
        x, y = validate_planar(point)
        longitude, latitude = self._inverse.transform(x, y, errcheck=True)
        return GeoPoint(latitude=latitude, longitude=longitude)


def horizontal_distance(a: GeoPoint, b: GeoPoint) -> float:
    """Ellipsoidal WGS84 surface distance in metres, ignoring altitude."""
    _, _, distance = _GEOD.inv(a.longitude, a.latitude, b.longitude, b.latitude)
    return float(distance)
