"""Automatic, continuous image evidence and candidate-dependent outline order."""
import numpy as np
from .robust_scoring import order_constraints
from .hypotheses import equivalent_entity,explicitly_same_object
from .spatial_refinement import _angular_arrays
from geophotoloc.maps.matching import image_category,category_compatibility


def visual_relation_weight(a,b,config):
    """Left/right inputs; continuous normalized separation with the existing deadband."""
    if not(a.coordinates_reliable and b.coordinates_reliable):return 0.
    separation=max(0.,b.x-a.x-config.x_tolerance)
    if not separation:return 0.
    if a.bbox is None or b.bbox is None:
        # Missing boxes never reach the complete-box maximum, even at image edges.
        return .5*separation
    width=max(a.bbox.x_max-a.bbox.x_min,b.bbox.x_max-b.bbox.x_min,config.x_tolerance)
    gap=max(0.,b.bbox.x_min-a.bbox.x_max-config.x_tolerance)
    # Center evidence survives overlap at half strength, normalized by widths.
    return float(np.clip((gap+.5*separation)/(width+gap+.5*separation),0,1))


def automatic_relation_scores(points,observations,candidates,geometries,relations,config):
    points=np.asarray(points,dtype=float).reshape(-1,2)
    if not np.isfinite(points).all():raise ValueError('Finite local points required')
    edges=order_constraints(observations,relations,config);directed={(e['left'],e['right']) for e in edges}
    numerator=np.zeros(len(points));denominator=0.;reports=[];cache={}
    for edge in edges:
        a,b=edge['left'],edge['right'];oa,ob=observations[a],observations[b];reasons=[]
        weight=visual_relation_weight(oa,ob,config)
        if (b,a) in directed or edge['downweight_reasons']:
            weight=0.;reasons.append('explicit_order_conflicts_with_image_or_inverse')
        identity={};same=False
        if a in candidates and b in candidates:
            same=(equivalent_entity(candidates[a],candidates[b]) or explicitly_same_object(a,b,config) or
                  candidates[a].entity.id in candidates[b].equivalent_entity_ids or candidates[b].entity.id in candidates[a].equivalent_entity_ids)
        if same:weight=0.;reasons.append('same_physical_entity')
        consistency=np.full(len(points),.5);determined=np.zeros(len(points),dtype=bool)
        complete=True
        for key,o in ((a,oa),(b,ob)):
            c=candidates.get(key);g=geometries.get(key)
            if c is None:
                complete=False;identity[key]={'entity_id':None};continue
            full=(c.entity.complete_geometry and c.entity.geometry_precision=='complete_outline' and g is not None and not g.is_empty and g.is_valid and g.geom_type in {'Polygon','MultiPolygon'})
            identity[key]=dict(entity_id=c.entity.id,name_similarity=c.score_components.get('name_similarity'),
               category_consistency=category_compatibility(image_category(o),c.entity.category),model_identity_uncertain=o.identity_uncertain,
               match_score=c.score,complete_outline=full)
            complete&=full
            if full and key not in cache:
                cache[key]=_angular_arrays(points,g) if len(points) else (np.array([]),np.array([]),np.zeros(0,dtype=bool))
        if complete and not same:
            ca,wa,ia=cache[a];cb,wb,ib=cache[b];delta=(cb-ca+180)%360-180;half=(wa+wb)/2;tol=config.angular_tolerance_deg
            determined=~(ia|ib)&(wa<180-tol)&(wb<180-tol)&(np.abs(delta)>half+tol)&(np.abs(delta)+half<180-tol)
            consistency[determined]=(delta[determined]>0).astype(float)
        else:reasons.append('missing_candidate_or_complete_outline; representative_order_not_used')
        numerator+=weight*consistency;denominator+=weight
        reports.append(dict(left=a,right=b,visual_weight=weight,identity_evidence=identity,consistency=consistency.tolist(),
          weighted_scores=(weight*consistency).tolist(),conflicts=int(np.sum(determined&(consistency==0))),indeterminate=int((~determined).sum()),
          determined=determined.tolist(),reasons=reasons,
          indeterminate_reason='overlap_inside_antipodal_or_missing_outline; visibility_and_FOV_unknown'))
    return dict(scores=(numerator/denominator).tolist() if denominator>0 else [None]*len(points),weight_sum=denominator,
      usable_relations=sum(r['visual_weight']>0 for r in reports),relations=reports,
      meaning='Visual weight and identity evidence separate; unknown geometry=0.5; heuristic, not probability; no hard exclusion')


def automatic_quality(score,relation_score):
    return (round(score.score,6),round(score.components.get('geometry',0.),6),
            round(.5 if relation_score is None else relation_score,6),score.reliable_landmark_count)
