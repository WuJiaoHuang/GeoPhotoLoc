"""Post-solve camera-location evaluation; never called by the inference pipeline."""
from shapely.geometry import Point,shape
from shapely.ops import nearest_points,unary_union
from geophotoloc.geometry.coordinates import LocalCoordinateSystem,horizontal_distance
from geophotoloc.localization.projection import to_local_geometry


def evaluate_camera_location(result, truth):
    """truth is an independently established GeoPoint, accepted only after solve."""
    system=LocalCoordinateSystem(truth)
    origin=Point(0,0)
    local=[to_local_geometry(shape(region.geometry),system) for region in result.regions]
    ranks=[i+1 for i,geom in enumerate(local) if geom.covers(origin)]
    nearest=min((geom.distance(origin) for geom in local),default=None)
    top=result.regions[0] if result.regions else None
    return dict(status=result.status,candidate_regions=len(local),truth_inside_any=bool(ranks),
                containing_ranks=ranks,nearest_region_distance_m=nearest,
                top1_point_distance_m=horizontal_distance(truth,top.best_location) if top else None,
                top1_area_m2=top.area_m2 if top else None,
                participating_landmarks=len(top.assignments) if top else 0,
                note='来源自报 camera location，不是测量级真值；空候选不计算虚构距离。')
