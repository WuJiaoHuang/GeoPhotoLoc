"""Optional full-footprint hard constraints and bounded 2D visibility scoring."""
from shapely.geometry import Point
from time import perf_counter
from geophotoloc.models.pose import PoseConstraintScore
from .footprints import angular_footprint, shortest_arc, footprint_order, local_interval
from .scoring import evaluate_pose
from .visibility import potential_visibility, VisibilityResult


def evaluate_enhanced_pose(point, observations, entities, coordinates, outlines, identity_scores,
                           relations, config, context, geometries, *, standing_filters=()):
    footprints = {}
    for key, entity in entities.items():
        complete = (entity.complete_geometry and entity.geometry_precision == 'complete_outline'
                    and geometries[key] is not None and geometries[key].geom_type in {'Polygon','MultiPolygon'})
        geometry = geometries[key] if complete else Point(coordinates[key])
        footprints[key] = angular_footprint(point, geometry, complete=complete)
    evidence = [dict(image_landmark_id=key, **fp.to_dict()) for key,fp in footprints.items()]
    coverage = context.coverage_status(Point(point))

    def failure(reason):
        return PoseConstraintScore(feasible=False, score=0, reasons=[reason], footprint_evidence=evidence,
                                   map_coverage_status=coverage, landmark_count=len(entities))

    if standing_filters:
        result=failure('known_standing_surface_conflict')
        result.filter_reasons=list(standing_filters)
        return result
    if any(not fp.valid for fp in footprints.values()):
        return failure('invalid_footprint_or_observer_inside_target')
    if any(not config.minimum_distance_m < fp.distance_m <= config.max_observation_distance_m for fp in footprints.values()):
        return failure('outside_observation_distance_limits')
    directions = [angle for fp in footprints.values() for angle in (fp.left_bound_deg,fp.right_bound_deg)]
    _,_,span,reference = shortest_arc(directions)
    if config.footprint_constraints and (any(fp.angular_width_deg >= 180 for fp in footprints.values())
                                        or span > max(config.fov_degrees)+config.angular_tolerance_deg):
        return failure('no_common_full_footprint_field_of_view')
    callback = (lambda a,b: footprint_order(footprints[a],footprints[b],reference,config.angular_tolerance_deg)) if config.footprint_constraints else None
    result = evaluate_pose(point, observations, entities, coordinates, outlines, identity_scores, relations,
                           config, order_evaluator=callback)
    result.footprint_evidence = evidence
    result.map_coverage_status = coverage
    if not result.feasible:
        return result
    if config.footprint_constraints:
        assumptions = []
        for assumption in result.camera_assumptions:
            intervals = [local_interval(fp,assumption['heading']) for fp in footprints.values()]
            if all(interval is not None and max(abs(interval[0]),abs(interval[1])) <= assumption['fov_degrees']/2+config.angular_tolerance_deg
                   for interval in intervals):
                assumptions.append(assumption)
        if not assumptions:
            result.feasible = False
            result.score = 0
            result.reasons.append('no_common_full_footprint_camera_assumption')
            return result
        selected = min(assumptions,key=lambda a:(a['projection_rmse'],a['fov_degrees'],a['principal_point_x'],a['heading']))
        projection = max(0,1-selected['projection_rmse']/.20)
        result.score += .20*(projection-result.components['horizontal_projection'])
        result.components['horizontal_projection'] = projection
        result.heading = selected['heading']
        result.fov_degrees = selected['fov_degrees']
        result.principal_point_x = selected['principal_point_x']
        result.projection_rmse = selected['projection_rmse']
        result.camera_assumptions = assumptions
    pair_count = result.satisfied+result.indeterminate
    footprint_quality = (result.satisfied+.5*result.indeterminate)/pair_count if pair_count else .5
    visibilities = []
    if config.visibility_soft and not standing_filters and any(fp.geometry_quality=='COMPLETE_OUTLINE' for fp in footprints.values()):
        context.visibility_evaluated_points=getattr(context,'visibility_evaluated_points',0)+1
    for key,fp in footprints.items():
        if config.visibility_soft and not standing_filters and fp.geometry_quality == 'COMPLETE_OUTLINE':
            started=perf_counter()
            visibility = potential_visibility(point,geometries[key],context,target_entity=entities[key],max_rays=config.visibility_max_rays)
            context.visibility_elapsed=getattr(context,'visibility_elapsed',0)+perf_counter()-started
        else:
            visibility = VisibilityResult(reason='disabled_or_insufficient_geometry_or_standing_conflict')
        visibilities.append(visibility)
        result.visibility_evidence.append(dict(image_landmark_id=key,**visibility.to_dict()))
    visibility_quality = sum(v.quality for v in visibilities)/len(visibilities)
    result.components.update(base_score=result.score, footprint_consistency=footprint_quality,
                             visibility_quality=visibility_quality,
                             footprint_evidence_coverage=result.satisfied/max(1,pair_count),
                             visibility_evidence_coverage=sum(v.complete_ray_fraction for v in visibilities)/len(visibilities),
                             geometry_completeness=sum(fp.geometry_quality=='COMPLETE_OUTLINE' for fp in footprints.values())/len(footprints))
    result.score = round(.80*result.score+.15*footprint_quality+.05*visibility_quality,8)
    result.reasons.append('enhanced_weights_0.80_base_0.15_footprint_0.05_visibility_not_probabilities')
    if coverage != 'COMPLETE':
        result.reasons.append('standing_surface_unknown_outside_confirmed_import_coverage')
    return result
