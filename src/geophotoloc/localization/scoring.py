"""Pointwise global FOV, pair order, outline uncertainty and pinhole scoring."""
from itertools import combinations
from math import atan, degrees, radians, sin, cos, atan2, tan, hypot
import numpy as np
from geophotoloc.geometry import bearing, signed_angle_difference, check_left_right
from geophotoloc.models.pose import PoseConstraintScore
from .projection import angular_span


def evaluate_pose(point, observations, entities, coordinates, outlines, identity_scores, relations, config, *, order_evaluator=None):
    ids = sorted(entities)
    bearings, distances = {}, {}
    for key in ids:
        target = coordinates[key]
        distance = hypot(target[0] - point[0], target[1] - point[1])
        if distance <= config.minimum_distance_m:
            return PoseConstraintScore(feasible=False, score=0, reasons=["observer_coincident_or_too_close"])
        bearings[key], distances[key] = bearing(point, target), distance
    span = angular_span(list(bearings.values()))
    score = PoseConstraintScore(feasible=False, score=0, landmark_count=len(ids),
                               bearings_deg=bearings, distances_m=distances, span_deg=span)
    if len(ids) < 2:
        score.reasons.append("single_landmark_insufficient")
        return score
    # Full footprint angular extent is an uncertainty interval, not a point.
    angular_width = {}
    for key in ids:
        vertices = outlines.get(key, [])
        offsets = [signed_angle_difference(bearings[key], bearing(point, vertex)) for vertex in vertices
                   if hypot(vertex[0]-point[0], vertex[1]-point[1]) > config.minimum_distance_m]
        angular_width[key] = max((abs(value) for value in offsets), default=0)
    # Explicit inverse edges and x-derived orders share one independent pair key.
    expected = {}
    for relation in relations:
        if relation.relation_type.value not in {"LEFT_OF", "RIGHT_OF"}:
            continue
        a, b = relation.subject_id, relation.object_id
        if a in entities and b in entities and observations[a].coordinates_reliable and observations[b].coordinates_reliable:
            left, right = (a,b) if relation.relation_type.value == "LEFT_OF" else (b,a)
            expected.setdefault(tuple(sorted((a,b))), set()).add((left,right))
    for a,b in combinations(ids,2):
        if not (observations[a].coordinates_reliable and observations[b].coordinates_reliable):
            continue
        if abs(observations[a].x-observations[b].x) > config.x_tolerance:
            left,right = (a,b) if observations[a].x < observations[b].x else (b,a)
            expected.setdefault(tuple(sorted((a,b))),set()).add((left,right))
    for pair, orders in sorted(expected.items()):
        if len(orders) > 1:
            score.conflicts += 1
            continue
        left,right = next(iter(orders))
        if order_evaluator is not None:
            outcome = order_evaluator(left,right)
            if outcome == 'SATISFIED':
                score.satisfied += 1
            elif outcome == 'CONFLICT':
                score.conflicts += 1
            else:
                score.indeterminate += 1
            continue
        result = check_left_right(point, coordinates[left], coordinates[right], "LEFT_OF")
        separation = abs(signed_angle_difference(bearings[left], bearings[right]))
        if (result.satisfied is None or separation <= angular_width[left]+angular_width[right]+config.angular_tolerance_deg):
            score.indeterminate += 1
        elif result.satisfied:
            score.satisfied += 1
        else:
            score.conflicts += 1
    if score.conflicts:
        score.reasons.append("horizontal_order_conflict")
        return score
    best = None
    assumptions = []
    reliable = [key for key in ids if observations[key].coordinates_reliable]
    if len(reliable) < 2:
        score.reasons.append("fewer_than_two_reliable_horizontal_observations")
        return score
    for fov in config.fov_degrees:
        if span > fov + config.angular_tolerance_deg:
            continue
        for principal in config.principal_points:
            offsets = [degrees(atan(2*(observations[key].x-principal)*tan(radians(fov/2)))) for key in reliable]
            headings = [radians(bearings[key]-offset) for key,offset in zip(reliable,offsets)]
            heading = degrees(atan2(sum(sin(x) for x in headings),sum(cos(x) for x in headings))) % 360
            if heading >= 360-1e-10:
                heading = 0.0
            angles = [signed_angle_difference(heading,bearings[key]) for key in ids]
            if max(abs(x) for x in angles) > fov/2 + config.angular_tolerance_deg:
                continue
            residuals = [principal + tan(radians(signed_angle_difference(heading,bearings[key])))/(2*tan(radians(fov/2))) - observations[key].x for key in reliable]
            rmse = float(np.sqrt(np.mean(np.square(residuals))))
            candidate = (rmse, fov, principal, heading)
            assumptions.append(dict(fov_degrees=fov,principal_point_x=principal,heading=heading,projection_rmse=rmse))
            if best is None or candidate < best:
                best = candidate
    if best is None:
        score.reasons.append("no_common_horizontal_field_of_view")
        return score
    rmse,fov,principal,heading = best
    quality = sum(entities[key].geometry_precision == "complete_outline" for key in ids)/len(ids)
    order = score.satisfied/max(1,score.satisfied+score.indeterminate)
    projection = max(0,1-rmse/0.20)
    components = dict(order=order, global_fov=1.0, horizontal_projection=projection,
                      distinct_landmark_support=min(len(ids)/4,1), identity=float(np.mean(identity_scores)),
                      geometry_quality=quality, observation_reliability=len(reliable)/len(ids),
                      outline_angular_uncertainty_deg=max(angular_width.values()))
    total = .40*order + .15 + .20*projection + .10*components['distinct_landmark_support'] + .10*components['identity'] + .05*quality
    score.feasible = True
    score.camera_assumptions = assumptions
    score.score = round(total,8)
    score.components = components
    score.heading,score.fov_degrees,score.principal_point_x,score.projection_rmse = heading,fov,principal,rmse
    score.reasons = ["global_order_and_common_FOV_checked", "horizontal_spacing_is_soft_evidence",
                     "outline_intervals_allow_indeterminate_order", "ABOVE_BELOW_not_used_as_planar_constraints"]
    if span < 2 or min(distances.values()) > 100*max(1,span):
        score.reasons.append("weak_or_narrow_angular_geometry")
    if min(hypot(coordinates[a][0]-coordinates[b][0],coordinates[a][1]-coordinates[b][1]) for a,b in combinations(ids,2)) < 20:
        score.reasons.append("landmark_pair_spacing_under_20m_is_weak_position_evidence")
    return score
