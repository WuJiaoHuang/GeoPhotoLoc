"""Optional real Chrome acceptance; start Streamlit on port 8511 first."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

out=Path('docs/evaluation/stage5_3/demo');out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
 page=browser.new_page(viewport={'width':1440,'height':1700});errors=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://localhost:8511/?demo=refinement&case=photo_04',wait_until='domcontentloaded')
 page.get_by_text('空间关系对照版本',exact=True).wait_for(timeout=60000)
 page.get_by_role('combobox').last.click()
 page.get_by_role('option',name='Stage 5.3 可靠性分级',exact=True).click()
 page.get_by_text('S1 与 S1-R 是并列实验；',exact=False).wait_for(timeout=60000)
 page.locator('iframe').last.scroll_into_view_if_needed();page.wait_for_timeout(8000)
 f=next(f for f in page.frames if f!=page.main_frame and 'S1-R' in f.locator('body').inner_text())
 text=f.locator('body').inner_text()
 assert all(s in text for s in ['S0','S1-R','S2-R'])
 tooltip_js='''() => {let a=[];function walk(l){if(l.getTooltip&&l.getTooltip())a.push(String(l.getTooltip().getContent()));if(l.eachLayer)l.eachLayer(walk);}if(window.map)walk(window.map);return a;}'''
 assert not any('独立评估参考机位' in t for t in f.evaluate(tooltip_js))
 checkbox=f.locator('.leaflet-control-layers-overlays label').filter(has_text='S1-R 三级').locator('input')
 before=f.evaluate('Object.keys(window.map._layers).length');checkbox.check();page.wait_for_timeout(500)
 assert f.evaluate('Object.keys(window.map._layers).length')>before
 page.screenshot(path=str(out/'photo04_parallel_layers.png'),full_page=True)
 page.get_by_text('独立评估模式：显示参考机位',exact=True).click()
 page.get_by_text('紫红点为来源自报相机位置，仅在求解后的只读评估显示。',exact=True).wait_for(timeout=30000)
 tooltips=[]
 for _ in range(30):
  page.wait_for_timeout(1000)
  tooltips=[t for f in page.frames if f!=page.main_frame for t in f.evaluate(tooltip_js)]
  if any('独立评估参考机位' in t for t in tooltips):break
 assert any('独立评估参考机位' in t for t in tooltips),tooltips[:10]
 page.screenshot(path=str(out/'photo04_independent_evaluation.png'),full_page=True)
 assert not errors,errors
 (out/'browser_acceptance.json').write_text(json.dumps(dict(five_layers_visible=True,parallel_strategy_selected=True,layer_toggle_verified=True,reference_default_hidden=True,explicit_reference_verified=True,page_errors=errors),indent=2)+'\n',encoding='utf-8')
 browser.close()
