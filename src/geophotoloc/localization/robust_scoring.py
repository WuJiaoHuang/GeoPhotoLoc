"""Discrete camera hypotheses and robust soft evidence; physical limits stay hard."""
from itertools import combinations
import numpy as np
from shapely.geometry import Point
from geophotoloc.models.pose import PoseConstraintScore
from .footprints import angular_footprint,visible_footprint
from .hypotheses import independent_ids,assignment_valid
from types import SimpleNamespace


def huber_loss(error,delta=1.):
    if not np.isfinite(delta) or delta<=0:raise ValueError('Huber delta must be finite and positive')
    e=np.abs(np.asarray(error,dtype=float))
    return np.where(e<=delta,.5*e*e,delta*(e-.5*delta))


def angular_interval_distance(direction,center,width):
    return np.maximum(0,np.abs((np.asarray(direction)-center+180)%360-180)-width/2)


def normalized_angular_error(observed_x,heading,fov,principal,center,width,tolerance=.06):
    scale=2*np.tan(np.deg2rad(fov/2))
    offset=np.rad2deg(np.arctan((observed_x-principal)*scale))
    lo=np.rad2deg(np.arctan((max(0,observed_x-tolerance)-principal)*scale))
    hi=np.rad2deg(np.arctan((min(1,observed_x+tolerance)-principal)*scale))
    sigma=max(.05,(hi-lo)/2)
    error=angular_interval_distance(heading+offset,center,width)
    return float(error),float(error/sigma),float(sigma)


def order_constraints(observations,relations,config):
    edges={}
    for relation in relations:
        if relation.relation_type.value not in {'LEFT_OF','RIGHT_OF'}:continue
        left,right=(relation.subject_id,relation.object_id) if relation.relation_type.value=='LEFT_OF' else (relation.object_id,relation.subject_id)
        if left not in observations or right not in observations:continue
        a,b=observations[left],observations[right]
        contradiction=a.coordinates_reliable and b.coordinates_reliable and a.x>b.x+config.x_tolerance
        key=(left,right)
        edge=edges.setdefault(key,dict(left=left,right=right,weight=0.,sources=[],downweight_reasons=[]))
        edge['weight']=max(edge['weight'],config.contradictory_relation_weight if contradiction else 1.)
        if 'explicit' not in edge['sources']:edge['sources'].append('explicit')
        if contradiction:edge['downweight_reasons']=['explicit_relation_contradicts_reliable_image_x']
    for a,b in combinations(sorted(observations),2):
        x,y=observations[a],observations[b]
        if not (x.coordinates_reliable and y.coordinates_reliable) or abs(x.x-y.x)<=config.x_tolerance:continue
        left,right=(a,b) if x.x<y.x else (b,a)
        edge=edges.setdefault((left,right),dict(left=left,right=right,weight=0.,sources=[],downweight_reasons=[]))
        edge['weight']=max(1.,edge['weight']);edge['sources'].append('image_x')
    return [edges[k] for k in sorted(edges)]


