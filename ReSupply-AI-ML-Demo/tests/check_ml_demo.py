"""Real training on the prepared dataset; no live PayPal or LLM calls."""
import asyncio
from datetime import date,timedelta
import json
from pathlib import Path
import tempfile
from uuid import uuid4

import check_demo_shop as base
from prepare_ml_demo import prepare_ml_demo
from shop_workspace import demo_scope

code,ok,request=base.code,base.ok,base.request


async def run():
    with tempfile.TemporaryDirectory(prefix='resupply-ml-demo-') as folder:
        code.DB_PATH=Path(folder)/'actual.db';code.DEMO_DB_PATH=Path(folder)/'synthetic.db'
        today=date(2026,10,27);code.shop_today=lambda:today
        code.initialize_database()
        await ok('/api/products','POST',{'sku':'KEEP','name':'Existing real shop sentinel','stock':17,'unit_cost':'1.00'},201)
        original=base.snapshot(code.DB_PATH)
        result=prepare_ml_demo(code)
        assert result['daily_history_rows']==270 and result['added_history_rows']==270
        assert len(result['products'])==3 and result['auto_enabled']
        assert base.snapshot(code.DB_PATH)==original
        for product in result['products']:
            assert product['training_days']==90
            response=await ok('/demo/api/forecast?product_id='+str(product['id'])+'&source=demo')
            report=response['report'];evaluation=report['evaluation']
            assert response['report_current'] and response['planning']['active_run_id']==response['run_id']
            assert len(report['items'])==7 and evaluation['test_days']==21
            assert report['data_start']==(today-timedelta(days=90)).isoformat()
            assert report['data_end']==(today-timedelta(days=1)).isoformat()
            for fold in evaluation['folds']:assert fold['training_end']<fold['test_start']<=fold['test_end']
            measured=sum(abs(row['observed_units']-row['model_units']) for row in evaluation['items'])/len(evaluation['items'])
            assert abs(measured-evaluation['model_mae'])<.00011
        assert result['products'][0]['selected_method']=='random_forest'
        assert result['products'][2]['selected_method']=='seven_day_mean'
        # Reopening does not duplicate history or train a second identical report.
        repeat=prepare_ml_demo(code)
        assert repeat['added_history_rows']==0 and repeat['daily_history_rows']==270
        with demo_scope():
            with code.database() as db:
                assert db.execute('SELECT COUNT(*) FROM demand_forecast_runs').fetchone()[0]==3
                assert db.execute("SELECT COUNT(*) FROM daily_sales_history WHERE source!='demo'").fetchone()[0]==0
        # The ordinary stock-only flow uses the reviewed real model automatically.
        stock=await ok('/demo/api/easy/stock-update','POST',{'request_id':str(uuid4()),'product_id':1,'mode':'sold','quantity':1,'expected_stock':12})
        order=stock['autopilot']['order'];assert order and order['status']=='draft'
        pen=next(line for line in order['items'] if line['product_id']==1)
        assert pen['demand_source']=='reviewed_ml' and pen['forecast_run_id']
        assert order['payment'] is None
        fake=base.UniqueSettlement();code.SandboxPayPal=lambda:fake
        approved=(await ok('/demo/api/easy/autopilot/pay-ready','POST',{'request_id':str(uuid4()),'order_id':order['id'],'expected_version':order['version'],'expected_policy_revision':1}))['order']
        checkout=await ok('/demo/api/orders/'+str(order['id'])+'/paypal/create','POST',{'expected_version':approved['version']})
        fake.remotes[checkout['paypal_order_id']]['status']='APPROVED'
        held=await ok('/demo/api/orders/'+str(order['id'])+'/paypal/authorize','POST',{'paypal_order_id':checkout['paypal_order_id']})
        assert held['payment']['state']=='authorized'
        payment_calls=(len(fake.creates),len(fake.authorizations),len(fake.captures))
        before_stock=await ok('/demo/api/products')
        prepare_ml_demo(code)
        assert await ok('/demo/api/products')==before_stock
        assert (await ok('/demo/api/orders/'+str(order['id'])))['payment']['state']=='authorized'
        assert payment_calls==(len(fake.creates),len(fake.authorizations),len(fake.captures))
        # Future launches extend to the latest completed day without resetting progress.
        today+=timedelta(days=1)
        refreshed=prepare_ml_demo(code)
        assert refreshed['added_history_rows']==3 and refreshed['daily_history_rows']==273
        assert all(p['training_days']==91 for p in refreshed['products'])
        assert await ok('/demo/api/products')==before_stock
        assert base.snapshot(code.DB_PATH)==original
        print(json.dumps({'products':result['products'],'rows':result['daily_history_rows'],'tested_days_per_product':21},indent=2))
        print('PASS: 270 labelled synthetic rows, real 90-day training, measured backtests, ML selection and baseline fallback, automatic use in purchasing, idempotent restarts, current-date extension, preserved stock/holds and unchanged real shop.')


if __name__=='__main__':asyncio.run(run())
