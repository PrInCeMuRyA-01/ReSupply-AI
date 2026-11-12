"""Fresh shop -> stock-only use -> automatic draft -> mocked payment -> receipt."""
import asyncio
from datetime import date,timedelta
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from uuid import uuid4

import check_settlement as settlement
from shop_workspace import demo_scope
from easy_llm import EntrySuggestion

base=settlement.base
code,ok,request=base.code,base.ok,base.request


async def run():
    with tempfile.TemporaryDirectory(prefix='resupply-easy-tests-') as folder:
        code.DB_PATH=Path(folder)/'new-shop.db';code.DEMO_DB_PATH=Path(folder)/'new-demo.db'
        today=date(2026,10,27);code.shop_today=lambda:today
        code.initialize_database()
        with demo_scope():code.initialize_database()
        fake=settlement.FakeSettlement();code.SandboxPayPal=lambda:fake
        assert await ok('/api/products')==[] and await ok('/demo/api/products')==[]
        assert not (await ok('/api/easy/autopilot/run','POST'))['settings']['enabled']
        body={'request_id':str(uuid4()),'name':'Blue Pen','stock':50,'unit_cost':'0.60','supplier_name':'Metro Wholesale','lead_time_days':2,'daily_units':5}
        first=await ok('/api/easy/products','POST',body,201)
        assert (await ok('/api/easy/products','POST',body,201))['replayed']
        assert len(await ok('/api/products'))==1 and len(await ok('/api/suppliers'))==1
        assert (await request('/api/easy/products','POST',{**body,'stock':40}))[0]==409
        second=await ok('/api/easy/products','POST',{**body,'request_id':str(uuid4()),'name':'Notebook','stock':1000},201)
        assert len(await ok('/api/suppliers'))==1
        status=await ok('/api/easy/status');assert not status['products'][0]['ready']
        restock=await ok('/api/restock');assert restock['items'][0]['demand_source']=='owner_estimate'
        settings={'expected_revision':0,'enabled':True,'spending_limit':'100.00','shipping':'2.00','tax':'1.00',
            'coverage_days':7,'buffer_days':2,'auto_history':True,'zero_days_confirmed':False}
        state=await ok('/api/easy/autopilot','PUT',settings);assert state['order'] is None
        update={'request_id':str(uuid4()),'product_id':1,'mode':'sold','quantity':35,'expected_stock':50}
        result=await ok('/api/easy/stock-update','POST',update)
        assert result['stock_after']==15 and result['autopilot']['order']['status']=='draft'
        order=result['autopilot']['order'];assert order['items'][0]['quantity']==40 and order['products_total']=='24.00'
        again=await ok('/api/easy/stock-update','POST',update);assert again['replayed'] and again['autopilot']['order']['id']==order['id']
        assert len(await ok('/api/sales'))==1
        assert (await ok('/api/easy/autopilot/run','POST'))['order']['id']==order['id']
        assert (await request('/api/easy/stock-update','POST',{**update,'request_id':str(uuid4())}))[0]==409
        remaining=await ok('/api/easy/stock-update','POST',{'request_id':str(uuid4()),'product_id':1,'mode':'remaining','quantity':10,'expected_stock':15})
        order2=remaining['autopilot']['order'];assert order2['id']!=order['id'] and order2['items'][0]['quantity']==45
        orders=await ok('/api/orders');assert len([o for o in orders if o['status'] in ['draft','approved']])==1
        assert (await ok('/api/orders/'+str(order['id'])))['status']=='cancelled'
        approval={'request_id':str(uuid4()),'order_id':order2['id'],'expected_version':order2['version'],'expected_policy_revision':1}
        approved=(await ok('/api/easy/autopilot/pay-ready','POST',approval))['order']
        assert approved['grand_total']=='30.00' and approved['status']=='approved'
        assert (await ok('/api/easy/autopilot/pay-ready','POST',approval))['replayed']
        assert (await request('/api/orders/'+str(order['id'])+'/paypal/create','POST',{'expected_version':1}))[0]==409
        checkout=await ok(f"/api/orders/{approved['id']}/paypal/create",'POST',{'expected_version':approved['version']})
        fake.remotes[checkout['paypal_order_id']]['status']='APPROVED'
        held=await ok(f"/api/orders/{approved['id']}/paypal/authorize",'POST',{'paypal_order_id':checkout['paypal_order_id']})
        assert held['payment']['state']=='authorized'
        paid=await ok(f"/api/orders/{approved['id']}/paypal/capture",'POST',{'expected_version':approved['version']})
        assert paid['payment']['state']=='captured' and (await ok('/api/products'))[0]['stock']==10
        assert (await ok('/api/easy/autopilot/run','POST'))['order']['id']==paid['id']
        await ok('/api/easy/stock-update','POST',{'request_id':str(uuid4()),'product_id':1,'mode':'sold','quantity':1,'expected_stock':10})
        assert (await ok('/api/easy/autopilot/run','POST'))['order']['id']==paid['id']
        receive={'request_id':str(uuid4()),'expected_version':paid['version']}
        await ok(f"/api/orders/{paid['id']}/receive",'POST',receive)
        await ok(f"/api/orders/{paid['id']}/receive",'POST',receive)
        assert (await ok('/api/products'))[0]['stock']==54 and len(fake.captures)==1
        assert not (await ok('/api/easy/autopilot/run','POST'))['order']
        assert await ok('/demo/api/products')==[]
        # Date rollover creates only real logged totals unless zero-days were explicitly enabled.
        today+=timedelta(days=1)
        await ok('/api/easy/autopilot/run','POST')
        with code.database() as db:
            rows=db.execute('SELECT * FROM daily_sales_history').fetchall()
            assert len(rows)==1 and rows[0]['units_sold']==41 and rows[0]['source']=='actual'
        # Auto training and use need no manual Train / Preview / Use clicks once opted in.
        csv=['date,sku,units_sold,source,stockout']
        for offset in range(56):
            day=today-timedelta(days=56-offset)
            units=41 if day==today-timedelta(days=1) else [4,5,5,5,6,18,20][day.weekday()]
            csv.append(f"{day},{first['sku']},{units},actual,0")
        preview=await ok('/api/sales-history/import/preview','POST',{'csv_text':'\n'.join(csv)})
        await ok('/api/sales-history/import/commit','POST',{'preview_id':preview['preview_id'],'request_id':str(uuid4())})
        # Existing draft is replaced; the automatic model review is recorded.
        await ok('/api/easy/autopilot/run','POST')
        forecast=await ok('/api/forecast?product_id=1&source=actual')
        assert forecast['report_current'] and forecast['planning']['active_run_id']==forecast['run_id']
        count=len(await ok('/api/orders'))
        await ok('/api/easy/autopilot/run','POST')
        assert len(await ok('/api/orders'))==count
        # Pausing and re-enabling never fills untracked gaps as zero days.
        paused=await ok('/api/easy/autopilot','PUT',{**settings,'expected_revision':1,'enabled':False})
        gap_start=today.isoformat();today+=timedelta(days=3)
        resumed=await ok('/api/easy/autopilot','PUT',{**settings,'expected_revision':2,'zero_days_confirmed':True})
        with code.database() as db:
            assert db.execute('SELECT COUNT(*) FROM daily_sales_history WHERE sale_date>=? AND sale_date<?',(gap_start,today.isoformat())).fetchone()[0]==0
        assert (await request('/api/easy/autopilot','PUT',{**settings,'expected_revision':1}))[0]==409
        # The optional LLM only returns validated draft fields and sends no inventory or keys in its payload.
        sample={'intent':'record_sale','name':'Blue Pen','stock':None,'unit_cost':None,'supplier_name':None,
            'lead_time_days':None,'daily_units':None,'quantity':2,'explanation':'Review the sale.'}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(sample)}]}]}).encode()
        def fake_open(req,timeout):
            payload=json.loads(req.data)
            assert payload['input']=='2 Blue Pen sold' and payload['store'] is False
            assert 'Metro' not in req.data.decode() and 'test-private-key' not in req.data.decode()
            return Response()
        sales_before=await ok('/api/sales')
        with patch.dict(os.environ,{'OPENAI_ENABLED':'true','OPENAI_API_KEY':'test-private-key'}),patch('easy_llm.urlopen',fake_open):
            suggestion=await ok('/api/easy/llm/suggest','POST',{'text':'2 Blue Pen sold','consent_to_send':True})
            assert suggestion['saved'] is False and suggestion['suggestion']['quantity']==2
            assert (await request('/api/easy/llm/suggest','POST',{'text':'2 Blue Pen sold','consent_to_send':False}))[0]==422
            sample['quantity']=-2
            assert (await request('/api/easy/llm/suggest','POST',{'text':'2 Blue Pen sold','consent_to_send':True}))[0]==502
        assert await ok('/api/sales')==sales_before
        print('PASS: fresh isolated shops, atomic setup, shared supplier, owner-estimate planning, stock-only automatic orders, stale-tab and duplicate-save protection, one active draft, explicit payment, single receipt, daily aggregation, auto ML training/use, and read-only mocked LLM drafts.')


if __name__=='__main__':asyncio.run(run())
