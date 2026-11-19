"""Real browser acceptance. Start current Streamlit on localhost:8512."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

out=Path('docs/evaluation/stage5_4/demo');out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
 page=browser.new_page(viewport={'width':1440,'height':1700});errors=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://localhost:8512/?demo=refinement&case=photo_02',wait_until='domcontentloaded')
 page.get_by_text('空间关系对照版本',exact=True).wait_for(timeout=60000)
 page.get_by_role('combobox').last.click();page.get_by_role('option',name='Stage 5.4 自动关系 F',exact=True).click()
 page.get_by_text('A1 只增加连续关系评分',exact=False).wait_for(timeout=60000)
 page.locator('iframe').last.scroll_into_view_if_needed();page.wait_for_timeout(8000)
 f=next(f for f in page.frames if f!=page.main_frame and 'A2' in f.locator('body').inner_text())
 text=f.locator('body').inner_text();assert all(s in text for s in ('A0','A1','A2','F 排名'))
 js='''() => {let a=[];function walk(l){if(l.getTooltip&&l.getTooltip())a.push(String(l.getTooltip().getContent()));if(l.eachLayer)l.eachLayer(walk);}if(window.map)walk(window.map);return a;}'''
 assert not any('独立评估参考机位' in t for t in f.evaluate(js))
 before=f.evaluate('Object.keys(window.map._layers).length')
 f.locator('.leaflet-control-layers-overlays label').filter(has_text='A1 自动').locator('input').check()
 assert f.evaluate('Object.keys(window.map._layers).length')>before
 page.screenshot(path=str(out/'photo02_automatic.png'),full_page=True)
 page.get_by_text('独立评估模式：显示参考机位',exact=True).click()
 for _ in range(40):
  page.wait_for_timeout(1000)
  tooltips=[t for f in page.frames if f!=page.main_frame for t in f.evaluate(js)]
  if any('独立评估参考机位' in t for t in tooltips):break
 assert any('独立评估参考机位' in t for t in tooltips)
 page.screenshot(path=str(out/'photo02_evaluation.png'),full_page=True)
 assert not errors,errors
 (out/'browser_acceptance.json').write_text(json.dumps(dict(automatic_version_selected=True,A0_A1_A2_layers=True,F_rank_markers=True,layer_toggle_verified=True,reference_default_hidden=True,explicit_reference_verified=True,page_errors=errors),indent=2)+'\n',encoding='utf-8')
 browser.close()
