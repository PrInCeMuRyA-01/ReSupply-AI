"""Real ML + two SQLite shops + mocked Sandbox lifecycle. No external payments."""
import asyncio
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4
from urllib.parse import urlsplit

import check_settlement as settlement
from sales_history import save_total
from shop_workspace import demo_scope

base=settlement.base
code,ok,request=base.code,base.ok,base.request
TODAY=date(2026,10,14)


def snapshot(path):
    with sqlite3.connect(path) as db:
        tables=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name:db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall() for name in tables}


async def raw_request(url):
    messages=[]
    async def receive():return {'type':'http.request','body':b'','more_body':False}
    async def send(message):messages.append(message)
    path=urlsplit(url)
    await code.app({'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1',
        'method':'GET','scheme':'http','path':path.path,'raw_path':path.path.encode(),
        'query_string':path.query.encode(),'headers':[],'client':('127.0.0.1',123),'server':('test',80)},receive,send)
    start=next(m for m in messages if m['type']=='http.response.start')
    return start['status'],dict(start['headers']),b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body')


class UniqueSettlement(settlement.FakeSettlement):
    def authorize(self,remote_id,request_id):
        try:return super().authorize(remote_id,request_id)
        finally:
            for hold in self.remotes[remote_id]['purchase_units'][0].get('payments',{}).get('authorizations',[]):
                hold['id']='A'+remote_id[1:]


async def demo_ok(path,method='GET',body=None,status=200):
    return await ok('/demo'+path,method,body,status)


