"""Actual browser: prepared data -> real retraining/chart -> automatic purchase -> fake payment."""
import os,socket,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright,expect
from check_easy_browser import FAKE_SDK


def run(base,artifacts):
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1080})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('https://www.paypal.com/sdk/js?**',lambda route:route.fulfill(status=200,content_type='application/javascript',body=FAKE_SDK))
        page.goto(base+'/demo/')
        expect(page.locator('#easy-mode')).to_have_text('DEMO · Auto restock ON')
        expect(page.locator('#easy-ml-proof')).to_be_visible()
        expect(page.locator('#easy-ml-days')).to_have_text('90')
        expect(page.locator('#easy-ml-models')).to_have_text('3')
        assert int(page.locator('#easy-ml-selected').inner_text())>=1
        assert page.request.get(base+'/api/products').json()==[]
        old=page.request.get(base+'/demo/api/forecast?product_id=1&source=demo').json()
        assert old['report']['selected_method']=='random_forest'
        page.screenshot(path=str(artifacts/'ml-demo-home.png'),full_page=True)
        page.locator('#easy-ml-open').click()
        expect(page.locator('#forecast-choice')).to_contain_text('ML forecast selected')
        expect(page.locator('#forecast-train')).to_be_enabled()
        assert page.locator('#forecast-chart circle').count()==7
        assert page.locator('#forecast-test-rows tr').count()==21
        with page.expect_response(lambda r:'/api/forecast/train' in r.url and r.request.method=='POST') as response:
            page.locator('#forecast-train').click()
        trained=response.value.json()
        assert trained['run_id']!=old['run_id']
        assert trained['report_current'] and trained['report']['training_days']==90
        expect(page.locator('#forecast-choice')).to_contain_text('ML forecast selected')
        expect(page.locator('#forecast-results')).to_be_visible()
        expect(page.locator('#forecast-train')).to_have_text('Train & forecast')
        page.screenshot(path=str(artifacts/'ml-demo-forecast.png'),full_page=True)
        page.evaluate("window.resupplyNavigate('overview')")
        expect(page.locator('#easy-pay')).to_be_visible(timeout=20000)
        page.locator('#easy-stock-quantity').fill('1');page.locator('#easy-stock-save').click()
        expect(page.locator('#easy-stock-list')).to_contain_text('11 left',timeout=20000)
        expect(page.locator('#easy-pay')).to_be_enabled()
        order=next(o for o in page.request.get(base+'/demo/api/orders').json() if o['status']=='draft')
        details=page.request.get(base+'/demo/api/orders/'+str(order['id'])).json()
        pen=next(item for item in details['items'] if item['product_id']==1)
        assert pen['demand_source']=='reviewed_ml' and pen['forecast_run_id']==trained['run_id']
        assert details['payment'] is None
        page.locator('#easy-pay').click();page.locator('#fake-buyer-approve').click()
        expect(page.locator('#paypal-payment-message')).to_contain_text('captured',timeout=20000)
        assert page.request.get(base+'/api/products').json()==[]
        page.locator('#close-review').click();page.evaluate("window.resupplyNavigate('overview')")
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_function("document.getElementById('app-sidebar').getBoundingClientRect().right<=1")
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(artifacts/'ml-demo-mobile.png'),full_page=True)
        assert not errors,errors
        browser.close()
        print('PASS: visible 90-day/3-model proof, real Train request and changed run ID, ML forecast/chart/21 test rows, automatic ML-based draft after stock update, mocked PayPal capture, blank main shop, mobile layout and zero page errors.')


if __name__=='__main__':
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory(prefix='ml-browser-artifacts-') as folder:
        artifacts=Path(os.environ.get('RESUPPLY_BROWSER_ARTIFACTS',folder));artifacts.mkdir(parents=True,exist_ok=True)
        env={**os.environ,'RESUPPLY_TEST_PORT':str(port),'RESUPPLY_ML_DEMO_TEST':'1'}
        server=subprocess.Popen([sys.executable,str(Path(__file__).with_name('easy_browser_server.py'))],env=env,stdout=subprocess.DEVNULL)
        try:
            for _ in range(300):
                try:urlopen(base+'/health',timeout=1);break
                except Exception:
                    if server.poll() is not None:raise RuntimeError('Test fixture could not start.')
                    time.sleep(.1)
            else:raise RuntimeError('Model preparation timed out.')
            run(base,artifacts)
        finally:server.terminate();server.wait(timeout=5)
