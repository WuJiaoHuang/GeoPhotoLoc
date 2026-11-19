"""Offline refinement display. References load only through explicit evaluation UI."""
import base64,gzip,json
from html import escape
from pathlib import Path
import folium
from shapely.geometry import shape
from geophotoloc.models import VisionExtractionResult,PoseLocalizationResult,MapMatchingResult,GeoPoint
from geophotoloc.models.refinement import SpatialRefinementResult,ReliableRefinementResult
from geophotoloc.vision import prepare_image
from .pipeline import DemoResult
from .visualization import build_map,annotate_image

ROOT=Path(__file__).resolve().parents[3]
OUTPUT=ROOT/'docs/evaluation/stage5_2'
DATA=ROOT/'docs/evaluation/real_camera_diagnostics'
CONSTRAINT_LABELS={'S0':'地标身份与地图分布；固定距离和共同网格；不按图像关系排名',
 'S1':'加入可靠左右关系；朝向未知；重叠与身份不明保留歧义',
 'S2':'加入轮廓、视场、投影和站立约束；有界优选并保留歧义'}
CONSTRAINT_LABELS.update({'S1-R':'仅 HARD 冲突排除；SOFT 只诊断；UNKNOWN 中立（与 S1 并列）',
 'S2-R':'从 S1-R 继续完整几何精化；评分与预算保持不变'})
CONSTRAINT_LABELS.update({'A0':'相同有限语义初始范围（无排名）','A1':'自动图像关系软评分；集合不缩减','A2':'实际 F 有界优选区域；关系仅在原几何质量档内排序'})


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


def load_reliable_refinement_case(case):
    result=load_refinement_case(case)
    target=ROOT/'docs/evaluation/stage5_3/refinement'/f'{case}.json.gz'
    result.refinement=ReliableRefinementResult.model_validate_json(gzip.decompress(target.read_bytes())).model_dump(mode='json')
    result.provenance='Stage 5.3 冻结输入离线对照；S1/S1-R 并列，无新增视觉或地图请求。'
    return result


def load_automatic_refinement_case(case):
    from .order_comparison import compare_region_orders
    result=load_refinement_case(case);e=result.localization
    target=ROOT/'docs/evaluation/stage5_4'
    result.localization=PoseLocalizationResult.model_validate_json(gzip.decompress((target/'poses'/f'F_{case}.json.gz').read_bytes()))
    result.refinement=json.loads(gzip.decompress((target/'refinement'/f'{case}.json.gz').read_bytes()))
    result.refinement['order_comparison']=compare_region_orders(e,result.localization)
    result.provenance='Stage 5.4 纯自动 F 组冻结离线结果；无人工身份输入，无新增模型请求。'
    return result


