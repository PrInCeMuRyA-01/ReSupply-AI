"""Browser integration against the isolated fake-PayPal test server, never a live account."""
from pathlib import Path
import os,socket,subprocess,sys,tempfile,time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright,expect

BASE=None
ARTIFACTS=None
FAKE_SDK='''window.paypal={FUNDING:{PAYPAL:'paypal'},Buttons:function(options){return{
isEligible:()=>true,close:()=>Promise.resolve(),render:async function(target){
const b=document.createElement('button');b.id='fake-buyer-approve';b.textContent='Approve Sandbox test payment';
b.onclick=async()=>{try{let allowed=true;await options.onClick({}, {resolve:()=>Promise.resolve(),reject:()=>{allowed=false;return Promise.resolve();}});
if(!allowed)return;const id=await options.createOrder();await options.onApprove({orderID:id});}catch(e){await options.onError(e);}};
document.querySelector(target).replaceChildren(b);}}}};'''


def run():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1366,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.route('https://www.paypal.com/sdk/js?**',lambda route:route.fulfill(status=200,content_type='application/javascript',body=FAKE_SDK))
        page.goto(BASE);expect(page.locator('#easy-mode')).to_have_text('One-time setup')
        assert page.locator('nav details').count()==1 and not page.locator('nav details').evaluate('(e)=>e.open')
        for selector,value in [('#easy-name','Blue Pen'),('#easy-stock','50'),('#easy-cost','0.60'),('#easy-supplier','Metro Wholesale'),('#easy-daily','5'),('#easy-lead','2')]:
            page.locator(selector).fill(value)
        page.locator('#easy-add-product').click()
        expect(page.locator('#easy-product-feedback')).to_contain_text('Blue Pen saved')
        expect(page.locator('#easy-sale-product')).to_contain_text('50 left')
        page.locator('#easy-shipping').fill('2.00');page.locator('#easy-tax').fill('1.00')
        page.locator('#easy-auto-history').check();page.locator('#easy-enabled').check();page.locator('#easy-policy-save').click()
        expect(page.locator('#easy-mode')).to_have_text('Auto restock ON',timeout=20000)
        expect(page.locator('#easy-pay')).to_be_hidden()
        page.locator('#easy-stock-quantity').fill('35');page.locator('#easy-stock-save').click()
        expect(page.locator('#easy-pay')).to_have_text('Pay $27.00 with PayPal',timeout=20000)
        expect(page.locator('#easy-stock-list')).to_contain_text('15 left')
        # The ordinary shopkeeper never clicks Train, Build plan, Select supplier or Approve order.
        page.locator('#easy-pay').click()
        expect(page.locator('#order-dialog')).to_be_visible()
        expect(page.locator('#easy-payment-mode-note')).to_contain_text('complete (capture)')
        page.locator('#fake-buyer-approve').click()
        expect(page.locator('#paypal-payment-message')).to_contain_text('captured',timeout=20000)
        order=page.request.get(BASE+'/api/orders').json()[0]
        assert order['payment']['state']=='captured' and order['grand_total']=='27.00'
        assert page.request.get(BASE+'/api/products').json()[0]['stock']==15
        page.locator('#close-review').click();page.evaluate("window.resupplyNavigate('overview')")
        expect(page.locator('#easy-receive')).to_be_visible(timeout=20000)
        page.locator('#easy-receive').click();expect(page.locator('#order-action-confirm')).to_be_visible()
        page.locator('#confirm-order-action').click()
        expect(page.locator('#paypal-payment-message')).to_contain_text('received',timeout=20000)
        assert page.request.get(BASE+'/api/products').json()[0]['stock']==55
        page.locator('#close-review').click();page.evaluate("window.resupplyNavigate('overview')")
        expect(page.locator('#easy-stock-list')).to_contain_text('55 left',timeout=20000)
        page.screenshot(path=str(ARTIFACTS/'easy-home-desktop.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_function("document.getElementById('app-sidebar').getBoundingClientRect().right<=1")
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(ARTIFACTS/'easy-home-mobile.png'),full_page=True)
        page.reload();expect(page.locator('#easy-stock-list')).to_contain_text('55 left')
        assert page.request.get(BASE+'/demo/api/products').json()==[]
        assert not errors,errors
        print('PASS: actual Chromium form setup, stock-only automatic order, explicit PayPal consent with automatic capture, manual receiving, persisted stock after refresh, separate empty demo, no page errors and no horizontal overflow at 1366px/390px. PayPal is mocked.')
        browser.close()


if __name__=='__main__':
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    BASE=f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory(prefix='easy-browser-artifacts-') as folder:
        ARTIFACTS=Path(os.environ.get('RESUPPLY_BROWSER_ARTIFACTS',folder));ARTIFACTS.mkdir(parents=True,exist_ok=True)
        env={**os.environ,'RESUPPLY_TEST_PORT':str(port)}
        server=subprocess.Popen([sys.executable,str(Path(__file__).with_name('easy_browser_server.py'))],env=env,stdout=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:urlopen(BASE+'/health',timeout=1);break
                except Exception:
                    if server.poll() is not None:raise RuntimeError('Test server failed to start.')
                    time.sleep(.1)
            else:raise RuntimeError('Test server startup timed out.')
            run()
        finally:server.terminate();server.wait(timeout=5)
