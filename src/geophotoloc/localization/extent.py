"""Camera extent from target geometry, never clipped by map import bounds."""
import itertools
import numpy as np
from shapely import points,distance
from shapely.geometry import box


def adaptive_search_extent(geometries,max_distance_m):
    if not 0<max_distance_m<=10000 or not geometries:
        raise ValueError('Nonempty geometry and bounded positive observation distance required')
    bounds=[g.bounds for g in geometries if g is not None and not g.is_empty]
    if len(bounds)!=len(geometries):
        raise ValueError('Each target needs an outline or representative point')
    # Enclosing rectangle; exact intersection of distance sets is applied in batches.
    return box(min(b[0] for b in bounds)-max_distance_m,min(b[1] for b in bounds)-max_distance_m,
               max(b[2] for b in bounds)+max_distance_m,max(b[3] for b in bounds)+max_distance_m)


def within_observation_distance(xy,geometries,max_distance_m):
    if not 0<max_distance_m<=10000 or not geometries:
        raise ValueError('Nonempty geometry and bounded positive observation distance required')
    xy=np.asarray(xy,dtype=float).reshape(-1,2)
    mask=np.isfinite(xy).all(axis=1)
    for geometry in geometries:
        if geometry.geom_type=='Point':
            mask &= np.hypot(xy[:,0]-geometry.x,xy[:,1]-geometry.y)<=max_distance_m
        else:
            west,south,east,north=geometry.bounds
            mask &= (xy[:,0]>=west-max_distance_m)&(xy[:,0]<=east+max_distance_m)&(xy[:,1]>=south-max_distance_m)&(xy[:,1]<=north+max_distance_m)
            indices=np.flatnonzero(mask)
            if len(indices):
                mask[indices] &= distance(points(xy[indices]),geometry)<=max_distance_m
        if not mask.any():
            break
    return mask


def distance_batches(iterator,geometries,max_distance_m,batch_size=128):
    if not 1<=batch_size<=1024:
        raise ValueError('Invalid distance batch size')
    iterator=iter(iterator)
    while batch:=list(itertools.islice(iterator,batch_size)):
        mask=within_observation_distance(batch,geometries,max_distance_m)
        yield from zip(batch,mask.tolist())
