"""Automatic A0/A1/A2; A1 is the whole soft-scored set, A2 is actual F output."""
from collections import defaultdict
from time import perf_counter
import numpy as np
from shapely.geometry import shape,mapping
from shapely.ops import unary_union
from geophotoloc.models import GeoPoint
from geophotoloc.geometry.coordinates import LocalCoordinateSystem
from .projection import to_local_geometry,to_wgs84_geometry
from .region_selection import sampled_cell_geometry
from .spatial_refinement import polygonal_valid


def build_automatic_refinement(vision,matching,pose,bounds,semantic=None):
    start=perf_counter();parts=defaultdict(list);systems={};audits=[];values=[];points=0;repairs=[]
    for h in pose.hypotheses:
        if not h.searched_points:continue
        if not h.automatic_relation_audit:raise ValueError('F relation audit required')
        b=bounds[h.region_id];s=systems.setdefault(h.region_id,LocalCoordinateSystem(GeoPoint(latitude=(b.south+b.north)/2,longitude=(b.west+b.east)/2)))
        traces=[t for t in h.sample_trace if 'outside_exact_distance_domain' not in t.get('reasons',[])];xy=[(t['x'],t['y']) for t in traces]
        fine=[p for p,t in zip(xy,traces) if t['phase']=='fine'];coarse=[p for p,t in zip(xy,traces) if t['phase']!='fine']
        if semantic is None:
            domain=polygonal_valid(to_local_geometry(shape(h.search_geometry),s),repairs,h.id+':domain')
            parts[h.region_id].append(sampled_cell_geometry(coarse,fine,h.coarse_spacing_m,pose.config.fine_spacing_m,domain))
        audit=h.automatic_relation_audit
        if audit['points']!=[list(p) for p in xy]:raise ValueError('Automatic scores must share frozen grid order')
        points+=len(xy);values.extend(v for v in audit['scores'] if v is not None)
        audits.append(dict(id=h.id,region_id=h.region_id,assignments=h.assignments,points=len(xy),usable_relations=audit['usable_relations'],weight_sum=audit['weight_sum']))
    if semantic is not None:geometry=semantic['geometry'];area=semantic['area_m2']
    else:
        unions={rid:unary_union(gs) for rid,gs in parts.items()};area=sum(g.area for g in unions.values())
        geometry=mapping(unary_union([polygonal_valid(to_wgs84_geometry(g,systems[rid]),repairs,'A0:'+rid,geographic=True) for rid,g in unions.items()]))
    fgeometry=mapping(unary_union([shape(r.geometry) for r in pose.regions]))
    distribution=dict(count=len(values),null_count=points-len(values),min=min(values,default=None),max=max(values,default=None),
       mean=float(np.mean(values)) if values else None,p10=float(np.percentile(values,10)) if values else None,p90=float(np.percentile(values,90)) if values else None)
    layers=[dict(stage=stage,geometry=g,area_m2=a,reduction_from_previous=None if stage=='A0' or not area else 1-a/area,
       actual_points=points,passed_points=points if stage!='A2' else sum(r.candidate_point_count for r in pose.regions),reliable_relations=sum(h['usable_relations'] for h in audits),
       ranked=stage=='A2',seconds=perf_counter()-start,constraints=[text]) for stage,g,a,text in [
       ('A0',geometry,area,'Frozen finite semantic/distance envelope, unranked'),('A1',geometry,area,'Same envelope, continuous soft relation scores; no exclusion'),
       ('A2',fgeometry,pose.preferred_area_m2,'Actual bounded F preferred regions; heuristic, not strict feasibility')]]
    return dict(version='stage5.4',layers=layers,distribution=distribution,hypotheses=audits,ranked_regions=[dict(rank=i,region_id=r.id,geometry=r.geometry,score=r.best_score.score,automatic_relation_score=r.automatic_relation_score) for i,r in enumerate(pose.regions,1)],
      geojson=dict(type='FeatureCollection',features=[dict(type='Feature',geometry=l['geometry'],properties={'stage':l['stage']}) for l in layers]),elapsed_seconds=perf_counter()-start,
      warnings=['A1 performs no area reduction; scores are not probabilities','A2 is F output, not a second solver or hard feasible set','Finite E-generated grid, unknown FOV/visibility, uncertain identities and partial OSM coverage remain'],geometry_repairs=repairs)
