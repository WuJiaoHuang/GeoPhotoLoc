"""Connected sampled cell regions, clipped to coverage and known obstacles."""
from shapely.geometry import box, mapping
from shapely.ops import unary_union
from .projection import to_wgs84_geometry


def components(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [part for sub in getattr(geometry,"geoms",[]) for part in components(sub)]


def cell_region(samples, spacing, search_geometry, context):
    if not samples:
        return []
    half = spacing/2
    union = unary_union([box(x-half,y-half,x+half,y+half) for x,y in samples]).intersection(search_geometry)
    union = union.difference(context.obstacle_union(union))
    return sorted(components(union),key=lambda p:(-p.area,p.bounds))


def geographic_mapping(geometry, context):
    return mapping(to_wgs84_geometry(geometry,context.system))
