"""Local geometry projection, reusing the Stage 1 AEQD coordinate system."""
import numpy as np
from shapely import transform
from geophotoloc.geometry.coordinates import LocalCoordinateSystem


def to_local_geometry(geometry, system: LocalCoordinateSystem):
    return transform(geometry, lambda xy: np.column_stack(system._forward.transform(xy[:,0],xy[:,1],errcheck=True)))


def to_wgs84_geometry(geometry, system: LocalCoordinateSystem):
    return transform(geometry, lambda xy: np.column_stack(system._inverse.transform(xy[:,0],xy[:,1],errcheck=True)))


def angular_span(bearings):
    values = np.sort(np.asarray(bearings) % 360)
    if len(values) <= 1:
        return 0.0
    gaps = np.diff(np.r_[values, values[0] + 360])
    return float(360 - max(gaps))
