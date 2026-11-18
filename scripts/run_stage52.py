"""Frozen-input E solves and same-grid S0/S1/S2 inference. No references/API."""
import argparse,gzip,hashlib,json,time
from pathlib import Path
from geophotoloc.maps import LandmarkStore
from geophotoloc.models import VisionExtractionResult
from geophotoloc.models.maps import MapMatchingResult,GeoBounds
from geophotoloc.models.pose import PoseLocalizationResult
from geophotoloc.localization import Stage52PoseSolver
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'docs/evaluation/real_camera_diagnostics'
OUT=ROOT/'docs/evaluation/stage5_2'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def read_pose(p):return PoseLocalizationResult.model_validate_json(gzip.decompress(p.read_bytes()))
def dump(p,result):
 p.parent.mkdir(parents=True,exist_ok=True);data=result.model_dump_json() if hasattr(result,'model_dump_json') else json.dumps(result,ensure_ascii=False,allow_nan=False)
 p.write_bytes(gzip.compress((data+'\n').encode(),compresslevel=9,mtime=0))
def trace_signature(pose):
 data=[dict(id=h.id,assignments=h.assignments,budget=h.budget,spacing=h.coarse_spacing_m,
  trace=[{k:t.get(k) for k in ('x','y','phase','feasible','score','outliers','components')} for t in h.sample_trace]) for h in pose.hypotheses]
 return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--solve-only',action='store_true');parser.add_argument('--refine-only',action='store_true');args=parser.parse_args()
 OUT.mkdir(parents=True,exist_ok=True)
 originals=json.loads((DATA/'inference_manifest.json').read_text(encoding='utf-8'))['artifacts']
 for name,digest in originals.items():
  if sha(DATA/name)!=digest:raise ValueError('Historical input/output changed')
 db=ROOT/'.cache/geophotoloc/maps.sqlite3'
 if sha(db)!=json.loads((DATA/'map_snapshot.json').read_text())['sha256']:raise ValueError('OSM snapshot differs')
 samples=json.loads((DATA/'inference_inputs.json').read_text(encoding='utf-8'))
 sources=list((ROOT/'src/geophotoloc/localization').glob('*.py'))+[ROOT/'src/geophotoloc/models/pose.py']
 source_hash={str(p.relative_to(ROOT)):sha(p) for p in sources}
 if args.solve_only:save(OUT/'solver_source_at_start.json',source_hash)
 checks=[]
 with LandmarkStore(db) as store:
  bounds={rid:GeoBounds.model_validate_json(store.connection.execute('SELECT bounds_json FROM regions WHERE id=?',(rid,)).fetchone()[0]) for rid in store.coverage_regions()}
  for sample in samples:
   case=sample['id'];vp=DATA/'inputs'/f'{case}.vision.json';mp=DATA/'inputs'/f'{case}.matches.json'
   if not vp.exists():checks.append(dict(case=case,status='vision_unavailable',reason='Original API timeout; no request made'));continue
   vision=VisionExtractionResult.model_validate_json(vp.read_bytes());matching=MapMatchingResult.model_validate_json(mp.read_bytes())
   d=read_pose(DATA/'poses'/f'joint_full_{case}.json.gz');path=OUT/'poses'/f'E_{case}.json.gz'
   if not path.exists():
    if args.refine_only:raise ValueError('E result missing')
    e=Stage52PoseSolver(store,d.config).solve(vision,matching);dump(path,e)
   else:e=read_pose(path)
   d_config=d.config.model_dump();e_config=e.config.model_dump();d_config.pop('selection_strategy');e_config.pop('selection_strategy')
   if d_config!=e_config or trace_signature(d)!=trace_signature(e):raise ValueError('D/E inputs, grids or scores diverged: '+case)
   if [r.model_dump(mode='json') for r in d.feasible_regions]!=[r.model_dump(mode='json') for r in e.feasible_regions]:raise ValueError('Physical Feasible changed')
   check=dict(case=case,status=e.status,vision_sha256=sha(vp),matching_sha256=sha(mp),D_sha256=sha(DATA/'poses'/f'joint_full_{case}.json.gz'),
      sample_trace_sha256=trace_signature(e),same_grid_scores_and_feasible=True,points=sum(h.searched_points for h in e.hypotheses),
      E_seconds=e.elapsed_seconds,E_regions=len(e.regions),E_preferred_m2=e.preferred_area_m2,
      discarded_modes=sum(sum(not x['retained'] and x['reason']!='covered_by_retained_mode' for x in h.selection_audit.get('decisions',[])) for h in e.hypotheses),
      omitted_top_quality_modes=sum(h.selection_audit.get('omitted_top_quality_modes',0) for h in e.hypotheses))
   if not args.solve_only:
    from geophotoloc.localization.spatial_refinement import build_spatial_refinement
    refinement=build_spatial_refinement(vision,matching,e,bounds)
    dump(OUT/'refinement'/f'{case}.json.gz',refinement)
    check['refinement_seconds']=refinement['elapsed_seconds']
   checks.append(check);save(OUT/'inference_checks.json',checks)
   print(json.dumps(check,ensure_ascii=False),flush=True)
 save(OUT/'inference_checks.json',checks)
 files=list((OUT/'poses').glob('*.gz'))+list((OUT/'refinement').glob('*.gz'))+[OUT/'inference_checks.json']
 save(OUT/('solve_manifest.json' if args.solve_only else 'inference_manifest.json'),dict(artifacts={str(p.relative_to(OUT)):sha(p) for p in files},
   historical_artifacts=originals,source_sha256=source_hash,map_sha256=sha(db),references_read=False))
 if args.solve_only and source_hash!={str(p.relative_to(ROOT)):sha(p) for p in sources}:raise ValueError('Solver source changed during solves')

if __name__=='__main__':main()
