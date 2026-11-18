"""Read-only bookkeeping of existing candidates; no references or search changes."""
import math
import numpy as np
from shapely import intersects_xy


def annotate_selection(trace,scores,entries,kept,config,connected,*,retained_members=None):
    before={p for _,members in entries for p in members}
    after={p for polygon,members in entries if any(polygon is k for k in kept) for p in members}
    if retained_members is not None:after=set(retained_members)
    thresholds={}
    if config.dual_regions:
        maxima={}
        for p,s in scores.items():
            tile=(math.floor(p[0]/config.preferred_tile_size_m),math.floor(p[1]/config.preferred_tile_size_m))
            maxima[tile]=max(maxima.get(tile,-1),s.score)
        for p in scores:
            tile=(math.floor(p[0]/config.preferred_tile_size_m),math.floor(p[1]/config.preferred_tile_size_m))
            thresholds[p]=maxima[tile]-config.score_window
    else:
        points=list(scores);xy=np.array(points).reshape(-1,2)
        for polygon in connected:
            members=[p for p,inside in zip(points,intersects_xy(polygon,xy[:,0],xy[:,1])) if inside]
            if members:
                cutoff=max(scores[p].score for p in members)-config.score_window
                thresholds.update({p:cutoff for p in members})
    rounded={(round(p[0],6),round(p[1],6)):p for p in scores}
    ordered=sorted(scores,key=lambda p:(-scores[p].score,p))
    ranks={p:i+1 for i,p in enumerate(ordered)}
    for item in trace:
        p=rounded.get((item['x'],item['y']))
        if p is None:continue
        cutoff=thresholds.get(p)
        item.update(score_rank_within_hypothesis=ranks[p],window_cutoff=cutoff,
                    selection_stage='preferred' if p in after else 'region_cap' if p in before else
                    'below_score_window' if cutoff is not None and scores[p].score<cutoff else 'cell_clipping_or_no_component_membership')
