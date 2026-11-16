"""Fast partial-horizontal-frame model; no occlusion ray calls in this module."""
from itertools import combinations
from math import atan,degrees,radians,tan,sqrt
from shapely.geometry import Point
from geophotoloc.geometry import bearing
from geophotoloc.models.pose import PoseConstraintScore
from .footprints import angular_footprint,circular_segments,intersect_segments,visible_footprint,footprint_order,shortest_arc


def expected_orders(observations,ids,relations,tolerance):
    expected={}
    for r in relations:
        a,b=r.subject_id,r.object_id
        if a in ids and b in ids and observations[a].coordinates_reliable and observations[b].coordinates_reliable and r.relation_type.value in {'LEFT_OF','RIGHT_OF'}:
            expected.setdefault(tuple(sorted((a,b))),set()).add((a,b) if r.relation_type.value=='LEFT_OF' else (b,a))
    for a,b in combinations(sorted(ids),2):
        if observations[a].coordinates_reliable and observations[b].coordinates_reliable and abs(observations[a].x-observations[b].x)>tolerance:
            expected.setdefault((a,b),set()).add((a,b) if observations[a].x<observations[b].x else (b,a))
    return expected


def evaluate_partial_pose(point,observations,entities,coordinates,geometries,identity_scores,relations,config,context,*,standing_filters=()):
    result=PoseConstraintScore(feasible=False,score=0,landmark_count=len(entities))
    if standing_filters:
        result.reasons=['known_standing_surface_conflict'];result.filter_reasons=list(standing_filters);return result
    footprints={}
    for key,entity in entities.items():
        g=geometries[key]
        complete=entity.complete_geometry and entity.geometry_precision=='complete_outline' and g is not None and g.is_valid and g.geom_type in {'Polygon','MultiPolygon'}
        fp=angular_footprint(point,g if complete else Point(coordinates[key]),complete=complete)
        footprints[key]=fp
        if not fp.valid or not config.minimum_distance_m<fp.distance_m<=config.max_observation_distance_m:
            result.reasons=['invalid_geometry_or_observation_distance'];return result
    result.footprint_evidence=[dict(image_landmark_id=k,**f.to_dict()) for k,f in footprints.items()]
    result.distances_m={k:f.distance_m for k,f in footprints.items()}
    result.bearings_deg={k:bearing(point,coordinates[k]) for k in entities}
    reliable=[k for k in entities if observations[k].coordinates_reliable]
    if len(reliable)<2:
        result.reasons=['fewer_than_two_reliable_horizontal_observations'];return result
    expected=expected_orders(observations,entities,relations,config.x_tolerance)
    if any(len(v)>1 for v in expected.values()):
        result.conflicts=sum(len(v)>1 for v in expected.values());result.reasons=['contradictory_image_order'];return result
    _,_,span,reference=shortest_arc([a for fp in footprints.values() for a in (fp.left_bound_deg,fp.right_bound_deg)])
    if span<180 and all(fp.angular_width_deg<180 for fp in footprints.values()):
        result.conflicts=sum(footprint_order(footprints[a],footprints[b],reference,config.angular_tolerance_deg)=='CONFLICT' for orders in expected.values() for a,b in orders)
        if result.conflicts:
            result.reasons=['horizontal_order_conflict'];return result
    best=None;assumptions=[];had_order_conflict=False
    for fov in config.fov_degrees:
        scale=2*tan(radians(fov/2))
        for principal in config.principal_points:
            allowed=[(0.,360.)]
            for key,fp in footprints.items():
                width=fp.angular_width_deg
                if key in reliable and fp.geometry_quality=='COMPLETE_OUTLINE':
                    x=observations[key].x
                    low=degrees(atan((max(0,x-config.observation_x_tolerance)-principal)*scale))
                    high=degrees(atan((min(1,x+config.observation_x_tolerance)-principal)*scale))
                    allowed=intersect_segments(allowed,circular_segments(fp.left_bound_deg-high,width+high-low))
                required=0 if fp.geometry_quality=='POINT_DOWNGRADE' else min(width,config.minimum_visible_angle_deg) if width<.1 else width*config.minimum_visible_fraction
                allowed=intersect_segments(allowed,circular_segments(fp.left_bound_deg+required-fov/2,width+fov-2*required))
                if not allowed:break
            for lo,hi in allowed:
                heading=((lo+hi)/2)%360
                visible={k:visible_footprint(fp,heading,fov,config.minimum_visible_fraction,config.minimum_visible_angle_deg) for k,fp in footprints.items()}
                if not all(v['sufficient'] for v in visible.values()):continue
                satisfied=indeterminate=conflicts=0
                for orders in expected.values():
                    left,right=next(iter(orders))
                    order=footprint_order(footprints[left],footprints[right],heading,config.angular_tolerance_deg)
                    if order=='CONFLICT':conflicts+=1
                    elif order=='SATISFIED':satisfied+=1
                    else:indeterminate+=1
                if conflicts:
                    had_order_conflict=True;continue
                residuals=[]
                for key in reliable:
                    ranges=[(principal+tan(radians(a))/scale,principal+tan(radians(b))/scale) for a,b in visible[key]['intervals']]
                    x=observations[key].x
                    residuals.append(min(max(a-x,0,x-b) for a,b in ranges))
                if any(residual>config.observation_x_tolerance+1e-8 for key,residual in zip(reliable,residuals) if footprints[key].geometry_quality=='COMPLETE_OUTLINE'):continue
                rmse=sqrt(sum(r*r for r in residuals)/len(residuals))
                quality=sum(f.geometry_quality=='COMPLETE_OUTLINE' for f in footprints.values())/len(entities)
                order=satisfied/max(1,satisfied+indeterminate)
                projection=max(0,1-rmse/.2)
                identity=sum(identity_scores)/len(identity_scores)
                base=.4*order+.15+.2*projection+.1*min(len(entities)/4,1)+.1*identity+.05*quality
                consistency=(satisfied+.5*indeterminate)/max(1,satisfied+indeterminate) if expected else .5
                score=.8*base+.15*consistency+.025
                assumption=dict(heading=heading,fov_degrees=fov,principal_point_x=principal,projection_rmse=rmse)
                assumptions.append(assumption)
                rank=(-score,rmse,fov,principal,heading)
                if best is None or rank<best[0]:
                    best=(rank,assumption,visible,satisfied,indeterminate,base,consistency,quality,projection,identity)
    if best is None:
        result.reasons=['no_common_partial_frame_observation_consistency']
        if had_order_conflict:result.conflicts=1;result.reasons.append('horizontal_order_conflict')
        return result
    rank,assumption,visible,sat,indet,base,consistency,quality,projection,identity=best
    result.feasible=True;result.score=round(-rank[0],8);result.stage1_score=result.score
    result.satisfied=sat;result.indeterminate=indet
    result.heading=assumption['heading'];result.fov_degrees=assumption['fov_degrees'];result.principal_point_x=assumption['principal_point_x'];result.projection_rmse=assumption['projection_rmse']
    result.camera_assumptions=assumptions
    result.partial_visibility_evidence=[dict(image_landmark_id=k,**v) for k,v in visible.items()]
    result.components=dict(base_score=base,footprint_consistency=consistency,visibility_quality=.5,
        geometry_completeness=quality,footprint_evidence_coverage=sat/max(1,sat+indet),visibility_evidence_coverage=0,
        order=sat/max(1,sat+indet),global_fov=1,horizontal_projection=projection,identity=identity)
    result.reasons=['partial_horizontal_frame_not_3D_visibility','image_center_is_an_interval_observation_not_building_center','ambiguous_pose_not_unique_location']
    return result
