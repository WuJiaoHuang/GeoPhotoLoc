"""Offline refinement display. References load only through explicit evaluation UI."""
import base64,gzip,json
from html import escape
from pathlib import Path
import folium
from shapely.geometry import shape
from geophotoloc.models import VisionExtractionResult,PoseLocalizationResult,MapMatchingResult,GeoPoint
from geophotoloc.models.refinement import SpatialRefinementResult
from geophotoloc.vision import prepare_image
from .pipeline import DemoResult
from .visualization import build_map,annotate_image

ROOT=Path(__file__).resolve().parents[3]
OUTPUT=ROOT/'docs/evaluation/stage5_2'
DATA=ROOT/'docs/evaluation/real_camera_diagnostics'
CONSTRAINT_LABELS={'S0':'地标身份与地图分布；固定距离和共同网格；不按图像关系排名',
 'S1':'加入可靠左右关系；朝向未知；重叠与身份不明保留歧义',
 'S2':'加入轮廓、视场、投影和站立约束；有界优选并保留歧义'}


def available_cases():
    return sorted(p.stem.removesuffix('.json') for p in (OUTPUT/'refinement').glob('*.json.gz'))


def load_refinement_case(case):
    if case not in available_cases():raise ValueError('Unknown cached refinement case')
    vision=VisionExtractionResult.model_validate_json((DATA/'inputs'/f'{case}.vision.json').read_bytes())
    matching=MapMatchingResult.model_validate_json((DATA/'inputs'/f'{case}.matches.json').read_bytes())
    pose=PoseLocalizationResult.model_validate_json(gzip.decompress((OUTPUT/'poses'/f'E_{case}.json.gz').read_bytes()))
    refinement=SpatialRefinementResult.model_validate_json(gzip.decompress((OUTPUT/'refinement'/f'{case}.json.gz').read_bytes())).model_dump(mode='json')
    prepared=prepare_image(DATA/'images'/f'{case}.jpg')
    if prepared.metadata.processed_size!=vision.image.processed_size:raise ValueError('Image dimensions changed')
    return DemoResult(mode='offline',provenance='Stage 5.2 离线复现；未调用视觉或地图服务，未用参考机位求解。',
        vision=vision,matching=matching,localization=pose,refinement=refinement,processed_jpeg=base64.b64decode(prepared.data_url.split(',',1)[1]))


def load_reference_for_evaluation(case):
    rows=json.loads((DATA/'dataset_references.json').read_text(encoding='utf-8'))['samples']
    row=next(r for r in rows if r['id']==case)
    return GeoPoint(latitude=row['reference']['latitude'],longitude=row['reference']['longitude'])


def build_refinement_map(result,*,offline=True,reference=None,focus=None):
    m=build_map(result,offline=offline,show_candidates=False,focus=focus)
    colors={'S0':'#2563eb','S1':'#d97706','S2':'#059669'}
    for layer in result.refinement['layers']:
        g=shape(layer['geometry'])
        if g.is_empty:continue
        name={'S0':'S0 语义初始范围（无排名）','S1':'S1 加入可靠左右关系（无排名）','S2':'S2 完整几何与有界优选'}[layer['stage']]
        group=folium.FeatureGroup(name=name,show=layer['stage']=='S2')
        props=dict(阶段=layer['stage'],面积km2=round(layer['area_m2']/1e6,4),说明=CONSTRAINT_LABELS[layer['stage']])
        folium.GeoJson(dict(type='Feature',geometry=layer['geometry'],properties=props),
           style_function=lambda _,c=colors[layer['stage']]:dict(color=c,weight=2,fillOpacity=.14),
           tooltip=folium.GeoJsonTooltip(fields=list(props))).add_to(group)
        group.add_to(m)
    physical=folium.FeatureGroup(name='E 物理可行层（非精确位置）',show=False)
    for r in result.localization.feasible_regions:
        folium.GeoJson(r.geometry,style_function=lambda _:dict(color='#64748b',fillOpacity=.04,weight=1,dashArray='5,5')).add_to(physical)
    physical.add_to(m)
    preferred=folium.FeatureGroup(name='E 启发式优选（未额外硬筛 S1）',show=False)
    for r in result.localization.regions:
        folium.GeoJson(r.geometry,style_function=lambda _:dict(color='#9333ea',fillOpacity=.10,weight=1)).add_to(preferred)
    preferred.add_to(m)
    if reference is not None:
        folium.CircleMarker([reference.latitude,reference.longitude],radius=7,color='#be185d',fill=True,tooltip='独立评估参考机位（Q2自报，未用于推理）').add_to(m)
    # Replace the original control so the new layer controls are included once.
    for name,item in list(m._children.items()):
        if isinstance(item,folium.map.LayerControl):del m._children[name]
    folium.LayerControl(collapsed=False).add_to(m)
    return m


