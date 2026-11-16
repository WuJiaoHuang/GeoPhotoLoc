"""Bounded area-weighted, component-first deterministic spatial sampling."""
from dataclasses import dataclass
import hashlib
import math
import numpy as np
from shapely import intersects_xy
from shapely.geometry import box
from .regions import components


def allocate_budget(weights,total,cap=None):
    """One opportunity per component, then area-proportional largest remainders."""
    n=len(weights)
    result=[0]*n
    if not n or not total:
        return result
    caps=[cap or total]*n
    for i in range(min(n,total)):
        result[i]=1
    remaining=total-sum(result)
    while remaining:
        active=[i for i in range(n) if result[i]<caps[i]]
        if not active:break
        mass=sum(max(weights[i],1e-12) for i in active)
        amounts={i:remaining*max(weights[i],1e-12)/mass for i in active}
        for i in active:
            add=min(caps[i]-result[i],int(amounts[i]))
            result[i]+=add
        remaining=total-sum(result)
        if remaining:
            for i in sorted(active,key=lambda i:(-(amounts[i]%1),i)):
                if result[i]<caps[i] and remaining:
                    result[i]+=1;remaining-=1
    return result


def spatial_order(points,limit=None,seed=None):
    """Progressive maximin order, central first; independent of input ordering."""
    unique=sorted(set(points),key=lambda p:hashlib.sha256(f'{p[0]:.9f},{p[1]:.9f}'.encode()).digest())
    if not unique:return []
    xy=np.array(unique,dtype=float)
    count=min(len(xy),len(xy) if limit is None else limit)
    center=xy.mean(axis=0)
    index=unique.index(seed) if seed in unique else int(np.argmin(np.sum((xy-center)**2,axis=1)))
    distance=np.full(len(xy),np.inf)
    chosen=[]
    for _ in range(count):
        chosen.append(unique[index])
        distance=np.minimum(distance,np.sum((xy-xy[index])**2,axis=1))
        distance[index]=-1
        index=int(np.argmax(distance))
    return chosen


@dataclass
class SamplingPlan:
    points: list
    component_ids: list[int]
    spacing: float
    components: list
    quotas: list[int]
    available: int
    limited: bool


def plan_samples(geometry,budget,minimum_spacing=180,maximum_spacing=600,exclude=(),supplemental=False):
    parts=sorted(components(geometry),key=lambda p:(-p.area,p.bounds))
    spacing=float(np.clip(math.sqrt(geometry.area/max(1,budget)),minimum_spacing,maximum_spacing))
    quotas=allocate_budget([p.area for p in parts],budget)
    buckets=[];available=0;excluded=set(exclude)
    for polygon,quota in zip(parts,quotas):
        if not quota:
            buckets.append([]);continue
        west,south,east,north=polygon.bounds
        # Domain-specific lattice, not world-origin traversal. Pool size bounded.
        h=max(spacing,math.sqrt((east-west)*(north-south)/20000))
        pool=[]
        for offset in ((.25,.75) if supplemental else (.5,)):
            xs=np.arange(west+h*offset,east,h);ys=np.arange(south+h*offset,north,h)
            xx,yy=np.meshgrid(xs,ys)
            mask=intersects_xy(polygon,xx.ravel(),yy.ravel())
            pool.extend(zip(xx.ravel()[mask].tolist(),yy.ravel()[mask].tolist()))
        representative=polygon.representative_point();pool.append((representative.x,representative.y))
        if len(pool)<quota and min(east-west,north-south)<h:
            # Thin/offset components can miss the entire lattice. Strip
            # intersections supply interior points across their whole length.
            vertical=east-west>=north-south
            for j in range(quota):
                lo=(j/quota);hi=(j+1)/quota
                strip=box(west+(east-west)*lo,south,west+(east-west)*hi,north) if vertical else box(west,south+(north-south)*lo,east,south+(north-south)*hi)
                cut=polygon.intersection(strip)
                if not cut.is_empty:
                    p=cut.representative_point();pool.append((p.x,p.y))
        pool=[p for p in set(pool) if p not in excluded]
        available+=len(pool)
        buckets.append(spatial_order(pool,quota))
    # Round-robin components: small components are not delayed behind big ones.
    points=[];ids=[]
    for j in range(max(map(len,buckets),default=0)):
        for i,bucket in enumerate(buckets):
            if j<len(bucket):points.append(bucket[j]);ids.append(i)
    return SamplingPlan(points,ids,spacing,parts,quotas,available,available>budget or len(parts)>budget)


def feasible_medoid(points):
    """Exact Euclidean medoid of feasible samples, memory bounded in chunks."""
    xy=np.array(sorted(set(points)),dtype=float)
    sums=np.zeros(len(xy))
    for begin in range(0,len(xy),128):
        delta=xy[begin:begin+128,None,:]-xy[None,:,:]
        sums[begin:begin+128]=np.hypot(delta[:,:,0],delta[:,:,1]).sum(axis=1)
    return tuple(xy[int(np.argmin(sums))])
