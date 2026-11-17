"""Deterministic bounded grids and obstacle-aware search context."""
import numpy as np
import json
from collections import OrderedDict
from time import perf_counter
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
        self.strtree_queries = 0
        self.visibility_elapsed = 0
        self.projected_entities = {}
        self.system = LocalCoordinateSystem(GeoPoint(latitude=(bounds.south+bounds.north)/2,
                                                      longitude=(bounds.west+bounds.east)/2))
        self.coverage = to_local_geometry(box(bounds.west,bounds.south,bounds.east,bounds.north),self.system)
        self.obstacles = []
        self.obstacle_types = []
        self.obstacle_entities = []
        self.uncertain_areas = []
        self.coverage_confirmed = False
        count = store.connection.execute('SELECT count(*) FROM memberships WHERE region_id=?',(region_id,)).fetchone()[0]
        for row in store.connection.execute('SELECT metadata_json FROM imports WHERE region_id=?',(region_id,)):
            metadata = json.loads(row[0])
            # Only successful full-building imports establish coverage provenance.
            if (metadata.get('source') and metadata.get('fetched_at') and metadata.get('query_sha256')
                    and metadata.get('stored_entities') == count and count > 0
                    and 'out meta geom;' in metadata.get('query','')
                    and '["building"]' in metadata.get('query','') and not metadata.get('warnings')
                    and metadata.get('bounds') == bounds.model_dump()):
                self.coverage_confirmed = True
        for entity in store.list_entities(regions=[region_id]):
            is_building = entity.tags.get('building') not in (None,'no') or entity.tags.get('building:part') not in (None,'no')
            if is_building and (not entity.complete_geometry or entity.geometry_precision != 'complete_outline'):
                raw = shape(entity.geometry) if entity.geometry else None
                # Known partial extent is uncertain; a point-only building has
                # no bounded footprint, so conservatively downgrade the scope.
                uncertain = (to_local_geometry(raw.envelope,self.system) if raw is not None and
                             not raw.is_empty and raw.geom_type != 'Point' else self.coverage)
                self.uncertain_areas.append(uncertain)
            if not entity.complete_geometry or entity.geometry_precision != "complete_outline" or not entity.geometry:
                continue
            raw = shape(entity.geometry)
            if raw.geom_type not in {"Polygon","MultiPolygon"}:
                continue
            is_building = entity.tags.get("building") not in (None,"no") or entity.tags.get("building:part") not in (None,"no")
            is_water = (entity.tags.get("natural") == "water" or entity.tags.get("waterway") in {"riverbank","dock"})
            if is_building or is_water:
                geometry = self.project_entity(entity)
                self.obstacles.append(geometry)
                self.obstacle_types.append("building_interior" if is_building else "water_area")
                self.obstacle_entities.append(entity)
        self.tree = STRtree(self.obstacles)
        self.uncertainty_tree = STRtree(self.uncertain_areas)

    def project_entity(self,entity):
        if entity.id not in self.projected_entities:
            self.projected_entities[entity.id] = to_local_geometry(shape(entity.geometry),self.system) if entity.geometry else None
        return self.projected_entities[entity.id]

    def coverage_status(self, geometry):
        """Import-confirmed scope only; COMPLETE does not imply a perfect OSM map."""
        if not self.coverage_confirmed or geometry.is_empty:
            return 'UNKNOWN'
        if self.coverage.covers(geometry):
            self.strtree_queries += 1
            if len(self.uncertainty_tree.query(geometry,predicate='intersects')):
                return 'PARTIAL'
            return 'COMPLETE'
        return 'PARTIAL' if self.coverage.intersects(geometry) else 'UNKNOWN'

    def filter_reasons(self, point, target_geometries, *, allow_uncovered=False):
        p = Point(point)
        reasons = []
        if not allow_uncovered and not self.coverage.covers(p):
            reasons.append("outside_map_coverage")
        self.strtree_queries += 1
        for index in self.tree.query(p):
            if self.obstacles[index].covers(p):
                reasons.append(self.obstacle_types[index])
        if any(g is not None and g.geom_type in {"Polygon","MultiPolygon"} and g.covers(p) for g in target_geometries):
            reasons.append("overlapping_landmark_outline")
        return sorted(set(reasons))

    def obstacle_union(self, geometry):
        self.strtree_queries += 1
        indexes=self.tree.query(geometry)
        if not getattr(self,'enable_union_cache',False):
            return unary_union([self.obstacles[index] for index in indexes])
        if not hasattr(self,'obstacle_unions'):self.obstacle_unions=OrderedDict()
        key=tuple(sorted(indexes.tolist()))
        started=perf_counter()
        if key not in self.obstacle_unions:
            self.obstacle_union_misses=getattr(self,'obstacle_union_misses',0)+1
            if len(self.obstacle_unions)>=8:self.obstacle_unions.popitem(last=False)
            self.obstacle_unions[key]=unary_union([self.obstacles[index] for index in indexes])
        else:
            self.obstacle_union_hits=getattr(self,'obstacle_union_hits',0)+1
            self.obstacle_unions.move_to_end(key)
        self.obstacle_union_seconds=getattr(self,'obstacle_union_seconds',0)+perf_counter()-started
        return self.obstacle_unions[key]
