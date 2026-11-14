"""Image-space overlays and Folium presentation, with fully local JS/CSS assets."""
import base64
from html import escape
from io import BytesIO
import json
from pathlib import Path

import folium
from branca.element import Element
from PIL import Image,ImageDraw,ImageFont
from pyproj import Geod

ASSETS=Path(__file__).parent/'assets'
COLORS=('#2563eb','#dc2626','#059669','#9333ea','#d97706','#0891b2','#be185d','#4f46e5')
STATUS_LABELS={'SUCCESS':'候选求解完成','AMBIGUOUS':'存在多个可能机位或身份',
               'INSUFFICIENT_EVIDENCE':'可靠地标或顺序证据不足','NO_FEASIBLE_POSE':'当前假设和搜索范围内无可行采样',
               'SEARCH_LIMITED':'搜索预算、细化或输出范围受限'}


def annotate_image(jpeg,vision):
    with Image.open(BytesIO(jpeg)) as source:
        image=source.convert('RGB').copy()
    expected=vision.image.processed_size
    if image.size!=(expected.width,expected.height):
        raise ValueError('标注图片必须与预处理后的识别尺寸一致')
    draw=ImageDraw.Draw(image)
    font=None
    for path in ('C:/Windows/Fonts/msyh.ttc','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if Path(path).exists():
            font=ImageFont.truetype(path,max(12,min(22,image.width//65)))
            break
    font=font or ImageFont.load_default()
    occupied=[]
    for index,item in enumerate(vision.landmarks):
        color='#d97706' if item.identity_uncertain else COLORS[index%len(COLORS)]
        box=item.bbox
        if box is None:
            continue
        rectangle=(round(box.x_min*image.width),round(box.y_min*image.height),
                   round(box.x_max*image.width),round(box.y_max*image.height))
        draw.rectangle(rectangle,outline=color,width=max(2,image.width//500))
        cx,cy=round(item.x*image.width),round(item.y*image.height)
        draw.line((cx-5,cy,cx+5,cy),fill=color,width=2)
        draw.line((cx,cy-5,cx,cy+5),fill=color,width=2)
        text=f'{item.id} {item.name[:48]}' + (' · 身份待确认' if item.identity_uncertain else '')
        bounds=draw.textbbox((0,0),text,font=font)
        width,height=min(bounds[2]-bounds[0]+8,image.width),bounds[3]-bounds[1]+10
        x=min(max(0,rectangle[0]),max(0,image.width-width))
        y=max(0,rectangle[1]-height)
        for _ in range(len(occupied)+1):
            if not any(x<ox+ow and x+width>ox and y<oy+oh and y+height>oy for ox,oy,ow,oh in occupied):
                break
            y=min(image.height-height,y+height+2)
        draw.rectangle((x,y,x+width,y+height),fill='#fff9ed',outline=color,width=1)
        draw.text((x+4,y+3-bounds[1]),text,font=font,fill='#172033')
        occupied.append((x,y,width,height))
    output=BytesIO();image.save(output,format='PNG')
    return output.getvalue()


def build_map(result, *, offline=True, focus=None, sightlines=False):
    m=folium.Map(location=[35,105],zoom_start=4,tiles=None,control_scale=True)
    # No global Folium class mutation: each session's map owns its dependencies.
    m.default_js=[];m.default_css=[]
    root=m.get_root()
    root.header.add_child(Element('<style>.leaflet-control-zoom a{width:44px!important;height:44px!important;line-height:44px!important}</style>'))
    root.header.add_child(Element('<style>'+ (ASSETS/'leaflet.css').read_text(encoding='utf-8')+'</style>'))
    for name in ('leaflet.js','jquery.js'):
        root.header.add_child(Element('<script>'+ (ASSETS/name).read_text(encoding='utf-8')+'</script>'))
    if not offline:
        folium.TileLayer('OpenStreetMap',name='OSM 底图').add_to(m)
    entities={}
    for match in result.matching.matches:
        for candidate in match.candidates:
            entity=candidate.entity
            entities[entity.id]=entity
            text=(f'<b>{escape(entity.name)}</b><br>{escape(entity.id)}<br>'
                  f'图像对象：{escape(match.image_landmark_id)}<br>检索分：{candidate.score:.3f}（非概率）<br>'
                  f'命中名称：{escape(candidate.matched_query)}<br>身份尚未确认')
            folium.CircleMarker([entity.location.latitude,entity.location.longitude],radius=5,
                                color=COLORS[len(entities)%len(COLORS)],fill=True,
                                tooltip=escape(entity.name),popup=folium.Popup(text,max_width=320)).add_to(m)
    for index,region in enumerate(result.localization.regions):
        color=COLORS[index%len(COLORS)]
        layer=folium.FeatureGroup(name=f'{index+1}. {region.id}')
        properties=dict(区域=region.id,启发式分=region.best_score.score,面积平方米=round(region.area_m2),
                        满足=region.best_score.satisfied,冲突=region.best_score.conflicts,
                        不可判定=region.best_score.indeterminate,边界受限=region.touches_search_boundary)
        folium.GeoJson({'type':'Feature','geometry':region.geometry,'properties':properties},
                       style_function=lambda feature,c=color:{'color':c,'weight':2,'fillOpacity':.17},
                       tooltip=folium.GeoJsonTooltip(fields=list(properties))).add_to(layer)
        location=region.best_location
        folium.CircleMarker([location.latitude,location.longitude],radius=5,color=color,fill=True,
                            tooltip=f'搜索代表点 {index+1}（非已确认拍摄点）',
                            popup=f'朝向假设 {region.heading:.1f}°；非精确定位').add_to(layer)
        if region.heading is not None:
            lon,lat,_=Geod(ellps='WGS84').fwd(location.longitude,location.latitude,region.heading,90)
            folium.PolyLine([[location.latitude,location.longitude],[lat,lon]],color=color,weight=3,
                            tooltip=f'相机估计朝向 {region.heading:.1f}°').add_to(layer)
            folium.Marker([lat,lon],icon=folium.DivIcon(html=f'<span style="display:block;color:{color};font-size:20px;transform:rotate({region.heading}deg)">▲</span>')).add_to(layer)
        if sightlines:
            for entity_id in region.assignments.values():
                if entity_id in entities:
                    target=entities[entity_id].location
                    folium.PolyLine([[location.latitude,location.longitude],[target.latitude,target.longitude]],
                                    color=color,weight=1,dash_array='5,5').add_to(layer)
        layer.add_to(m)
    chosen=[r for r in result.localization.regions if focus is None or r.id==focus]
    if chosen:
        west=min(r.bounds_wgs84[0] for r in chosen);south=min(r.bounds_wgs84[1] for r in chosen)
        east=max(r.bounds_wgs84[2] for r in chosen);north=max(r.bounds_wgs84[3] for r in chosen)
        m.fit_bounds([[south,west],[north,east]],padding=(20,20))
    elif entities:
        locations=[(e.location.latitude,e.location.longitude) for e in entities.values()]
        m.fit_bounds(locations,padding=(40,40),max_zoom=16)
    folium.LayerControl(collapsed=True).add_to(m)
    root.html.add_child(Element('<div style="position:absolute;bottom:2px;left:8px;z-index:999;background:white;color:#222;font-size:11px">'
                                '© OpenStreetMap contributors / ODbL · '+('离线几何图，无网络底图' if offline else 'OSM 底图')+'</div>'))
    return m


def download_payloads(result):
    return {'json':result.model_dump_json(indent=2).encode('utf-8'),
            'geojson':json.dumps(result.localization.geojson,ensure_ascii=False,indent=2).encode('utf-8'),
            'annotated_png':annotate_image(result.processed_jpeg,result.vision)}
