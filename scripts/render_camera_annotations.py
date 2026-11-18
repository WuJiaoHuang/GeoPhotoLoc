"""Offline model-box inspection; labels are never sent back into inference."""
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from geophotoloc.models import VisionExtractionResult
from run_camera_benchmark import OUT

def main():
 font_path=Path('C:/Windows/Fonts/msyh.ttc')
 font=ImageFont.truetype(str(font_path),18) if font_path.exists() else ImageFont.load_default()
 for p in sorted((OUT/'inputs').glob('*.vision.json')):
  key=p.name.removesuffix('.vision.json');image_path=OUT/'images'/f'{key}.jpg'
  if not image_path.exists():continue
  result=VisionExtractionResult.model_validate_json(p.read_bytes())
  with Image.open(image_path) as src:
   im=src.convert('RGB');draw=ImageDraw.Draw(im)
   for lm in result.landmarks:
    b=lm.bbox;xy=(b.x_min*im.width,b.y_min*im.height,b.x_max*im.width,b.y_max*im.height)
    draw.rectangle(xy,outline='yellow',width=2)
    label=lm.id+' '+lm.name[:32]
    draw.text((max(0,xy[0]),max(0,xy[1]-22)),label,font=font,fill='yellow',stroke_width=1,stroke_fill='black')
    x,y=lm.x*im.width,lm.y*im.height;draw.ellipse((x-3,y-3,x+3,y+3),fill='red')
   draw.text((6,im.height-26),'Model predictions / source and license: ATTRIBUTION.md',font=font,fill='white',stroke_width=1,stroke_fill='black')
   out=OUT/'annotations'/f'{key}.jpg';out.parent.mkdir(exist_ok=True);im.save(out,quality=88)
 print('Annotations saved; geometry and API not invoked')

if __name__=='__main__':main()