def render_refinement(result,*,offline=True,reference=None,show_map=True):
    import streamlit as st
    from streamlit_folium import st_folium
    st.subheader('语义检索 → 空间关系 → 完整几何精化')
    st.caption('地图圆点为检索地标，面状区域为可能机位；地标中心不是摄影师位置。')
    st.caption('S0/S1 无机位排名；S2 是在同一网格上施加 S1 的受控精化层，与保持软关系的 E 优选结果分开显示。')
    rows=[]
    for layer in result.refinement['layers']:
        reduction=layer['reduction_from_previous']
        rows.append({'层次':layer['stage'],'面积 km²':round(layer['area_m2']/1e6,4),'相对上一层缩小':None if reduction is None else f'{reduction:.1%}',
          '实际网格点':layer['actual_points'],'通过点':layer['passed_points'],'关系数':layer['reliable_relations'],'使用约束':CONSTRAINT_LABELS[layer['stage']]})
    st.dataframe(rows,hide_index=True)
    if not any(layer['actual_points'] for layer in result.refinement['layers']):st.info('独立锚点或身份不足，三层均无机位输出；面积为0不表示零误差。')
    st.warning('区域缩小不等于定位成功。重叠轮廓、身份不确定或不可靠关系会保守保留；数量上限仍可能遗漏并列高分模式。自报机位不是测量真值。')
    if show_map:st_folium(build_refinement_map(result,offline=offline,reference=reference),height=650,use_container_width=True,returned_objects=[],key='refinement-map')
    with st.expander('截断证据与适用限制'):
        st.write(result.refinement['warnings'])
        st.json([{'身份':h.id,'保留决策':h.selection_audit} for h in result.localization.hypotheses])


def render_offline_refinement():
    import streamlit as st
    cases=available_cases()
    if not cases:
        st.warning('空间精化离线结果尚未生成，请运行 scripts/run_stage52.py。');return
    default=st.query_params.get('case','photo_02')
    case=st.selectbox('空间精化真实案例',cases,index=cases.index(default) if default in cases else 0,key='refinement_case')
    result=load_refinement_case(case)
    st.info(result.provenance)
    st.image(annotate_image(result.processed_jpeg,result.vision),caption='缓存真实照片与地标识别框；照片作者、来源及许可见下方链接。',width=850)
    st.dataframe([{'图像ID':o.id,'识别名称':o.name,'模型自报身份':'不确定' if o.identity_uncertain else '给出名称（未独立核验）','地图候选数':len(next(m for m in result.matching.matches if m.image_landmark_id==o.id).candidates)} for o in result.vision.landmarks],hide_index=True)
    show=st.checkbox('独立评估模式：显示参考机位',value=False,key='show_refinement_reference')
    reference=load_reference_for_evaluation(case) if show else None
    if show:st.caption('紫红点为来源自报相机位置，仅在求解后的只读评估显示。')
    render_refinement(result,reference=reference)
    st.download_button('下载空间精化 GeoJSON',json.dumps(result.refinement['geojson'],ensure_ascii=False).encode(),file_name='spatial_refinement.geojson',mime='application/geo+json')
    st.markdown('[照片作者与许可](https://github.com/WuJiaoHuang/GeoPhotoLoc/blob/main/docs/evaluation/real_camera_diagnostics/ATTRIBUTION.md) · © OpenStreetMap contributors / ODbL')
