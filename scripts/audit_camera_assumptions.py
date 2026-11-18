"""Legacy post-solve camera-model diagnostics, never a localization algorithm."""
import json,math
from pathlib import Path
from geophotoloc.models import GeoPoint,VisionExtractionResult
from geophotoloc.models.maps import MapMatchingResult
from geophotoloc.geometry.coordinates import LocalCoordinateSystem
from geophotoloc.geometry.bearing import bearing,signed_angle_difference
from run_camera_benchmark import OUT,save
from diagnose_camera_benchmark import verify_manifest


def point_pair_implied_fov(x1,x2,angular_separation_deg,principal=.5):
 # Closed-form consistency diagnostic. Same-side rays can have two roots;
 # return the smaller admissible one, without assuming global monotonicity.
 u,v=2*(x1-principal),2*(x2-principal)
 delta=angular_separation_deg
 if abs(u-v)<1e-12 or not 0<delta<180:return None
 if abs(delta-90)<1e-9:
  roots=[math.sqrt(-1/(u*v))] if u*v<0 else []
 else:
  tangent=math.tan(math.radians(delta));a=u*v*tangent;b=-abs(u-v);c=tangent
  if abs(a)<1e-12:roots=[-c/b]
  else:
   discriminant=b*b-4*a*c
   roots=[] if discriminant<0 else [(-b+math.sqrt(discriminant))/(2*a),(-b-math.sqrt(discriminant))/(2*a)]
 fovs=[]
 for t in roots:
  if t<=0:continue
  fov=math.degrees(2*math.atan(t))
  actual=abs(math.degrees(math.atan(u*t)-math.atan(v*t)))
  if 1<=fov<=169 and abs(actual-delta)<1e-7:fovs.append(fov)
 return min(fovs,default=None)


def main():
 verify_manifest(OUT)
 refs=json.loads((OUT/'dataset_references.json').read_text(encoding='utf-8'))['samples'];rows=[]
 for key in ('legacy_beijing_cbd','legacy_north_bund'):
  ref=next(r for r in refs if r['id']==key)['reference']
  system=LocalCoordinateSystem(GeoPoint(latitude=ref['latitude'],longitude=ref['longitude']))
  vision=VisionExtractionResult.model_validate_json((OUT/'inputs'/f'{key}.vision.json').read_bytes())
  matching=MapMatchingResult.model_validate_json((OUT/'inputs'/f'{key}.matches.json').read_bytes())
  observations={o.id:o for o in vision.landmarks};targets={m.image_landmark_id:m.candidates[0].entity for m in matching.matches if m.candidates}
  ids=['lm_1','lm_2'];a,b=[bearing((0,0),system.to_local(targets[k].location)) for k in ids];delta=abs(signed_angle_difference(a,b))
  x1,x2=[observations[k].x for k in ids]
  implied=point_pair_implied_fov(x1,x2,delta)
  rows.append(dict(case=key,ids=ids,names=[targets[k].name for k in ids],bearings_deg=[a,b],angular_separation_deg=delta,
     observed_x=[x1,x2],point_center_implied_fov_deg=implied,configured_fov_deg=[60,75,90,110,130],
     conclusion='Point-center angular separation implies a horizontal FOV outside the configured grid' if implied is not None and implied<60 else 'No below-grid point-center FOV diagnosed',
     limitations='Post-hoc model-consistency calculation only, no new pose or parameter change. Visible bbox centers need not project to OSM representative points; footprint, crop, camera self-report, identity and lens distortion remain uncertain. Not a measured focal length. For same-side rays the smaller admissible FOV is reported; a second solution can exist.'))
 save(OUT/'post_evaluation/camera_assumption_audit.json',rows);verify_manifest(OUT)
 print(json.dumps(rows,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
