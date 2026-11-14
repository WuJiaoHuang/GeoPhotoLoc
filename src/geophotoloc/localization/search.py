"""Deterministic bounded grids and obstacle-aware search context."""
import numpy as np
from shapely.geometry import Point, box, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree
from geophotoloc.geometry.coordinates import LocalCoordinateSystem
from geophotoloc.models import GeoPoint
from .projection import to_local_geometry


def grid(geometry, spacing):
    west,south,east,north = geometry.bounds
    for y in np.arange(np.ceil(south/spacing)*spacing,north+1e-7,spacing):
        for x in np.arange(np.ceil(west/spacing)*spacing,east+1e-7,spacing):
            point = Point(float(x),float(y))
            if geometry.covers(point):
                yield (float(x),float(y))


class SearchContext:
    def __init__(self, store, region_id, bounds):
        self.system = LocalCoordinateSystem(GeoPoint(latitude=(bounds.south+bounds.north)/2,
                                                      longitude=(bounds.west+bounds.east)/2))
        self.coverage = to_local_geometry(box(bounds.west,bounds.south,bounds.east,bounds.north),self.system)
        self.obstacles = []
        self.obstacle_types = []
        for entity in store.list_entities(regions=[region_id]):
            if not entity.complete_geometry or entity.geometry_precision != "complete_outline" or not entity.geometry:
                continue
            raw = shape(entity.geometry)
            if raw.geom_type not in {"Polygon","MultiPolygon"}:
                continue
            is_building = entity.tags.get("building") not in (None,"no") or entity.tags.get("building:part") not in (None,"no")
            is_water = (entity.tags.get("natural") == "water" or entity.tags.get("waterway") in {"riverbank","dock"})
            if is_building or is_water:
                geometry = to_local_geometry(raw,self.system)
                self.obstacles.append(geometry)
                self.obstacle_types.append("building_interior" if is_building else "water_area")
        self.tree = STRtree(self.obstacles)

    def filter_reasons(self, point, target_geometries):
        p = Point(point)
        reasons = []
        if not self.coverage.covers(p):
            reasons.append("outside_map_coverage")
        for index in self.tree.query(p):
            if self.obstacles[index].covers(p):
                reasons.append(self.obstacle_types[index])
        if any(g is not None and g.geom_type in {"Polygon","MultiPolygon"} and g.covers(p) for g in target_geometries):
            reasons.append("overlapping_landmark_outline")
        return sorted(set(reasons))

    def obstacle_union(self, geometry):
        return unary_union([self.obstacles[index] for index in self.tree.query(geometry)])
