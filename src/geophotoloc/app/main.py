"""Chinese Streamlit UI; algorithms and all I/O orchestration live in services."""
import hashlib
from pathlib import Path
import tempfile

import streamlit as st
from streamlit_folium import st_folium
from geophotoloc.config import VisionConfig,ConfigurationError
from geophotoloc.localization import PoseSearchConfig
from geophotoloc.maps.regions import REGIONS
from geophotoloc.app.demo_data import CASES,ROOT,load_case,load_camera_evaluations
from geophotoloc.app.pipeline import LocalizationPipeline,PipelineFailure,validate_upload
from geophotoloc.app.setup import setup_demo,database_status
from geophotoloc.app.visualization import STATUS_LABELS,build_map,download_payloads


def main():
    st.set_page_config(page_title='GeoPhotoLoc · 旅拍机位粗定位',layout='wide')
    st.title('GeoPhotoLoc — 基于地标空间关系的旅拍机位粗定位')
    st.caption('从照片中的地标与空间关系出发，展示可能机位区域和可核对的几何证据。')
    st.markdown('<style>button{min-height:44px}:focus-visible{outline:3px solid #2563eb!important;outline-offset:2px}</style>',unsafe_allow_html=True)
    mode=st.radio('演示模式',['离线案例','在线定位','空间精化离线'],index=2 if st.query_params.get('demo')=='refinement' else 0,horizontal=True,key='mode')
    if mode=='空间精化离线':
        from geophotoloc.app.refinement_demo import render_offline_refinement
        render_offline_refinement()
        return
    db=ROOT/'.cache/geophotoloc/maps.sqlite3'
    if mode=='离线案例':
        st.info('离线复现实验结果，非本次实时模型推理。')
        st.caption('地图数据覆盖：北京 CBD、广州珠江新城/广州塔、上海陆家嘴。离线不连接视觉模型或 Overpass。')
    else:
        coverage=database_status(db)
        st.caption('本地地图覆盖：'+('、'.join(coverage) if coverage else '尚未初始化'))
        try:
            config=VisionConfig.from_env()
            st.caption('模型：'+config.model+' · 配置已读取，连接未探测（页面加载不发送请求）')
        except ConfigurationError:
            config=None
            st.warning('尚未配置有效视觉参数。请在 .env 配置 API Key；页面不会自动请求模型。')
        if set(REGIONS)-set(coverage):
            st.info('在线地图覆盖尚未完整初始化；可运行 uv run python -m geophotoloc.cli demo-setup。离线案例无需初始化。')
            if st.button('初始化三个演示区域地图'):
                with st.spinner('按有限范围顺序初始化地图；不调用视觉模型…'):
                    status=setup_demo(db)
                st.session_state['_setup_result']=status
                st.rerun()
        if '_setup_result' in st.session_state:
            for item in st.session_state['_setup_result']:
                if item['status']=='failed':
                    st.error(item.get('message','地图初始化失败，可稍后重试，或继续使用离线案例。'))
                else:
                    st.caption(f"地图 {item['region']}：{item['status']}")
    left,right=st.columns([1,1.65],gap='large')
    result=None
    with left:
        if mode=='离线案例':
            case=st.selectbox('预置真实案例',list(CASES),key='case')
            case_id=CASES[case]
            try:
                result=load_case(case_id)
                st.image(str(ROOT/f'docs/evaluation/stage2_1/images/{case_id}.jpg'),caption='原始照片（未改写历史输出）',width='stretch')
            except (OSError,ValueError):
                st.error('离线素材缺失或格式错误，请确认完整克隆项目和 docs/evaluation 目录。')
        else:
            upload=st.file_uploader('上传旅游照片（JPEG / PNG / WebP，最大 20 MiB）',type=['jpg','jpeg','png','webp'])
            with st.expander('搜索参数'):
                use_automatic=st.checkbox('Stage 5.4 单图自动关系排序',value=True)
                use_refinement=st.checkbox('启用 Stage 5.2 空间精化',value=False)
                radius=st.number_input('地标分布外扩半径（米）',min_value=200,max_value=10000,value=2200,step=200,disabled=use_refinement)
                budget=st.number_input('最大搜索点数',min_value=100,max_value=100000,value=24000,step=1000)
                if use_refinement:st.caption('空间精化沿用固定 5 km 观察距离先验；外扩半径仅用于原定位模式。')
            signature=None
            upload_valid=False
            if upload:
                data=upload.getvalue()
                try:
                    validate_upload(data,upload.name)
                    signature=hashlib.sha256(data).hexdigest()
                    st.image(data,caption='上传原图',width='stretch')
                    upload_valid=True
                except PipelineFailure as error:
                    st.error(str(error))
            if st.button('开始定位',disabled=not upload_valid or config is None,type='primary'):
                if len(data)>20*1024*1024:
                    st.error('图片文件超过 20 MiB 限制。')
                else:
                    if '_pipeline' not in st.session_state:
                        st.session_state['_pipeline']=LocalizationPipeline(db,vision_config=config)
                    pipeline=st.session_state['_pipeline']
                    pipeline.vision_config=config
                    pipeline.automatic_relations=use_automatic
                    pipeline.search_config=PoseSearchConfig(search_radius_m=radius,max_total_points=budget)
                    if use_refinement:
                        from geophotoloc.localization import Stage52PoseSolver
                        pipeline.search_config=Stage52PoseSolver(None,pipeline.search_config).config.model_copy(update={'record_diagnostic_trace':True})
                    try:
                        with tempfile.TemporaryDirectory(prefix='geophotoloc-upload-') as folder:
                            path=Path(folder)/('upload'+Path(upload.name).suffix.lower())
                            path.write_bytes(data)
                            with st.spinner('识别地标 → 匹配地图 → 搜索候选区域…'):
                                st.session_state['_online_result']=pipeline.run(path)
                        st.session_state['_upload_signature']=signature
                    except PipelineFailure as error:
                        st.session_state.pop('_online_result',None)
                        st.error(str(error))
                    except Exception:
                        st.session_state.pop('_online_result',None)
                        st.error('本次处理未完成，请检查图片、本地地图和配置；未展示失败堆栈或敏感详情。')
            if signature and signature==st.session_state.get('_upload_signature'):
                result=st.session_state.get('_online_result')
                if result and result.cache_hit:
                    st.caption('已复用本会话同图片结果，本次未重复调用视觉模型。')
                elif result and result.vision_cache_hit:
                    st.caption('本次复用视觉识别，仅重新计算地图匹配和几何结果，没有再次请求模型。')
                if result and (result.localization.config.search_radius_m!=radius or result.localization.config.max_total_points!=budget):
                    st.caption('参数已改变，当前图仍为上次运行结果；点击开始定位后更新。')
        if result:
            st.subheader('视觉识别与图像位置')
            try:
                payloads=download_payloads(result)
                st.image(payloads['annotated_png'],caption='预处理后图片上的地标框与中心；琥珀色为身份待确认',width='stretch')
            except (OSError,ValueError):
                payloads=None
                st.error('标注或下载文件生成失败；请检查图片与结果尺寸。')
            if not result.vision.landmarks:
                st.warning('视觉模型没有提取到可用地标；这不代表地图数据库中没有建筑。')
            st.dataframe([{'ID':x.id,'名称':x.name,'身份候选':' / '.join(x.name_candidates),'身份':'待确认' if x.identity_uncertain else '模型给出具体名称（未独立确认）','x':x.x,'y':x.y} for x in result.vision.landmarks],hide_index=True)
    with right:
        if result:
            pose=result.localization
            st.subheader(STATUS_LABELS.get(pose.status,pose.status))
            st.caption(f'状态：{pose.status} · 候选区域：{len(pose.regions)} · 搜索耗时：{pose.elapsed_seconds:.3f} 秒')
            if pose.status=='SEARCH_LIMITED':
                st.warning('搜索预算、细化或输出数量受限；尚未细化的粗候选仍被保留，不能将未搜索位置认定为不可行。')
            if pose.status=='INSUFFICIENT_EVIDENCE':
                st.warning('只有单地标或可靠顺序不足，不能确定摄影机位置。地图仅显示地标，不添加虚构机位。')
            if pose.status=='NO_FEASIBLE_POSE':
                st.warning('当前地图覆盖、视场、顺序和站立约束下未找到可行采样；这不表示其他区域或相机假设下没有解。')
            if not any(x.candidates for x in result.matching.matches):
                st.warning('未匹配到可靠地图实体：可能名称不足或照片超出本地三个区域覆盖，不能直接判定照片无地标。')
            focus=st.selectbox('聚焦候选区域',['全部候选区域']+[x.id for x in pose.regions])
            lines=st.checkbox('显示代表点到地标的视线',value=False)
            if result.refinement:
                from geophotoloc.app.refinement_demo import build_refinement_map
                display_map=build_refinement_map(result,offline=mode=='离线案例',focus=None if focus=='全部候选区域' else focus)
            else:
                display_map=build_map(result,offline=mode=='离线案例',focus=None if focus=='全部候选区域' else focus,sightlines=lines)
            st_folium(display_map,
                      height=610,use_container_width=True,returned_objects=[],key=f'map-{mode}-{focus}')
            st.caption('离线几何图不加载网络底图。彩色面为采样候选区域；方向线为朝向假设；代表点不是已确认拍摄点。© OpenStreetMap contributors / ODbL')
        else:
            st.info('选择离线案例，或上传照片并点击开始定位。模型不会因页面重绘而自动调用。')
    if result:
        if result.refinement:
            from geophotoloc.app.refinement_demo import render_refinement
            render_refinement(result,offline=mode=='离线案例',show_map=False)
        st.subheader('几何证据与候选排序')
        rows=[]
        for rank,region in enumerate(result.localization.regions,1):
            rows.append({'排名':rank,'区域':region.id,'地图覆盖':region.region_id,'纬度':region.best_location.latitude,
                         '经度':region.best_location.longitude,'面积 km²':round(region.area_m2/1e6,4),'朝向°':region.heading,
                         '启发式分（非概率）':region.best_score.score,'满足':region.best_score.satisfied,'冲突':region.best_score.conflicts,
                         '不可判定':region.best_score.indeterminate,'已细化':region.refined,'触及搜索边界':region.touches_search_boundary,
                         '身份组合':str(region.assignments)})
        st.dataframe(rows,hide_index=True)
        st.warning('尚无唯一拍摄点的精度证据。只有两个可靠地标且视场角未知时，可能存在连续机位带；网格间距不是定位误差，启发式分不是成功概率。')
        with st.expander('地图匹配详情与身份歧义',expanded=False):
            st.dataframe([{'图像 ID':match.image_landmark_id,'候选':c.entity.name,'OSM ID':c.entity.id,'分数':c.score,
                           '坐标含义':c.entity.coordinate_meaning,'身份确认':c.identity_certain,'依据':'；'.join(c.reasons)}
                          for match in result.matching.matches for c in match.candidates],hide_index=True)
            st.write([{'图像 ID':m.image_landmark_id,'未匹配原因':m.unmatched_reason} for m in result.matching.matches if not m.candidates])
        with st.expander('空间关系、分项评分与限制'):
            st.json([x.model_dump(mode='json') for x in result.vision.relations])
            st.json([{'区域':r.id,'评分':r.best_score.model_dump(),'限制':r.uncertainty} for r in result.localization.regions])
            st.write(result.localization.warnings)
            st.json([{'组合':h.id,'分配':h.assignments,'搜索点':h.searched_points,'可行点':h.feasible_points,
                      '过滤点':h.filtered_points,'受限':h.limited,'原因':h.reasons}
                     for h in result.localization.hypotheses])
        st.caption(result.provenance)
        with st.expander('独立机位评估（历史求解完成后核验）'):
            show_historical=st.checkbox('主动加载历史独立机位评估',value=False,key='show_historical_evaluation')
            evaluations=load_camera_evaluations() if show_historical else []
            st.caption('以下是独立来源自报 Camera location 的小样本核验，不是测量级真值；未输入视觉、地图匹配或求解器。北外滩为新增真实 Pipeline 案例。')
            st.dataframe([{'案例':x['case'],'是否有可评估坐标':x['evaluated'],'状态':x.get('status','仅粗地点描述'),
                           '真值在候选区域内':x.get('truth_inside_any'),
                           '到最近候选区域 m':x.get('nearest_region_distance_m'),
                           '到首个代表点 m':x.get('top1_point_distance_m'),
                           '候选区域数':x.get('candidate_regions'),
                           '来源':x['source']} for x in evaluations],hide_index=True)
            st.info('北京真值位于现有地图覆盖外；东方明珠单地标不计算虚构误差；北外滩本次真值未被最终多边形包含。广州没有精确机位坐标，不计算米制误差。')
        if payloads:
            a,b,c=st.columns(3)
            a.download_button('下载完整 JSON',payloads['json'],'geophotoloc_result.json','application/json')
            b.download_button('下载 GeoJSON',payloads['geojson'],'candidate_regions.geojson','application/geo+json')
            c.download_button('下载标注图片',payloads['annotated_png'],'landmarks.png','image/png')
        st.caption('独立机位核验与失败案例见 docs/STAGE5_FINAL_EVALUATION.md；离线原结果未经修改。')


if __name__=='__main__':
    main()
