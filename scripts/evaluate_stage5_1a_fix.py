"""Immutable-input ablation and optional instrumented legacy replay, no reference coordinates."""
import argparse,json,platform,sys,cProfile,pstats,hashlib
from pathlib import Path
from evaluate_stage5_1a import load_inputs,CASES,GROUPS
from geophotoloc.maps import LandmarkStore
from geophotoloc.localization import PoseSolver,PoseSearchConfig

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'docs/evaluation/stage5_1a_fix'


def configurations():
    common=PoseSearchConfig(coarse_spacing_m=250,fine_spacing_m=60,viewpoint_fix=True,record_sample_trace=True).model_dump()
    return {name:PoseSearchConfig(**{**common,**dict(zip(('adaptive_extent','footprint_constraints','visibility_soft'),flags))}) for name,flags in GROUPS.items()}


def summarize(case,result,hashes):
    return dict(case=case,input_sha256=hashes,status=result.status,config=result.config.model_dump(mode='json'),seconds=result.elapsed_seconds,
        searched_points=sum(h.searched_points for h in result.hypotheses),feasible_points=sum(h.feasible_points for h in result.hypotheses),
        candidate_regions=len(result.regions),total_region_area_m2=sum(r.area_m2 for r in result.regions),
        search_area_m2=sum(h.search_area_m2 for h in result.hypotheses),
        best_point=result.regions[0].best_location.model_dump() if result.regions else None,
        region_medoid=result.regions[0].region_medoid.model_dump() if result.regions and result.regions[0].region_medoid else None,
        performance=result.diagnostics,unsearched_area_m2=sum(h.unsearched_area_m2 for h in result.hypotheses),
        hypotheses=[dict(id=h.id,budget=h.budget,used=h.searched_points,coarse=h.coarse_points,fine=h.fine_points,components=h.component_sampling,completion=h.sampling_completion_ratio,unsearched_area_m2=h.unsearched_area_m2) for h in result.hypotheses])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group',choices=tuple(GROUPS),action='append')
    parser.add_argument('--case',choices=CASES,action='append')
    parser.add_argument('--legacy-performance',action='store_true')
    parser.add_argument('--profile',action='store_true')
    args=parser.parse_args(argv)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    configs=configurations()
    if args.legacy_performance:
        configs={'legacy_replay':PoseSearchConfig(coarse_spacing_m=250,fine_spacing_m=60,adaptive_extent=True,footprint_constraints=True,visibility_soft=True,record_sample_trace=True)}
    import importlib.metadata
    environment=dict(python=sys.version,platform=platform.platform(),dependencies={k:importlib.metadata.version(k) for k in ('shapely','numpy','pyproj','pydantic')})
    (OUTPUT/'environment.json').write_text(json.dumps(environment,indent=2)+'\n',encoding='utf-8')
    with LandmarkStore() as store:
        for group,config in configs.items():
            if args.group and group not in args.group:continue
            summary=[]
            for case in CASES:
                if args.case and case not in args.case:continue
                if args.legacy_performance and case=='oriental_pearl':continue
                vision,matching,hashes=load_inputs(case)
                profiler=cProfile.Profile() if args.profile else None
                if profiler:profiler.enable()
                result=PoseSolver(store,config).solve(vision,matching)
                if profiler:
                    profiler.disable()
                    with (OUTPUT/f'{group}_{case}_profile.txt').open('w',encoding='utf-8') as stream:
                        pstats.Stats(profiler,stream=stream).sort_stats('cumulative').print_stats(40)
                (OUTPUT/f'{group}_{case}.json').write_text(result.model_dump_json()+'\n',encoding='utf-8')
                record=summarize(case,result,hashes);summary.append(record)
                print(json.dumps(dict(group=group,case=case,seconds=result.elapsed_seconds,points=record['searched_points'],regions=record['candidate_regions'],performance=record['performance']),ensure_ascii=False),flush=True)
            (OUTPUT/f'{group}_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    if not args.legacy_performance and not args.group and not args.case:
        files=[OUTPUT/f'{g}_{case}.json' for g in GROUPS for case in CASES]+[OUTPUT/f'{g}_summary.json' for g in GROUPS]
        sources=sorted((ROOT/'src/geophotoloc/localization').glob('*.py'))+[ROOT/'src/geophotoloc/models/pose.py',Path(__file__).resolve()]
        manifest=dict(artifacts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                      source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},environment=environment)
        (OUTPUT/'run_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
