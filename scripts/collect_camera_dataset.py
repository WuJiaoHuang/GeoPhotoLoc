"""Bounded Commons acquisition. References are never imported by inference."""
import hashlib, html, json, re, time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
import httpx
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evaluation/real_camera_diagnostics'
API='https://commons.wikimedia.org/w/api.php'
CANDIDATES=[
 ('Shanghai Skyline 2020.jpg','shihu2020','development'),
 ('Shanghai, China skyline.jpg','quintin2024','development'),
 ('Shanghai Skyline from the Bund.jpg','wilson2014','development'),
 ('Flickr - Shinrya - Shanghai Skyline at Day.jpg','shinrya2012','holdout'),
 ('Flickr - Shinrya - Shanghai Skyline HDR.jpg','shinrya2012','holdout'),
 ('20191112 Lujiazui skyline-2.jpg','lujiazui20191112','holdout'),
 ('20191112 Lujiazui skyline-13.jpg','lujiazui20191112','holdout'),
 ('Beijing Central Business District (20240826163226).jpg','howey2024','development'),
 ('Beijing CBD in 2026.jpg','renek2026','holdout'),
 ('Guangzhou skyline (6343573781).jpg','mcgill2011','development'),
 ('广州塔晨曦Scenery in Guangzhou, China - panoramio (1).jpg','jiang2010','development'),
 ('City Skyline, Shot on Xinhua Kuaisulu, Guangzhou.jpg','yikyuen2025','holdout'),
 ('Lujiazui Skyline from Bund.jpg','composite2008','reject_composite'),
 ('Shanghai Skyline 2012.jpg','questionable2012','review_questionable'),
]

def save(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def digest(data):return hashlib.sha256(data).hexdigest()

def clean(s):return html.unescape(re.sub('<[^>]+>','',s))

def camera_template(text):
 # Object location, Wikidata coordinates, and EXIF fields are deliberately ignored.
 match=re.search(r'\{\{[Ll]ocation(?: dec)?\s*\|\s*([-+0-9.]+)\s*\|\s*([-+0-9.]+)[^}]*\}\}',text)
 if not match:return None
 lat,lon=map(float,match.group(1,2))
 if not -90<=lat<=90 or not -180<=lon<=180:return None
 return dict(latitude=lat,longitude=lon,template=match.group(),kind='Commons Location template (camera position)')

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if (OUT/'dataset_freeze.json').exists():
  frozen=json.loads((OUT/'dataset_freeze.json').read_text(encoding='utf-8'))
  for key,sha in frozen['images'].items():
   if digest((OUT/'images'/f'{key}.jpg').read_bytes())!=sha:raise ValueError('Frozen image changed')
  print('Dataset already frozen and image hashes verified; no download or overwrite')
  return
 records=[];screen=[]
 with httpx.Client(timeout=45,follow_redirects=True,headers={'User-Agent':'GeoPhotoLocEvaluation/1.1 (bounded Commons camera benchmark)'}) as client:
  def query(params):
   # At most two GETs for a failed public metadata query; never VLM retries.
   for attempt in range(2):
    try:
     response=client.get(API,params={'action':'query','format':'json',**params});response.raise_for_status();return response.json()
    except (httpx.HTTPError,ValueError):
     if attempt:raise
     time.sleep(1)
  for index,(name,group,split) in enumerate(CANDIDATES,1):
   key=f'photo_{index:02d}';snapshot=OUT/'sources'/f'{key}.json'
   try:
    if snapshot.exists():meta=json.loads(snapshot.read_text(encoding='utf-8'))
    else:
     info=next(iter(query({'prop':'imageinfo','titles':'File:'+name,'iiprop':'url|extmetadata|sha1|size','iiurlwidth':1600})['query']['pages'].values()))
     rev=next(iter(query({'prop':'revisions','titles':'File:'+name,'rvprop':'ids|content','rvslots':'main'})['query']['pages'].values()))
     meta=dict(info=info,revision=rev,retrieved_at_utc=datetime.now(timezone.utc).isoformat());save(snapshot,meta)
    item=meta['info']['imageinfo'][0];ext={k:v['value'] for k,v in item['extmetadata'].items()}
    revision=meta['revision']['revisions'][0];text=revision['slots']['main']['*'];ref=camera_template(text)
    reason=None
    if split=='reject_composite':reason='Source explicitly describes a composite of four photos; unsuitable for pinhole comparison'
    elif split=='review_questionable':reason='No independently verified target identities within current bounded OSM areas; west-facing central-Shanghai view deferred, not proof its camera coordinate is wrong'
    elif not ref:reason='No explicit camera Location template; object/EXIF coordinates are insufficient'
    elif not any(k in ext.get('LicenseShortName','').lower() for k in ('cc by','cc0','public domain')):reason='No supported explicit reusable license'
    if reason:
     screen.append(dict(id=key,title=name,status='excluded',reason=reason));continue
    url=item.get('thumburl',item['url']);cache=ROOT/'.cache/real_camera_downloads'/f'{key}.jpg';cache.parent.mkdir(parents=True,exist_ok=True)
    if not cache.exists():
     r=client.get(url);r.raise_for_status();cache.write_bytes(r.content)
    data=cache.read_bytes()
    with Image.open(BytesIO(data)) as im:
     im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((1600,1600))
     path=OUT/'images'/f'{key}.jpg';path.parent.mkdir(exist_ok=True);im.save(path,quality=92)
     size=list(im.size)
    record=dict(id=key,file=f'images/{key}.jpg',split=split,source_group=group,title=name,
      source_url='https://commons.wikimedia.org/wiki/File:'+quote(name.replace(' ','_')),revision_id=revision['revid'],
      original_url=item['url'],download_url=url,author=clean(ext.get('Artist','')),license=ext.get('LicenseShortName'),license_url=ext.get('LicenseUrl'),
      downloaded_sha256=digest(data),image_sha256=digest(path.read_bytes()),downloaded_bytes=len(data),input_dimensions=size,
      modifications='Commons thumbnail resized to <=1600px, re-encoded JPEG; EXIF/GPS/IPTC removed; no crop',
      reference={**ref,'quality':'Q2_SELF_REPORTED_UNVERIFIED','accuracy_m':None,'quality_basis':'Explicit camera-position template, not surveyed; numeric precision is not accuracy; no asserted metre uncertainty'},
      metadata_snapshot_sha256=digest(snapshot.read_bytes()))
    records.append(record);screen.append(dict(id=key,title=name,status='acquired_pending_visual_review',reason='License and explicit camera template verified; visual eligibility review required'))
    print(key,'acquired',size,flush=True)
   except (httpx.HTTPError,ValueError,KeyError,OSError) as error:
    screen.append(dict(id=key,title=name,status='acquisition_failed',reason=type(error).__name__,http_status=getattr(getattr(error,'response',None),'status_code',None)))
    print(key,'failed',type(error).__name__,getattr(getattr(error,'response',None),'status_code',None),flush=True)
   time.sleep(.75)
   save(OUT/'screening.json',screen);save(OUT/'dataset_references.json',dict(samples=records,policy='Q1 independently surveyed; Q2 explicit self-reported camera position plausible but unverified; Q3 ambiguous/object-only excluded. No Q1 currently. Split grouped before vision calls.'))
 if not records:raise SystemExit('No qualified photo downloads')

if __name__=='__main__':main()
