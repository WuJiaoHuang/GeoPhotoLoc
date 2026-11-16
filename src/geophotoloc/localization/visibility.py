"""Potential 2D obstruction only: never proves real 3D invisibility."""
from dataclasses import dataclass,asdict
from types import SimpleNamespace
from collections import OrderedDict
from time import perf_counter
import numpy as np
from shapely import get_coordinates
from shapely.geometry import Point,LineString
from shapely.ops import nearest_points
from geophotoloc.geometry import bearing,signed_angle_difference
from geophotoloc.maps.matching import same_physical_entity
from .footprints import angular_footprint,exterior_vertices


@dataclass(frozen=True)
class VisibilityResult:
    visibility_status: str = 'UNKNOWN'
    valid_rays: int = 0
    blocked_rays: int = 0
    blocked_ratio: float | None = None
    complete_ray_fraction: float = 0
    fully_blocked_2d: bool = False
    quality: float = .5
    reason: str = 'insufficient_geometry_or_map_coverage'

    def to_dict(self):
        return asdict(self)


def boundary_rays(observer_xy,target_geometry,max_rays=12):
    if not 1<=max_rays<=12:
        raise ValueError('Visibility rays must be bounded to 1..12')
    angular=angular_footprint(observer_xy,target_geometry)
    if not angular.valid or angular.geometry_quality!='COMPLETE_OUTLINE':
        return []
    p=Point(observer_xy)
    vertices=exterior_vertices(target_geometry)
    vectors=vertices-np.asarray(observer_xy)
    directions=np.degrees(np.arctan2(vectors[:,0],vectors[:,1]))%360
    angles=(directions-angular.center_bearing_deg+180)%360-180
    boundary=target_geometry.boundary
    nearest=nearest_points(p,boundary)[1]
    samples=[(nearest.x,nearest.y),tuple(vertices[int(np.argmin(angles))]),tuple(vertices[int(np.argmax(angles))])]
    for fraction in np.linspace(0,1,max_rays*2,endpoint=False):
        sample=boundary.interpolate(float(fraction),normalized=True)
        samples.append((sample.x,sample.y))
    rays,seen=[],[]
    for xy in samples:
        angle=bearing(observer_xy,xy)
        if any(abs(signed_angle_difference(old,angle))<.05 for old in seen):
            continue
        vector=np.asarray(xy)-np.asarray(observer_xy)
        length=float(np.hypot(*vector))
        if length<1e-7:
            continue
        line=LineString([observer_xy,xy])
        intersections=get_coordinates(line.intersection(boundary))
        along=[float(np.dot(v-np.asarray(observer_xy),vector/length)) for v in intersections]
        positive=[value for value in along if value>1e-7]
        if not positive:
            continue
        end=np.asarray(observer_xy)+(vector/length)*min(positive)
        rays.append(LineString([observer_xy,tuple(end)]));seen.append(angle)
        if len(rays)>=max_rays:
            break
    return rays


def potential_visibility(observer_xy,target_geometry,context,*,target_entity=None,excluded_entity_ids=(),max_rays=12):
    rays=boundary_rays(observer_xy,target_geometry,max_rays)
    if not rays:
        return VisibilityResult()
    blocked,complete=0,0
    p=Point(observer_xy)
    if not hasattr(context,'visibility_identity_cache'):
        context.visibility_identity_cache={}
    for ray in rays:
        complete += context.coverage_status(ray)=='COMPLETE'
        obstructed=False
        # GEOS applies the exact predicate inside the index query, avoiding
        # Python intersections for every building in a long ray's bbox.
        context.strtree_queries=getattr(context,'strtree_queries',0)+1
        for index in context.tree.query(ray,predicate='intersects'):
            if context.obstacle_types[index]!='building_interior':
                continue
            obstacle=context.obstacles[index]
            entity=context.obstacle_entities[index]
            duplicate=False
            if target_entity is not None:
                key=(target_entity.id,entity.id)
                if key not in context.visibility_identity_cache:
                    context.visibility_identity_cache[key]=same_physical_entity(SimpleNamespace(entity=entity),SimpleNamespace(entity=target_entity))
                duplicate=context.visibility_identity_cache[key]
            if entity.id in excluded_entity_ids or duplicate:
                continue
            if obstacle.equals(target_geometry):
                continue
            crossing=ray.intersection(obstacle)
            if not crossing.is_empty and crossing.distance(p)<ray.length-1e-6:
                obstructed=True
                break
        blocked += obstructed
    ratio=blocked/len(rays)
    known=complete==len(rays)
    # UNKNOWN is no better than the worst known 2D obstruction, never CLEAR.
    return VisibilityResult('CLEAR' if known and not blocked else 'POTENTIALLY_OCCLUDED' if known else 'UNKNOWN',
                            len(rays),blocked,ratio,complete/len(rays),blocked==len(rays),
                            1-.5*ratio if known else .5,
                            'two_dimensional_only_height_and_pitch_unknown' if known else 'ray_corridor_not_fully_covered')


def cached_visibility(observer_xy,target_geometry,context,*,target_entity=None,max_rays=12,cache_size=2048):
    """Bounded context-local LRU, keyed by exact sample position and entity."""
    if not hasattr(context,'visibility_results'):
        context.visibility_results=OrderedDict()
    key=(tuple(observer_xy),target_entity.id if target_entity else None,
         target_geometry.wkb if target_geometry is not None else None,max_rays)
    if key in context.visibility_results:
        context.visibility_cache_hits=getattr(context,'visibility_cache_hits',0)+1
        context.visibility_results.move_to_end(key)
        return context.visibility_results[key]
    result=potential_visibility(observer_xy,target_geometry,context,target_entity=target_entity,max_rays=max_rays)
    context.visibility_cache_misses=getattr(context,'visibility_cache_misses',0)+1
    context.visibility_results[key]=result
    while len(context.visibility_results)>cache_size:
        context.visibility_results.popitem(last=False)
    return result