async def run():
    with tempfile.TemporaryDirectory(prefix='resupply-demo-shop-') as folder:
        code.DB_PATH=Path(folder)/'real.db'
        code.DEMO_DB_PATH=Path(folder)/'demo.db'
        code.shop_today=lambda:TODAY
        fake=UniqueSettlement()
        draft=await base.seed(fake)
        real=await base.approve(draft)
        created=await ok('/api/orders/1/paypal/create','POST',{'expected_version':2})
        fake.remotes[created['paypal_order_id']]['status']='APPROVED'
        real=await ok('/api/orders/1/paypal/authorize','POST',{'paypal_order_id':created['paypal_order_id']})
        assert real['number'].startswith('EASY-') and real['payment']['state']=='authorized'
        # A current real-shop reviewed forecast must survive the entire demo.
        with code.database() as db:
            for i in range(60):
                day=TODAY-timedelta(days=60-i)
                save_total(db,{'product_id':1,'sale_date':day.isoformat(),'units_sold':5,
                    'source':'actual','stockout':False})
        run_real=await ok('/api/forecast/train','POST',{'request_id':str(uuid4()),'product_id':1,'source':'actual'})
        await ok('/api/forecast-planning/review','POST',{'request_id':str(uuid4()),'product_id':1,
            'action':'use','expected_run_id':run_real['run_id'],'expected_revision':0})
        real_before=snapshot(code.DB_PATH)
        real_plan=await ok('/api/purchase-plan?budget=100.00')
        with demo_scope():code.initialize_database()

        assert (await ok('/api/demo-shop'))['workspace']=='real'
        assert (await request('/api/demo-shop/setup','POST'))[0]==409
        assert not (await demo_ok('/api/demo-shop'))['prepared']
        status,headers,_=await raw_request('/demo')
        assert status==307 and headers[b'location']==b'/demo/'
        status,headers,_=await raw_request('/demo/api/products/')
        assert status==307 and '/demo/api/products' in headers[b'location'].decode()
        for url,mode,prefix in [('/','real',''),('/demo/','demo','/demo')]:
            status,headers,body=await raw_request(url)
            text=body.decode()
            assert status==200 and headers[b'x-resupply-workspace']==mode.encode()
            assert f'data-workspace="{mode}" data-api-prefix="{prefix}"' in text
            assert f'src="{prefix}/assets/shop-workspace.js"' in text
            assert f'src="{prefix}/assets/demo-shop.js"' in text
        for asset in ('shop-workspace','demo-shop','sales-history','demand-forecast','forecast-purchasing','voice-assistant'):
            status,headers,body=await raw_request('/demo/assets/'+asset+'.js')
            assert status==200 and body and headers[b'x-resupply-workspace']==b'demo'
        assert (await ok('/openapi.json'))['servers']==[{'url':'/'}]
        assert (await demo_ok('/openapi.json'))['servers']==[{'url':'/demo'}]
        assert (await ok('/openapi.json'))['servers']==[{'url':'/'}]
        assert '/demo/openapi.json' in (await raw_request('/demo/docs'))[2].decode()
        print('PASS: separate HTML/assets/download/API docs and real setup refusal.')

        prepared=await demo_ok('/api/demo-shop/setup','POST')
        assert prepared['added_history_rows']==180
        initial=await demo_ok('/api/demo-shop')
        assert initial['prepared'] and initial['synthetic'] and len(initial['products'])==3
        assert initial['counts']['suppliers']==2 and initial['counts']['supplier_quotes']==6
        with demo_scope(),code.database() as db:
            namespace=db.execute("SELECT value FROM demo_shop_settings WHERE key='namespace'").fetchone()[0]
            assert db.execute("SELECT COUNT(*) FROM daily_sales_history WHERE source!='demo'").fetchone()[0]==0
            assert db.execute('SELECT MAX(sale_date) FROM daily_sales_history').fetchone()[0]=='2026-10-13'
        saved_seed=snapshot(code.DEMO_DB_PATH)
        await asyncio.gather(*(demo_ok('/api/demo-shop/setup','POST') for _ in range(4)))
        assert snapshot(code.DEMO_DB_PATH)==saved_seed and snapshot(code.DB_PATH)==real_before
        mean=await demo_ok('/api/restock')
        assert all(i['history_status']=='completed_days' and i['average_daily_sales'] is not None for i in mean['items'])
        assert (await request('/demo/api/forecast/train','POST',{'request_id':str(uuid4()),'product_id':1,'source':'actual'}))[0]==422
        bad_day={'request_id':str(uuid4()),'product_id':1,'sale_date':'2026-10-13','units_sold':5,'source':'actual','stockout':False,'expected_revision':1}
        assert (await request('/demo/api/sales-history/day','PUT',bad_day))[0]==409
        csv='date,sku,units_sold,source,stockout\n2026-10-13,PEN-BLUE,5,actual,0\n'
        invalid=await demo_ok('/api/sales-history/import/preview','POST',{'csv_text':csv})
        assert not invalid['valid']
        assert ',demo,0' in (await raw_request('/demo/api/sales-history/template?product_id=1'))[2].decode()
        print('PASS: atomic/retry-safe 3-product seed, synthetic labels, source gates and mean fallback.')

        reports=[]
        for p in initial['products']:
            body={'request_id':str(uuid4()),'product_id':p['id'],'source':'demo'}
            report=await demo_ok('/api/forecast/train','POST',body)
            assert report['report_current'] and report['planning']['can_use'] and report['report']['training_days']==60
            assert (await demo_ok('/api/forecast/train','POST',body))['run_id']==report['run_id']
            reports.append(report)
            preview=await demo_ok(f"/api/forecast-planning/preview?product_id={p['id']}&run_id={report['run_id']}&budget=100.00")
            assert preview['demo'] and preview['isolated_demo_shop'] and preview['stock']==p['stock']
            assert preview['unit_cost']!='1' and 'demo shop' in preview['message'].lower()
            review={'request_id':str(uuid4()),'product_id':p['id'],'action':'use',
                'expected_run_id':report['run_id'],'expected_revision':0}
            await demo_ok('/api/forecast-planning/review','POST',review)
            assert (await demo_ok('/api/forecast-planning/review','POST',review))['replayed']
        methods={r['report']['selected_method'] for r in reports}
        assert methods=={'random_forest','seven_day_mean'}
        plan=await demo_ok('/api/purchase-plan?budget=100.00')
        assert Decimal(plan['planned_cost'])+Decimal(plan['remaining_budget'])==Decimal('100.00')
        assert Decimal(plan['planned_cost'])<=100 and plan['planned_without_supplier']==0
        assert all(i['forecast_run_id'] for i in plan['items'])
        readonly=snapshot(code.DEMO_DB_PATH)
        voice=await demo_ok('/api/assistant/preview','POST',{'text':'50 dollar budget ka plan banao','forecast_source':'demo'})
        assert voice['status']=='ready' and all(i['forecast_run_id'] for i in voice['plan']['items'])
        voice=await demo_ok('/api/assistant/preview','POST',{'text':'PEN-BLUE ka forecast dikhao','forecast_source':'demo'})
        assert voice['status']=='ready' and voice['source']=='demo'
        assert snapshot(code.DEMO_DB_PATH)==readonly and snapshot(code.DB_PATH)==real_before
        assert len(fake.creates)==1 and not fake.captures and not fake.voids
        print('PASS: actual ML, honest mean selection, explicit synthetic review, cents budget and read-only voice.')

        draft_body={'request_id':str(uuid4()),'budget':'100.00'}
        demo=(await demo_ok('/api/orders','POST',draft_body,201))['order']
        assert demo['id']==1 and demo['number']==f'DEMO-{namespace}-000001'
        assert (await demo_ok('/api/orders','POST',draft_body))['replayed']
        assert all(i['forecast_run_id'] for i in demo['items'])
        # Overlapping numeric IDs do not attach a real payment to demo orders.
        assert demo['payment'] is None and (await ok('/api/orders/1'))['payment']['state']=='authorized'
        duplicate=await request('/demo/api/orders','POST',{'request_id':str(uuid4()),'budget':'100.00'})
        assert duplicate[0]==409 and demo['number'] in duplicate[1]['detail']
        approval={'request_id':str(uuid4()),'expected_version':1,'shipping_cost':'0.30','tax_cost':'0.20','spending_limit':'101.00'}
        demo=(await demo_ok('/api/orders/1/approve','POST',approval))['order']
        frozen_items=demo['items']
        created=await demo_ok('/api/orders/1/paypal/create','POST',{'expected_version':2})
        fake.remotes[created['paypal_order_id']]['status']='APPROVED'
        purchase_unit=fake.creates[-1][0]['purchase_units'][0]
        assert purchase_unit['reference_id']==demo['number'] and purchase_unit['custom_id']==demo['number']+'-v2'
        assert purchase_unit['reference_id']!=fake.creates[0][0]['purchase_units'][0]['reference_id']
        assert fake.creates[0][1]!=fake.creates[-1][1]
        demo=await demo_ok('/api/orders/1/paypal/authorize','POST',{'paypal_order_id':created['paypal_order_id']})
        assert demo['payment']['state']=='authorized' and demo['payment']['authorization_id']!=real['payment']['authorization_id']
        held=snapshot(code.DEMO_DB_PATH)
        await demo_ok('/api/demo-shop/setup','POST')
        assert snapshot(code.DEMO_DB_PATH)==held
        assert not (await demo_ok('/api/incoming-stock'))['items']
        fake.lose_capture=True
        assert (await request('/demo/api/orders/1/paypal/capture','POST',{'expected_version':2}))[0]==502
        demo=await demo_ok('/api/orders/1/paypal/sync','POST')
        assert demo['payment']['state']=='captured' and demo['can_receive']
        assert fake.captures[-1][1]['invoice_id']==demo['number']+'-v2' and len(fake.captures[-1][1]['invoice_id'])<=127
        await demo_ok('/api/orders/1/paypal/capture','POST',{'expected_version':2})
        assert len(fake.capture_keys)==1 and len(fake.captures)==1
        incoming=await demo_ok('/api/incoming-stock')
        assert incoming['items'][0]['number']==demo['number']
        eta={'request_id':str(uuid4()),'expected_order_version':2,'expected_revision':0,'arrival_date':'2026-10-16'}
        await demo_ok('/api/incoming-stock/1','PUT',eta)
        before=await demo_ok('/api/products')
        receive={'request_id':str(uuid4()),'expected_version':2}
        received=(await demo_ok('/api/orders/1/receive','POST',receive))['order']
        assert received['status']=='received' and received['items']==frozen_items
        assert (await demo_ok('/api/orders/1/receive','POST',receive))['replayed']
        after=await demo_ok('/api/products')
        quantities={i['product_id']:i['quantity'] for i in frozen_items}
        assert all(p['stock']==before[i]['stock']+quantities.get(p['id'],0) for i,p in enumerate(after))
        assert not (await demo_ok('/api/incoming-stock'))['items']
        assert snapshot(code.DB_PATH)==real_before and await ok('/api/purchase-plan?budget=100.00')==real_plan
        print('PASS: distinct payment references, explicit authorize/capture, lost-response recovery and exactly-once stock receipt.')

        # A separate hold can be voided; progress reflects the latest cancellation.
        cancelled=(await demo_ok('/api/orders','POST',{'request_id':str(uuid4()),'budget':'10.00'},201))['order']
        assert cancelled['id']==2
        cancelled=(await demo_ok('/api/orders/2/approve','POST',{'request_id':str(uuid4()),'expected_version':1,
            'shipping_cost':'0.00','tax_cost':'0.00','spending_limit':'10.00'}))['order']
        created=await demo_ok('/api/orders/2/paypal/create','POST',{'expected_version':2})
        fake.remotes[created['paypal_order_id']]['status']='APPROVED'
        await demo_ok('/api/orders/2/paypal/authorize','POST',{'paypal_order_id':created['paypal_order_id']})
        stock=await demo_ok('/api/products')
        fake.lose_void=True
        assert (await request('/demo/api/orders/2/paypal/void','POST',{'expected_version':2}))[0]==502
        cancelled=await demo_ok('/api/orders/2/paypal/sync','POST')
        assert cancelled['status']=='cancelled' and cancelled['payment']['state']=='voided'
        assert await demo_ok('/api/products')==stock and len(fake.voids)==1
        assert (await demo_ok('/api/demo-shop'))['focus_order']['id']==2
        print('PASS: separate demo Void, interrupted-response sync, cancelled progress and unchanged stock.')

        # Concurrent sync workers get their own ContextVar; no global DB switch.
        paths=['/api/products','/demo/api/products']*30
        results=await asyncio.gather(*(ok(path) for path in paths))
        for path,result in zip(paths,results):
            assert result[0]['sku']==('PEN-BLUE' if path.startswith('/demo') else 'PEN')
        demo_before=snapshot(code.DEMO_DB_PATH)
        code.initialize_database()
        with demo_scope():code.initialize_database()
        await demo_ok('/api/demo-shop/setup','POST')
        assert snapshot(code.DB_PATH)==real_before and snapshot(code.DEMO_DB_PATH)==demo_before
        assert (await demo_ok('/api/orders/1'))['receipt']['units']==received['receipt']['units']
        assert (await demo_ok('/api/demo-shop'))['focus_order']['status']=='cancelled'
        # New day extends only demo history; old approvals/payments stay frozen.
        code.shop_today=lambda:TODAY+timedelta(days=1)
        extended=await demo_ok('/api/demo-shop/setup','POST')
        assert extended['added_history_rows']==3
        stale=await demo_ok('/api/demo-shop')
        assert all(not p['current'] and not p['active_run_id'] for p in stale['products'])
        same=await demo_ok('/api/orders/1')
        assert same['items']==frozen_items and same['payment']==received['payment']
        assert snapshot(code.DB_PATH)==real_before
        assert (await demo_ok('/api/demo-shop/setup','POST'))['added_history_rows']==0
        original_path=code.DEMO_DB_PATH
        code.DEMO_DB_PATH=Path(folder)/'new-demo.db'
        with demo_scope():code.initialize_database()
        await demo_ok('/api/demo-shop/setup','POST')
        with demo_scope(),code.database() as db:
            assert db.execute("SELECT value FROM demo_shop_settings WHERE key='namespace'").fetchone()[0]!=namespace
        code.DEMO_DB_PATH=original_path
        assert (await demo_ok('/api/orders/1'))['number']==received['number']
        assert not code.is_demo_shop()
        print('PASS: 60 concurrent scoped reads, durable restart, idempotent prepare, date refresh and fresh namespace per new demo DB.')


if __name__=='__main__':asyncio.run(run())
