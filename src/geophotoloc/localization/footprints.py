"""Exact exterior-vertex angular intervals in north-clockwise convention."""
from dataclasses import dataclass,asdict
from enum import Enum
import numpy as np
from shapely.geometry import Point,Polygon
from geophotoloc.geometry import bearing,signed_angle_difference


@dataclass(frozen=True)
class AngularFootprint:
    center_bearing_deg: float = 0
    left_bound_deg: float = 0
    right_bound_deg: float = 0
    angular_width_deg: float = 0
    distance_m: float = 0
    geometry_quality: str = 'INVALID'
    valid: bool = False

    def to_dict(self):
        return asdict(self)


class OrderStatus(str,Enum):
    SATISFIED='SATISFIED'
    CONFLICT='CONFLICT'
    INDETERMINATE='INDETERMINATE'


def shortest_arc(angles):
    values=np.sort(np.asarray(angles,dtype=float)%360)
    if len(values)==0 or not np.isfinite(values).all():
        raise ValueError('Finite nonempty bearings required')
    gaps=np.diff(np.r_[values,values[0]+360])
    index=int(np.argmax(gaps))
    start=float(values[(index+1)%len(values)])
    width=float(360-gaps[index])
    return start,(start+width)%360,width,(start+width/2)%360


def exterior_vertices(geometry):
    if geometry.geom_type=='Polygon':
        return np.asarray(geometry.exterior.coords)[:,:2]
    if geometry.geom_type=='MultiPolygon':
        return np.concatenate([np.asarray(p.exterior.coords)[:,:2] for p in geometry.geoms])
    return np.empty((0,2))


def angular_footprint(observer_xy, building_geometry, *, complete=True):
    p=Point(observer_xy)
    if not np.isfinite(observer_xy).all() or building_geometry is None or building_geometry.is_empty:
        return AngularFootprint()
    g=building_geometry
    if not g.is_valid:
        return AngularFootprint(geometry_quality='INVALID_GEOMETRY')
    distance=float(g.distance(p))
    if g.geom_type in {'Polygon','MultiPolygon'} and g.covers(p):
        return AngularFootprint(distance_m=0,geometry_quality='OBSERVER_INSIDE_OR_BOUNDARY')
    if not complete or g.geom_type not in {'Polygon','MultiPolygon'}:
        target=g.representative_point()
        if target.distance(p)<1e-8:
            return AngularFootprint(distance_m=0,geometry_quality='COINCIDENT_POINT')
        angle=bearing(observer_xy,(target.x,target.y))
        return AngularFootprint(angle,angle,angle,0,float(target.distance(p)),'POINT_DOWNGRADE',True)
    polygons=[g] if g.geom_type=='Polygon' else list(g.geoms)
    if any(Polygon(poly.exterior).covers(p) for poly in polygons):
        # A courtyard is outside the solid building but the exterior surrounds P.
        return AngularFootprint(180,0,0,360,distance,'COMPLETE_SURROUNDING_HOLE',True)
    vertices=exterior_vertices(g)
    directions=vertices-np.asarray(observer_xy)
    angles=np.degrees(np.arctan2(directions[:,0],directions[:,1]))%360
    left,right,width,center=shortest_arc(angles)
    return AngularFootprint(center,left,right,width,distance,'COMPLETE_OUTLINE',True)


def local_interval(footprint,heading):
    if not footprint.valid or footprint.angular_width_deg>=180:
        return None
    center=signed_angle_difference(heading,footprint.center_bearing_deg)
    half=footprint.angular_width_deg/2
    low,high=center-half,center+half
    if low<=-180 or high>=180:
        return None
    return low,high


def footprint_order(a,b,heading,tolerance_deg=.5):
    if a.geometry_quality!='COMPLETE_OUTLINE' or b.geometry_quality!='COMPLETE_OUTLINE':
        return OrderStatus.INDETERMINATE
    aa,bb=local_interval(a,heading),local_interval(b,heading)
    if aa is None or bb is None:
        return OrderStatus.INDETERMINATE
    if max(aa[1],bb[1])-min(aa[0],bb[0]) >= 180-tolerance_deg:
        return OrderStatus.INDETERMINATE
    if aa[1]<bb[0]-tolerance_deg:
        return OrderStatus.SATISFIED
    if aa[0]>bb[1]+tolerance_deg:
        return OrderStatus.CONFLICT
    return OrderStatus.INDETERMINATE
