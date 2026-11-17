"""Two layers: unexcluded physical envelopes versus ranked local spatial modes."""
from collections import defaultdict
import numpy as np
from shapely import intersects_xy
from shapely.geometry import box
from shapely.ops import unary_union
from .regions import components


def preferred_entries(scores,fine_points,spacing,fine_spacing,feasible_geometry,window,tile_size):
    tiles=defaultdict(list);fine=set(fine_points)
    for p in scores:tiles[(int(np.floor(p[0]/tile_size)),int(np.floor(p[1]/tile_size)))].append(p)
    entries=[]
    for (tx,ty),points in sorted(tiles.items()):
        maximum=max(scores[p].score for p in points)
        support=[p for p in points if scores[p].score>=maximum-window]
        cells=[]
        for x,y in support:
            half=(fine_spacing if (x,y) in fine else spacing)/2
            cells.append(box(x-half,y-half,x+half,y+half))
        geometry=unary_union(cells).intersection(feasible_geometry).intersection(box(tx*tile_size,ty*tile_size,(tx+1)*tile_size,(ty+1)*tile_size))
        xy=np.array(support)
        for polygon in components(geometry):
            members=[p for p,inside in zip(support,intersects_xy(polygon,xy[:,0],xy[:,1])) if inside]
            if members:entries.append((polygon,members))
    return entries


def sampled_cell_geometry(coarse,fine,spacing,fine_spacing,search):
    """Union sample cells before masking, preserving the old set algebra."""
    cells=[]
    for points,step in ((coarse,spacing),(fine,fine_spacing)):
        half=step/2
        cells.extend(box(x-half,y-half,x+half,y+half) for x,y in points)
    return unary_union(cells).intersection(search)


def physical_union_area(unmasked_geometries,context):
    """Union(A_i minus O) = Union(A_i) minus O, with one shared map mask."""
    union=unary_union(unmasked_geometries)
    return union.difference(context.obstacle_union(union)).area if not union.is_empty else 0.


def tiled_union_area(polygons,tile_size):
    """Preferred polygons are already tile-clipped; disjoint tile areas add."""
    groups=defaultdict(list)
    for polygon in polygons:
        p=polygon.representative_point()
        groups[(int(np.floor(p.x/tile_size)),int(np.floor(p.y/tile_size)))].append(polygon)
    return sum(unary_union(parts).area for parts in groups.values())
