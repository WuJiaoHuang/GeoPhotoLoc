import json
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path.cwd();out=root/'docs/evaluation/stage5_2/demo';out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
 page=browser.new_page(viewport={'width':1440,'height':1600},device_scale_factor=1)
 errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
 page.goto('http://localhost:8510/?demo=refinement&case=photo_02',wait_until='domcontentloaded')
 page.get_by_text('语义检索 → 空间关系 → 完整几何精化',exact=True).wait_for(timeout=90000)
 page.get_by_text('S0',exact=True).first.wait_for(timeout=30000,state='attached')
 page.screenshot(path=str(out/'offline_refinement_overview.png'),full_page=True)
 page.locator('iframe').last.scroll_into_view_if_needed()
 page.wait_for_timeout(10000)
 page.screenshot(path=str(out/'offline_refinement_photo02.png'),full_page=True)
 frames=[f for f in page.frames if f!=page.main_frame]
 frame_text=' '.join(f.locator('body').inner_text() for f in frames)
 (out/'browser_debug.json').write_text(json.dumps(dict(errors=errors,frame_text=frame_text),ensure_ascii=False,indent=2),encoding='utf-8')
 assert all(s in frame_text for s in ['S0','S1','S2']),frame_text[:500]
 assert '独立评估参考机位' not in frame_text
 # Verify real Leaflet interaction and explicit evaluation rerender, not only HTML.
 f=next(f for f in page.frames if f!=page.main_frame and 'S0' in f.locator('body').inner_text())
 layer_count=f.evaluate('Object.keys(window.map._layers).length')
 f.locator('.leaflet-control-layers-overlays label').filter(has_text='S0').locator('input').check()
 page.wait_for_timeout(1000)
 assert f.evaluate('Object.keys(window.map._layers).length')>layer_count
 page.get_by_text('独立评估模式：显示参考机位',exact=True).click()
 assert page.get_by_label('独立评估模式：显示参考机位',exact=True).is_checked()
 page.get_by_text('紫红点为来源自报相机位置，仅在求解后的只读评估显示。',exact=True).wait_for(timeout=30000)
 page.wait_for_timeout(6000)
 frames=[f for f in page.frames if f!=page.main_frame]
 tooltip_js='''() => {let result=[]; function walk(layer){if(layer.getTooltip && layer.getTooltip()){result.push(String(layer.getTooltip().getContent()));} if(layer.eachLayer)layer.eachLayer(walk);} if(window.map)walk(window.map);return result;}'''
 tooltips=[tip for f in frames for tip in f.evaluate(tooltip_js)]
 assert any('独立评估参考机位' in t for t in tooltips),tooltips[:5]
 page.screenshot(path=str(out/'independent_evaluation_photo02.png'),full_page=True)
 (out/'browser_acceptance.json').write_text(json.dumps(dict(url=page.url,offline_layers_visible=True,reference_default_hidden=True,layer_toggle_verified=True,reference_only_after_explicit_evaluation=True,page_errors=errors,screenshot='offline_refinement_photo02.png'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 assert not errors,errors
 browser.close()
