"""Stage 5.1B immutable-input inference only; no positional references."""
import argparse,hashlib,json,platform,sys,cProfile,pstats,gzip
from pathlib import Path
from evaluate_stage5_1a import load_inputs,CASES
from geophotoloc.maps import LandmarkStore
from geophotoloc.localization import PoseSolver,PoseSearchConfig

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'docs/evaluation/stage5_1b'
GROUPS={'baseline':(False,False,False),'robust_only':(True,False,False),'identity_only':(False,True,False),'joint_full':(True,True,True)}


def configurations():
    common=PoseSearchConfig(adaptive_extent=True,viewpoint_fix=True,record_sample_trace=True,audit_hard_feasibility=True,max_hypotheses=12).model_dump()
    return {name:PoseSearchConfig(**{**common,**dict(zip(('robust_geometry','joint_identity','dual_regions'),flags)),'visibility_soft':name=='joint_full'}) for name,flags in GROUPS.items()}


def summarize(case,result,hashes):
    top=result.regions[0] if result.regions else None
    return dict(case=case,input_sha256=hashes,status=result.status,seconds=result.elapsed_seconds,config=result.config.model_dump(mode='json'),
        searched_points=sum(h.searched_points for h in result.hypotheses),identity_hypotheses=len(result.hypotheses),
        generated_hypotheses=len(result.identity_hypotheses) if result.config.joint_identity else len(result.hypotheses),
        searched_identity_hypotheses=sum(h.searched_points>0 for h in result.hypotheses),
        feasible_regions=len(result.feasible_regions),preferred_regions=len(result.regions),feasible_area_m2=result.feasible_area_m2,
        preferred_area_m2=result.preferred_area_m2,hypothesis_area_sum_m2=sum(r.area_m2 for r in result.feasible_regions),
        top1=top.best_location.model_dump() if top else None,top1_area_m2=top.area_m2 if top else None,
        top1_score=top.best_score.model_dump(mode='json') if top else None,performance=result.diagnostics,
        reliable_landmarks=top.best_score.reliable_landmark_count if top else 0,outlier_count=len(top.best_score.outlier_image_ids) if top else 0)


def read_result(group,case):
    from geophotoloc.models.pose import PoseLocalizationResult
    path=OUTPUT/f'{group}_{case}.json.gz'
    return PoseLocalizationResult.model_validate_json(gzip.decompress(path.read_bytes()))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group',choices=tuple(GROUPS),action='append')
    parser.add_argument('--case',choices=CASES,action='append')
    parser.add_argument('--profile',action='store_true')
    args=parser.parse_args(argv);OUTPUT.mkdir(parents=True,exist_ok=True)
    with LandmarkStore() as store:
        for group,config in configurations().items():
            if args.group and group not in args.group:continue
            summary=[]
            for case in CASES:
                if args.case and case not in args.case:continue
                vision,matching,hashes=load_inputs(case)
                profiler=cProfile.Profile() if args.profile else None
                if profiler:profiler.enable()
                result=PoseSolver(store,config).solve(vision,matching)
                if profiler:
                    profiler.disable()
                    with (OUTPUT/f'{group}_{case}_profile.txt').open('w',encoding='utf-8') as stream:pstats.Stats(profiler,stream=stream).sort_stats('cumulative').print_stats(40)
                (OUTPUT/f'{group}_{case}.json.gz').write_bytes(gzip.compress((result.model_dump_json()+'\n').encode('utf-8'),compresslevel=6,mtime=0))
                record=summarize(case,result,hashes);summary.append(record)
                print(json.dumps(dict(group=group,case=case,seconds=result.elapsed_seconds,points=record['searched_points'],preferred=record['preferred_regions'],feasible_km2=result.feasible_area_m2/1e6,preferred_km2=result.preferred_area_m2/1e6),ensure_ascii=False),flush=True)
            (OUTPUT/f'{group}_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not args.group and not args.case:
        paths=[OUTPUT/f'{g}_{c}.json.gz' for g in GROUPS for c in CASES]+[OUTPUT/f'{g}_summary.json' for g in GROUPS]
        source=sorted((ROOT/'src/geophotoloc/localization').glob('*.py'))+[ROOT/'src/geophotoloc/models/pose.py',Path(__file__).resolve()]
        manifest=dict(artifacts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source},python=sys.version,platform=platform.platform())
        (OUTPUT/'run_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
