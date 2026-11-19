"""Candidate-dependent order evidence. No reference locations or calibrated scores."""
import numpy as np
from shapely.geometry import Point
from .spatial_refinement import _angular_arrays
from .robust_scoring import order_constraints
from .hypotheses import equivalent_entity,explicitly_same_object
from geophotoloc.models.refinement import RelationObservationEvidence


def classify_relations(points, observations, candidates, geometries, relations, config, evidence=None):
    """Classify every deduplicated order at every point, not once per image.

    HARD additionally needs independently supplied identity AND full-silhouette
    evidence. Existing model/name assertions alone never manufacture those facts.
    """
    points=np.asarray(points,dtype=float).reshape(-1,2)
    if not np.isfinite(points).all():raise ValueError('Points must be finite')
    evidence={k:RelationObservationEvidence.model_validate(v) for k,v in (evidence or {}).items()}
    edges=order_constraints(observations,relations,config)
    directed={(e['left'],e['right']) for e in edges}
    n=len(points);keep=np.ones(n,dtype=bool);soft_sum=np.zeros(n);soft_n=np.zeros(n,dtype=int)
    hard_ok=np.zeros(n,dtype=int);hard_bad=np.zeros(n,dtype=int);hard_unknown=np.zeros(n,dtype=int);reports=[];cache={}
    for edge in edges:
        a,b=edge['left'],edge['right'];reasons=[]
        classes=np.full(n,'UNKNOWN',dtype='<U7');order=np.zeros(n,dtype=int)
        if a not in candidates or b not in candidates:reasons.append('missing_map_candidate')
        elif (equivalent_entity(candidates[a],candidates[b]) or explicitly_same_object(a,b,config) or
              candidates[a].entity.id in candidates[b].equivalent_entity_ids or candidates[b].entity.id in candidates[a].equivalent_entity_ids):
            reasons.append('same_physical_entity')
        if (b,a) in directed or edge['downweight_reasons']:reasons.append('contradictory_relation')
        oa,ob=observations[a],observations[b]
        if not(oa.coordinates_reliable and ob.coordinates_reliable) or ob.x-oa.x<=config.x_tolerance:
            reasons.append('unavailable_or_ambiguous_image_order')
        if not reasons:
            complete=[];trusted=[]
            for key,o in ((a,oa),(b,ob)):
                c=candidates[key];g=geometries.get(key)
                polygon=g is not None and not g.is_empty and g.is_valid and g.geom_type in {'Polygon','MultiPolygon'}
                full=polygon and c.entity.complete_geometry and c.entity.geometry_precision=='complete_outline' and c.entity.category in {'building','tower'}
                complete.append(full)
                ev=evidence.get(key,RelationObservationEvidence())
                trusted.append(not o.identity_uncertain and c.identity_certain and c.query_source=='primary' and c.score_components.get('name_similarity',0)>=1-1e-9 and ev.identity_confirmed and ev.full_outline_visible)
                if key not in cache:
                    if polygon and n:cache[key]=_angular_arrays(points,g)
                    elif g is not None and not g.is_empty and g.is_valid and n:
                        p=g.representative_point();d=np.array([p.x,p.y])-points
                        cache[key]=(np.degrees(np.arctan2(d[:,0],d[:,1]))%360,np.zeros(n),np.linalg.norm(d,axis=1)<=config.minimum_distance_m)
                    else:cache[key]=(np.zeros(n),np.full(n,360.),np.ones(n,dtype=bool))
            ca,wa,ia=cache[a];cb,wb,ib=cache[b]
            delta=(cb-ca+180)%360-180;half=(wa+wb)/2;tol=config.angular_tolerance_deg
            # Tolerance bands near overlap AND antipodal limits are indeterminate.
            usable=~(ia|ib)&(wa<180-tol)&(wb<180-tol)&(np.abs(delta)+half<180-tol)
            separated=usable&(np.abs(delta)>half+tol)
            order[separated]=np.where(delta[separated]>0,1,-1)
            classes[usable]='SOFT'
            boxes=oa.bbox is not None and ob.bbox is not None and oa.bbox.x_max+config.x_tolerance<ob.bbox.x_min
            if all(complete) and all(trusted) and boxes:
                classes[separated]='HARD';hard_unknown+=~separated
            if not all(complete):reasons.append('incomplete_or_non_building_outline')
            if not all(trusted):reasons.append('identity_or_full_visibility_not_independently_confirmed')
            if not boxes:reasons.append('overlapping_or_missing_image_boxes')
        hard=classes=='HARD';soft=classes=='SOFT'
        hard_ok+=hard&(order==1);hard_bad+=hard&(order==-1)
        keep&=~(hard&(order==-1));soft_sum+=np.where(soft,(order+1)/2,0);soft_n+=soft
        reports.append(dict(left=a,right=b,reasons=reasons,counts={k:int(np.sum(classes==k)) for k in ('HARD','SOFT','UNKNOWN')},
                            classes=classes.tolist(),orders=order.tolist()))
    scores=[float(s/n) if n else None for s,n in zip(soft_sum,soft_n)]
    return keep,dict(relations=reports,soft_scores=scores,hard_satisfied=hard_ok.tolist(),hard_conflicts=hard_bad.tolist(),
        hard_indeterminate=hard_unknown.tolist(),meaning='hard_indeterminate counts static HARD-ready pairs downgraded at this point; SOFT means diagnostic, not probabilities; UNKNOWN neutral')
