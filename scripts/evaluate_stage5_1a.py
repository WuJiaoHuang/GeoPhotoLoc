"""Offline A/B/C/D inference using immutable cached vision and map matches only."""
import hashlib
import argparse
import json
from pathlib import Path
from geophotoloc.maps import LandmarkStore
from geophotoloc.models import VisionExtractionResult
from geophotoloc.models.maps import MapMatchingResult
from geophotoloc.localization import PoseSolver,PoseSearchConfig

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'docs/evaluation/stage5_1a'
GROUPS={'baseline':(False,False,False),'extent_only':(True,False,False),
        'footprint_only':(False,True,False),'full_enhanced':(True,True,True)}
CASES=('beijing_cbd','north_bund','guangzhou_skyline','oriental_pearl')


def configurations():
    common=PoseSearchConfig(coarse_spacing_m=250,fine_spacing_m=60).model_dump()
    return {name:PoseSearchConfig(**{**common,**dict(zip(
        ('adaptive_extent','footprint_constraints','visibility_soft'),flags))}) for name,flags in GROUPS.items()}


def load_inputs(case):
    if case=='north_bund':
        path=ROOT/'docs/evaluation/stage5/north_bund_pipeline.json'
        data=json.loads(path.read_text(encoding='utf-8'))
        vision_json=json.dumps(data['vision'],ensure_ascii=False)
        matching_json=json.dumps(data['matching'],ensure_ascii=False)
    else:
        vision_json=(ROOT/f'docs/evaluation/stage2_1/results/{case}.json').read_text(encoding='utf-8')
        matching_json=(ROOT/f'docs/evaluation/stage3/{case}_matches.json').read_text(encoding='utf-8')
    hashes={key:hashlib.sha256(value.encode()).hexdigest() for key,value in [('vision',vision_json),('matching',matching_json)]}
    return VisionExtractionResult.model_validate_json(vision_json),MapMatchingResult.model_validate_json(matching_json),hashes


def summarize(case,result,hashes):
    top=result.regions[0] if result.regions else None
    return dict(case=case,input_sha256=hashes,status=result.status,config=result.config.model_dump(mode='json'),
                search_area_m2=sum(h.search_area_m2 for h in result.hypotheses),
                search_area_note='sum of hypothesis grid domains; overlaps counted; adaptive domains are rectangles with exact sample distance filters',
                searched_points=sum(h.searched_points for h in result.hypotheses),
                distance_filtered_points=sum(h.distance_filtered_points for h in result.hypotheses),
                feasible_points=sum(h.feasible_points for h in result.hypotheses),
                candidate_regions=len(result.regions),total_region_area_m2=sum(r.area_m2 for r in result.regions),
                top1=top.best_location.model_dump() if top else None,best_score=top.best_score.score if top else None,
                top1_components=top.best_score.components if top else {},
                confirmed_order_conflicts=sum(h.confirmed_order_conflicts for h in result.hypotheses),
                potentially_occluded_targets=sum(h.potentially_occluded_targets for h in result.hypotheses),
                occlusion_count_note='point-target pairs with observed 2D blockers, including incomplete-map UNKNOWN; not unique buildings',
                map_coverage_status=sorted(set(h.map_coverage_status for h in result.hypotheses)),
                top1_map_coverage_status=top.map_coverage_status if top else None,
                seconds=result.elapsed_seconds)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group',choices=tuple(GROUPS),action='append',help='Rerun selected groups; omitted runs all four')
    args=parser.parse_args(argv)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with LandmarkStore() as store:
        for group,config in configurations().items():
            if args.group and group not in args.group:
                continue
            summary=[]
            for case in CASES:
                vision,matching,hashes=load_inputs(case)
                result=PoseSolver(store,config).solve(vision,matching)
                (OUTPUT/f'{group}_{case}.json').write_text(result.model_dump_json()+'\n',encoding='utf-8')
                record=summarize(case,result,hashes)
                summary.append(record)
                print(json.dumps(dict(group=group,**record),ensure_ascii=False),flush=True)
            (OUTPUT/f'{group}_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
