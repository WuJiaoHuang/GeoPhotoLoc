"""Bounded identity beam built only from supplied Stage 3 candidates."""
from itertools import combinations
from geophotoloc.maps.matching import same_physical_entity,category_compatibility,image_category
from geophotoloc.geometry.coordinates import horizontal_distance
from geophotoloc.models.maps import RegionHypothesis
from shapely.geometry import shape


def equivalent_entity(a,b):
    if same_physical_entity(a,b):return True
    x,y=a.entity,b.entity
    if x.complete_geometry and y.complete_geometry and x.geometry_precision==y.geometry_precision=='complete_outline' and x.geometry and y.geometry:
        gx,gy=shape(x.geometry),shape(y.geometry)
        return gx.geom_type in {'Polygon','MultiPolygon'} and gy.geom_type in {'Polygon','MultiPolygon'} and gx.equals(gy)
    return False


def explicitly_same_object(a,b,config):
    group=config.same_object_groups.get(a)
    return group is not None and group==config.same_object_groups.get(b)


def assignment_valid(selected,config):
    return all(not equivalent_entity(a,b) or explicitly_same_object(ka,kb,config)
               for (ka,a),(kb,b) in combinations(selected,2))


def independent_ids(entities,config):
    from types import SimpleNamespace
    retained=[]
    for key in sorted(entities):
        if not any(equivalent_entity(SimpleNamespace(entity=entities[key]),SimpleNamespace(entity=entities[other])) for other in retained):
            retained.append(key)
    return retained


def diverse_beam(states,limit):
    """Reserve lexical alternatives AND different unmatched-object masks."""
    ordered=states[:max(1,limit//2)]
    masks={tuple(k for k,v in s[0].items() if v is None) for s in ordered}
    for state in states:
        mask=tuple(k for k,v in state[0].items() if v is None)
        if mask not in masks and len(ordered)<limit:
            ordered.append(state);masks.add(mask)
    for state in states:
        if len(ordered)>=limit:break
        if not any(state is item for item in ordered):ordered.append(state)
    return ordered


def generate_identity_hypotheses(vision,matching,config):
    lookup={m.image_landmark_id:m for m in matching.matches}
    pools={};pool_report={};pruned=0;expanded=0
    for observation in sorted(vision.landmarks,key=lambda o:o.id):
        candidates=lookup[observation.id].candidates if observation.id in lookup else []
        unique={}
        for c in candidates:
            if not c.entity.region_ids:continue
            previous=unique.get(c.entity.id)
            if previous is None or c.score>previous.score:unique[c.entity.id]=c
        values=sorted(unique.values(),key=lambda c:(-c.score,-category_compatibility(image_category(observation),c.entity.category),
                    -int(c.entity.complete_geometry),c.entity.id))[:config.max_identity_candidates]
        pools[observation.id]=values+[None]
        pool_report[observation.id]=[dict(entity_id=c.entity.id,score=c.score,geometry_precision=c.entity.geometry_precision) if c else dict(entity_id=None,status='UNKNOWN',score=0.) for c in pools[observation.id]]
    # State: assignments, selected candidates, common region IDs, lexical mass.
    beam=[({},[],None,0.)]
    for key,options in pools.items():
        next_states=[]
        for assigned,selected,regions,mass in beam:
            for candidate in options:
                expanded+=1
                new_selected=selected+([(key,candidate)] if candidate else [])
                if not assignment_valid(new_selected,config):continue
                common=regions
                if candidate:
                    common=set(candidate.entity.region_ids) if regions is None else regions&set(candidate.entity.region_ids)
                    if not common:continue
                    if any(horizontal_distance(c.entity.location,candidate.entity.location)>15000 for _,c in selected):continue
                next_states.append(({**assigned,key:candidate.entity.id if candidate else None},new_selected,common,mass+(candidate.score if candidate else 0)))
        next_states.sort(key=lambda s:(-s[3],tuple((k,v or '') for k,v in s[0].items())))
        pruned+=max(0,len(next_states)-config.identity_beam_width)
        beam=diverse_beam(next_states,config.identity_beam_width)
    # Reserve different UNKNOWN masks before filling lexical alternatives. The
    # diversity rule is generic, never tied to a photo object name or ID.
    beam.sort(key=lambda s:(-s[3],tuple((k,v or '') for k,v in s[0].items())))
    ordered=diverse_beam(beam,config.max_joint_hypotheses)
    final=[];search=[]
    for assignments,selected,regions,mass in ordered:
        if len(final)>=config.max_joint_hypotheses:break
        region=min(regions) if regions else None
        record=dict(assignments=assignments,unknown_image_ids=[k for k,v in assignments.items() if v is None],region_id=region,
                    identity_score=mass/max(1,len(pools)),independent_landmarks=len(independent_ids({k:c.entity for k,c in selected},config)))
        final.append(record)
        if selected and region:
            search.append(RegionHypothesis(region_id=region,assignments={k:v for k,v in assignments.items() if v is not None},
                score=record['identity_score'],matched_objects=len(selected),max_pair_distance_m=max((horizontal_distance(a.entity.location,b.entity.location) for (_,a),(_,b) in combinations(selected,2)),default=0),
                reasons=['bounded_joint_identity_beam; UNKNOWN is not a fabricated entity']))
    return search,final,dict(candidate_pools=pool_report,expanded_states=expanded,beam_pruned=pruned,
                            final_pruned=max(0,len(beam)-len(final)),beam_width=config.identity_beam_width)