def build_refinement_map(result,*,offline=True,reference=None,focus=None):
    m=build_map(result,offline=offline,show_candidates=False,focus=focus)
    automatic=result.refinement.get('version')=='stage5.4'
    colors={'S0':'#2563eb','S1':'#d97706','S1-R':'#0891b2','S2':'#059669','S2-R':'#db2777','A0':'#2563eb','A1':'#d97706','A2':'#059669'}
    for layer in result.refinement['layers']:
        g=shape(layer['geometry'])
        if g.is_empty:continue
        name={'S0':'S0 语义初始范围（无排名）','S1':'S1 原空间关系精化（并列对照）','S1-R':'S1-R 三级可靠性关系精化（并列对照）','S2':'S2 原完整几何（从 S1）','S2-R':'S2-R 完整几何（从 S1-R）',
              'A0':'A0 语义初始范围','A1':'A1 自动关系软评分（范围保持）','A2':'A2 实际 F 候选优选区域（非物理可行层）'}[layer['stage']]
        group=folium.FeatureGroup(name=name,show=layer['stage'] in {'S2','A2'})
        props=dict(阶段=layer['stage'],面积km2=round(layer['area_m2']/1e6,4),说明=CONSTRAINT_LABELS[layer['stage']])
        folium.GeoJson(dict(type='Feature',geometry=layer['geometry'],properties=props),
           style_function=lambda _,c=colors[layer['stage']]:dict(color=c,weight=2,fillOpacity=.14),
           tooltip=folium.GeoJsonTooltip(fields=list(props))).add_to(group)
        group.add_to(m)
    if automatic:
        group=folium.FeatureGroup(name='F 排名与已有代表样点（非确认机位）',show=True)
        for i,r in enumerate(result.localization.regions,1):
            folium.CircleMarker([r.best_location.latitude,r.best_location.longitude],radius=4,color='#9333ea',tooltip=f'F #{i} {r.id}；原几何 {r.best_score.score}；关系 {r.automatic_relation_score}').add_to(group)
        group.add_to(m)
    physical=folium.FeatureGroup(name='物理可行层（原 E/F 相同，非精确位置）' if automatic else 'E 物理可行层（非精确位置）',show=False)
    for r in result.localization.feasible_regions:
        folium.GeoJson(r.geometry,style_function=lambda _:dict(color='#64748b',fillOpacity=.04,weight=1,dashArray='5,5')).add_to(physical)
    physical.add_to(m)
    preferred=folium.FeatureGroup(name='F 启发式优选（即 A2）' if automatic else 'E 启发式优选（未额外硬筛 S1）',show=False)
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
    if result.refinement.get('version')=='stage5.3':
        st.caption('S1 与 S1-R 是并列实验；S2 从 S1、S2-R 从 S1-R 继续。SOFT 分数仅供诊断，不改变覆盖；缺少独立身份和完整可见证据时允许零 HARD、零收缩。')
    rows=[]
    s0=next(l['area_m2'] for l in result.refinement['layers'] if l['stage'] in {'S0','A0'})
    for layer in result.refinement['layers']:
        reduction=layer['reduction_from_previous']
        rows.append({'层次':layer['stage'],'面积 km²':round(layer['area_m2']/1e6,4),'相对上一层缩小':None if reduction is None else f'{reduction:.1%}',
          '相对 S0 缩小':None if not s0 else f"{1-layer['area_m2']/s0:.1%}",
          'HARD/SOFT/UNKNOWN 点关系计数':'/'.join(str(layer['relation_counts'].get(k,0)) for k in ('HARD','SOFT','UNKNOWN')) if 'relation_counts' in layer else None,
          '实际网格点':layer['actual_points'],'通过点':layer['passed_points'],'关系数':layer['reliable_relations'],'使用约束':CONSTRAINT_LABELS[layer['stage']]})
    st.dataframe(rows,hide_index=True)
    if result.refinement.get('version')=='stage5.4':
        st.caption('A1 只增加连续关系评分，面积保持；A2 直接显示 F 输出。关系分数不是概率；无有效关系时回退 E。')
        st.write('自动空间关系得分分布',result.refinement['distribution'])
        st.dataframe([{'F排名':i,'区域':r.id,'几何分':r.best_score.score,'自动关系分':r.automatic_relation_score,'独立可靠地标':r.best_score.reliable_landmark_count} for i,r in enumerate(result.localization.regions,1)],hide_index=True)
        if 'order_comparison' in result.refinement:
            st.dataframe(result.refinement['order_comparison']['regions'],hide_index=True)
        with st.expander('图像左右关系及逐身份自动证据'):
            st.json([dict(身份=h.id,关系=[{k:v for k,v in r.items() if k not in {'consistency','weighted_scores','determined'}} for r in h.automatic_relation_audit.get('relations',[])]) for h in result.localization.hypotheses])
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
    version=st.selectbox('空间关系对照版本',['Stage 5.2 历史','Stage 5.3 可靠性分级','Stage 5.4 自动关系 F'],key='refinement_version')
    if version=='Stage 5.4 自动关系 F':
        if not (ROOT/'docs/evaluation/stage5_4/refinement'/f'{case}.json.gz').exists():
            st.warning('此案例尚无 Stage 5.4 冻结输出。');return
        result=load_automatic_refinement_case(case)
    elif version=='Stage 5.3 可靠性分级':
        if not (ROOT/'docs/evaluation/stage5_3/refinement'/f'{case}.json.gz').exists():
            st.warning('此案例尚无 Stage 5.3 冻结输出。');return
        result=load_reliable_refinement_case(case)
    else:result=load_refinement_case(case)
    st.info(result.provenance)
    st.image(annotate_image(result.processed_jpeg,result.vision),caption='缓存真实照片与地标识别框；照片作者、来源及许可见下方链接。',width=850)
    st.dataframe([{'图像ID':o.id,'识别名称':o.name,'模型自报身份':'不确定' if o.identity_uncertain else '给出名称（未独立核验）','地图候选数':len(next(m for m in result.matching.matches if m.image_landmark_id==o.id).candidates)} for o in result.vision.landmarks],hide_index=True)
    show=st.checkbox('独立评估模式：显示参考机位',value=False,key='show_refinement_reference')
    if result.refinement.get('version')=='stage5.4':
        st.dataframe([{'图像ID':m.image_landmark_id,'地图候选':c.entity.name,'实体ID':c.entity.id,'名称相似度':c.score_components.get('name_similarity'),'候选分（非概率）':c.score} for m in result.matching.matches for c in m.candidates],hide_index=True)
    reference=load_reference_for_evaluation(case) if show else None
    if show:st.caption('紫红点为来源自报相机位置，仅在求解后的只读评估显示。')
    render_refinement(result,reference=reference)
    st.download_button('下载空间精化 GeoJSON',json.dumps(result.refinement['geojson'],ensure_ascii=False).encode(),file_name='spatial_refinement.geojson',mime='application/geo+json')
    st.markdown('[照片作者与许可](https://github.com/WuJiaoHuang/GeoPhotoLoc/blob/main/docs/evaluation/real_camera_diagnostics/ATTRIBUTION.md) · © OpenStreetMap contributors / ODbL')
