"""Freeze independently reviewed photos/references and neutral inference inputs."""
import hashlib,json
from io import BytesIO
from pathlib import Path
from PIL import Image,ImageOps
from evaluate_stage5_1a import load_inputs
from collect_camera_dataset import OUT,ROOT,save,digest

# Human review from the downloaded contact sheets + source categories/captions,
# established before VLM requests. These labels are evaluation-only.
REVIEW={
 'photo_01':['东方明珠','上海环球金融中心','金茂大厦','上海中心大厦'],
 'photo_02':['东方明珠','上海环球金融中心','金茂大厦','上海中心大厦'],
 'photo_03':['东方明珠','上海环球金融中心','金茂大厦','上海中心大厦'],
 'photo_04':['上海环球金融中心','金茂大厦','震旦国际大楼'],
 'photo_05':['上海环球金融中心','金茂大厦','震旦国际大楼'],
 'photo_06':['东方明珠','上海环球金融中心','上海中心大厦'],
 'photo_07':['东方明珠','上海环球金融中心','金茂大厦','上海中心大厦'],
 'photo_08':['中央电视台总部大楼','中国尊'],
 'photo_09':[],
 'photo_10':['广州国际金融中心','星海音乐厅'],
 'photo_11':['广州塔'],
 'photo_12':['广州国际金融中心','广州周大福金融中心'],
}

def main():
 if (OUT/'dataset_freeze.json').exists():raise SystemExit('Dataset already frozen; do not overwrite')
 references=json.loads((OUT/'dataset_references.json').read_text(encoding='utf-8'));samples=[]
 for row in references['samples']:
  key=row['id'];row['human_reference_landmarks']=REVIEW[key]
  row['visual_review']='Distinctive silhouettes checked on acquired image and Commons caption/categories; incomplete target list, not model output'
  row['eligibility']='multi_landmark' if len(REVIEW[key])>=2 else 'single_or_unresolved_identity_stress'
  row['context']='night' if key in ('photo_01','photo_05') else 'sunrise' if key=='photo_11' else 'day'
  row['limitations']='Q2, no measured accuracy; skyline/time/occlusion differences; no assertion of surveyed truth'
  if key=='photo_03':row['limitations']+='; Shanghai Tower still under construction'
  if key=='photo_12':row['limitations']+='; distant highway view, may exceed fixed 5km model or current map coverage'
  samples.append({k:row[k] for k in ('id','file','image_sha256')})
 save(OUT/'dataset_references.json',references)
 legacy_refs=json.loads((ROOT/'docs/evaluation/stage5/camera_truth.json').read_text(encoding='utf-8'))
 for key,file in [('beijing_cbd','docs/evaluation/stage2_1/images/beijing_cbd.jpg'),('north_bund','docs/evaluation/stage5/north_bund.jpg')]:
  target='legacy_'+key;path=OUT/'images'/f'{target}.jpg'
  with Image.open(ROOT/file) as im:ImageOps.exif_transpose(im).convert('RGB').save(path,quality=92)
  vision,matching,hashes=load_inputs(key)
  save(OUT/'inputs'/f'{target}.vision.json',vision.model_dump(mode='json'))
  save(OUT/'inputs'/f'{target}.matches.json',matching.model_dump(mode='json'))
  samples.append(dict(id=target,file=f'images/{target}.jpg',image_sha256=digest(path.read_bytes())))
  ref=next(x for x in legacy_refs if x['case']==key)
  references['samples'].append(dict(id=target,split='legacy_diagnostic',source_group=target,reference={**ref,'quality':'Q2_SELF_REPORTED_UNVERIFIED','accuracy_m':None},source_url=ref['source'],file=f'images/{target}.jpg',historical_input_hashes=hashes,eligibility='legacy'))
 save(OUT/'dataset_references.json',references)
 save(OUT/'inference_inputs.json',samples)
 save(OUT/'dataset_freeze.json',dict(images={s['id']:s['image_sha256'] for s in samples},reference_sha256=digest((OUT/'dataset_references.json').read_bytes()),inference_inputs_sha256=digest((OUT/'inference_inputs.json').read_bytes()),policy='Split grouped by photographer/outing before any vision calls; no tuning in this phase. Evaluation cannot change inference artifacts.'))
 print('Frozen',len(samples)-2,'new photos; 2 legacy cases; dev/holdout=6/6; 10 multi-landmark + 2 stress; no surveyed coordinates')

if __name__=='__main__':main()