def evaluate_robust_pose(point,observations,entities,coordinates,geometries,identity_scores,relations,config,context,*,standing_filters=(),detailed=True):
    result=PoseConstraintScore(feasible=False,score=0,landmark_count=len(entities))
    if not hasattr(context,'robust_identity_cache'):context.robust_identity_cache={}
    cache_key=(tuple(sorted((k,e.id) for k,e in entities.items())),tuple(sorted(config.same_object_groups.items())))
    if cache_key not in context.robust_identity_cache:
        if len(context.robust_identity_cache)>=100:context.robust_identity_cache.clear()
        valid=assignment_valid([(k,SimpleNamespace(entity=e)) for k,e in entities.items()],config)
        context.robust_identity_cache[cache_key]=(valid,independent_ids(entities,config))
    valid,independent=context.robust_identity_cache[cache_key]
    if not valid:
        result.reasons=['duplicate_physical_entity_assignment'];return result
    if standing_filters:
        result.filter_reasons=list(standing_filters);result.reasons=['physical_standing_conflict'];return result
    ids=sorted(entities)
    reliable=[k for k in independent if observations[k].coordinates_reliable]
    if len(reliable)<2:
        result.reasons=['fewer_than_two_independent_reliable_landmarks'];return result
    footprints={};quality=[]
    for key in ids:
        entity=entities[key];g=geometries[key]
        complete=entity.complete_geometry and entity.geometry_precision=='complete_outline' and g is not None and g.is_valid and g.geom_type in {'Polygon','MultiPolygon'}
        fp=angular_footprint(point,g if complete else Point(coordinates[key]),complete=complete)
        if not fp.valid or not config.minimum_distance_m<fp.distance_m<=config.max_observation_distance_m:
            result.reasons=['physical_target_coincidence_or_distance_limit'];return result
        footprints[key]=fp;quality.append(1. if fp.geometry_quality=='COMPLETE_OUTLINE' else .25)
    centers=np.array([footprints[k].center_bearing_deg for k in ids])
    widths=np.array([footprints[k].angular_width_deg if footprints[k].geometry_quality!='POINT_DOWNGRADE' else 2*config.point_geometry_uncertainty_deg for k in ids])
    # All H/F/principal alternatives are finite algebraic seeds, not continuous
    # pose optimization: center/edges aligned to each observation plus a mean.
    if not hasattr(context,'robust_camera_cache'):context.robust_camera_cache={}
    camera_key=(tuple((k,observations[k].x) for k in ids),config.fov_degrees,config.principal_points,config.observation_x_tolerance)
    if camera_key not in context.robust_camera_cache:
        if len(context.robust_camera_cache)>=100:context.robust_camera_cache.clear()
        fov=np.repeat(np.array(config.fov_degrees),len(config.principal_points))
        principal=np.tile(np.array(config.principal_points),len(config.fov_degrees))
        xs=np.array([observations[k].x for k in ids]);scale=2*np.tan(np.deg2rad(fov[:,None]/2))
        offsets=np.rad2deg(np.arctan((xs[None,:]-principal[:,None])*scale))
        low=np.rad2deg(np.arctan((np.maximum(0,xs-config.observation_x_tolerance)[None,:]-principal[:,None])*scale))
        high=np.rad2deg(np.arctan((np.minimum(1,xs+config.observation_x_tolerance)[None,:]-principal[:,None])*scale))
        context.robust_camera_cache[camera_key]=(fov,principal,offsets,np.maximum(.05,(high-low)/2))
    fov,principal,offsets,sigma=context.robust_camera_cache[camera_key]
    seed_center=(centers[None,:]-offsets)%360
    radians=np.deg2rad(seed_center)
    mean=np.rad2deg(np.arctan2(np.sin(radians).sum(axis=1),np.cos(radians).sum(axis=1)))%360
    seeds=np.concatenate([seed_center,seed_center-widths[None,:]/2,seed_center+widths[None,:]/2,mean[:,None]],axis=1)%360
    headings=seeds.ravel();camera_index=np.repeat(np.arange(len(fov)),seeds.shape[1])
    raw=angular_interval_distance(headings[:,None]+offsets[camera_index],centers[None,:],widths[None,:])
    normalized=raw/sigma[camera_index];losses=huber_loss(normalized,config.huber_delta)
    obs_weights=np.array([1. if observations[k].coordinates_reliable else .35 for k in ids])
    if not hasattr(context,'robust_order_cache'):context.robust_order_cache={}
    order_key=(tuple((k,o.x,o.coordinates_reliable) for k,o in sorted(observations.items())),
               tuple((r.subject_id,r.object_id,r.relation_type.value) for r in relations),config.x_tolerance,config.contradictory_relation_weight)
    if order_key not in context.robust_order_cache:
        if len(context.robust_order_cache)>=100:context.robust_order_cache.clear()
        context.robust_order_cache[order_key]=order_constraints(observations,relations,config)
    constraints=context.robust_order_cache[order_key]
    local=(centers[None,:]-headings[:,None]+180)%360-180
    left=local-widths[None,:]/2;right=local+widths[None,:]/2
    n_all=max(1,len(observations));unknown=set(observations)-set(ids)
    identity_by_id=dict(zip(entities,identity_scores))
    qualities=dict(zip(ids,quality))
    index_by_id={key:i for i,key in enumerate(ids)}
    relation_values=[]
    for edge in constraints:
        a=index_by_id.get(edge['left']);b=index_by_id.get(edge['right'])
        values=np.full(len(headings),.5)
        if a is not None and b is not None and quality[a]==1 and quality[b]==1:
            valid=(left[:,a]>-180)&(right[:,a]<180)&(left[:,b]>-180)&(right[:,b]<180)&(np.maximum(right[:,a],right[:,b])-np.minimum(left[:,a],left[:,b])<180-config.angular_tolerance_deg)
            values=np.where(valid & (right[:,a]<left[:,b]-config.angular_tolerance_deg),1.,values)
            values=np.where(valid & (left[:,a]>right[:,b]+config.angular_tolerance_deg),0.,values)
        relation_values.append(values)
    def fit(excluded=()):
        retained=[i for i,k in enumerate(ids) if k not in excluded]
        mean_loss=(losses[:,retained]*obs_weights[retained]).sum(axis=1)/obs_weights[retained].sum()
        missing=n_all-len(retained)
        projection=(np.exp(-np.minimum(mean_loss,700))*len(retained)+config.unknown_projection_score*missing)/n_all
        numerator=np.zeros(len(headings));weight=0
        for edge,values in zip(constraints,relation_values):
            assessed=np.full(len(headings),.5) if edge['left'] in excluded or edge['right'] in excluded else values
            numerator+=edge['weight']*assessed;weight+=edge['weight']
        order=numerator/weight if weight else np.full(len(headings),.5)
        identity=max(0,sum(identity_by_id[ids[i]] for i in retained)/n_all-config.outlier_identity_penalty*len(excluded))
        geometry=sum(quality[i] for i in retained)/n_all
        totals=config.projection_weight*projection+config.order_weight*order+config.identity_weight*identity+config.geometry_weight*geometry
        chosen=int(np.argmax(totals))
        return dict(index=chosen,total=float(totals[chosen]),loss=float(mean_loss[chosen]),projection=float(projection[chosen]),order=float(order[chosen]),identity=identity,geometry=geometry,excluded=list(excluded))
    kept=fit();best=kept;comparisons=[]
    if config.max_outliers and len(independent)>=3:
        for key in independent:
            remaining=independent_ids({k:e for k,e in entities.items() if k!=key},config) if config.same_object_groups else [k for k in independent if k!=key]
            if sum(observations[k].coordinates_reliable for k in remaining)<2:continue
            alternative=fit((key,));residual=float(normalized[kept['index'],index_by_id[key]])
            accepted=(residual>config.outlier_residual_threshold and kept['loss']-alternative['loss']>=config.outlier_loss_improvement and alternative['total']>kept['total'])
            if detailed:
                comparisons.append(dict(image_landmark_id=key,keep_score=kept['total'],exclude_score=alternative['total'],keep_loss=kept['loss'],exclude_loss=alternative['loss'],normalized_residual_if_kept=residual,eligible=accepted,
                    reason='Residual, loss improvement, two-independent-landmark support and penalized score are compared'))
            if accepted and alternative['total']>best['total']:best=alternative
    chosen=best['index'];ci=camera_index[chosen];heading=float(headings[chosen]);f=float(fov[ci]);c=float(principal[ci])
    excluded=set(best['excluded']);retained=[k for k in ids if k not in excluded]
    result.feasible=True;result.score=round(best['total'],8);result.stage1_score=result.score
    result.heading=heading;result.fov_degrees=f;result.principal_point_x=c
    result.projection_rmse=float(np.sqrt(np.mean(raw[chosen]**2)))
    result.outlier_image_ids=sorted(excluded);result.outlier_comparisons=comparisons;result.unknown_image_ids=sorted(unknown)
    remaining_independent=independent_ids({k:entities[k] for k in retained},config) if config.same_object_groups else [k for k in independent if k not in excluded]
    result.reliable_landmark_count=sum(observations[k].coordinates_reliable for k in remaining_independent)
    result.identifiability='AMBIGUOUS_TWO_LANDMARKS' if result.reliable_landmark_count==2 else 'MULTI_LANDMARK_AMBIGUITY'
    result.components=dict(projection=best['projection'],order=best['order'],identity=best['identity'],geometry=best['geometry'],
        normalized_huber_loss=best['loss'],reliable_landmarks=result.reliable_landmark_count,outlier_count=len(excluded),identity_evidence_coverage=len(retained)/n_all,
        geometry_completeness=best['geometry'],visibility_quality=.5)
    for edge,values in zip(constraints,relation_values):
        value=.5 if edge['left'] in excluded or edge['right'] in excluded else float(values[chosen])
        status='EXCLUDED_OBSERVATION' if edge['left'] in excluded or edge['right'] in excluded else 'SATISFIED' if value==1 else 'CONFLICT' if value==0 else 'INDETERMINATE'
        if status=='SATISFIED':result.satisfied+=1
        elif status=='CONFLICT':result.conflicts+=1
        else:result.indeterminate+=1
        if detailed:result.order_evidence.append(dict(**edge,status=status))
    if not detailed:
        result.reasons=['physical_hard_constraints_passed; robust_visual_soft_score']
        return result
    result.distances_m={k:footprints[k].distance_m for k in ids}
    result.bearings_deg={k:footprints[k].center_bearing_deg for k in ids}
    result.footprint_evidence=[dict(image_landmark_id=k,**footprints[k].to_dict()) for k in ids]
    for i,key in enumerate(ids):
        result.projection_evidence.append(dict(image_landmark_id=key,raw_error_deg=float(raw[chosen,i]),normalized_error=float(normalized[chosen,i]),tolerance_deg=float(sigma[ci,i]),huber_loss=float(losses[chosen,i]),
            status='OUTLIER' if key in excluded else 'INLIER',geometry_quality=footprints[key].geometry_quality,allowed_angular_width_deg=float(widths[i])))
        result.partial_visibility_evidence.append(dict(image_landmark_id=key,**visible_footprint(footprints[key],heading,f,config.minimum_visible_fraction,config.minimum_visible_angle_deg)))
    result.reasons=['physical_hard_constraints_passed; visual evidence is robust and soft','heuristic_joint_score_not_a_probability','discrete_camera_hypotheses_not_continuous_optimization']
    return result
