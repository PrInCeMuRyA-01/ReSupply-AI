"""Real ML + SQLite integration; payments use offline mocks only."""
import asyncio
from datetime import timedelta
from fractions import Fraction
import json
from uuid import uuid4

import check_forecast as model
import check_settlement as settlement
from forecast_purchasing import supply_projection, planning_context

code,ok,request,TODAY = model.code,model.ok,model.request,model.TODAY


def review_body(run,revision=0,action='use'):
    return {'request_id':str(uuid4()),'product_id':1,'action':action,
            'expected_run_id':run if action=='use' else None,'expected_revision':revision}


def delivery_body(value,revision=0,version=2):
    return {'request_id':str(uuid4()),'expected_order_version':version,'expected_revision':revision,'arrival_date':value}


async def train_actual():
    model.seed_history(source='actual',age=1,values=lambda i,d:10)
    return await ok('/api/forecast/train','POST',model.train_body('actual'))


async def actual_review_budget_and_frozen_order(fake,draft):
    await ok('/api/orders/1/cancel','POST',{'expected_version':1})
    report = await train_actual()
    before = await ok('/api/restock')
    assert before['items'][0]['demand_source'] == 'sales_average' and not report['planning']['active_run_id']
    preview = await ok('/api/forecast-planning/preview?product_id=1&run_id='+str(report['run_id'])+'&budget=10.00')
    assert not preview['demo'] and preview['lead_time_days']==2 and len(preview['daily'])==12
    assert preview['target_stock']==117 and preview['suggested_quantity']==100 and preview['budget_quantity']==10
    assert preview['budget_cost']=='9.5' and (await ok('/api/restock'))==before
    body=review_body(report['run_id'])
    changed=await ok('/api/forecast-planning/review','POST',body)
    assert changed['revision']==1 and (await ok('/api/forecast-planning/review','POST',body))['replayed']
    assert (await ok('/api/forecast-planning/requests/'+body['request_id']))['replayed']
    plan=await ok('/api/restock');item=plan['items'][0]
    assert item['forecast_run_id']==report['run_id'] and item['demand_source']=='reviewed_forecast_average'
    assert item['suggested_quantity']==100 and item['estimated_cost']=='95.00' and plan['method']=='reviewed_forecast_mixed'
    budget=await ok('/api/purchase-plan?budget=10.00')
    assert budget['planned_units']==10 and budget['planned_cost']=='9.50' and budget['remaining_budget']=='0.50'
    saved=(await ok('/api/orders','POST',{'request_id':str(uuid4()),'budget':'10.00'},status=201))['order']
    line=saved['items'][0];assert line['forecast_run_id']==report['run_id'] and line['quantity']==10
    approved=await model.base.approve(saved)
    await ok('/api/forecast-planning/review','POST',review_body(None,revision=1,action='average'))
    assert (await ok('/api/orders/2'))['items']==approved['items'] and (await ok('/api/orders/2'))['grand_total']==approved['grand_total']
    assert (await ok('/api/products'))[0]['stock']==17 and not fake.creates


async def demo_isolated_preview(fake,draft):
    model.seed_history(source='demo')
    report=await ok('/api/forecast/train','POST',model.train_body())
    before=await ok('/api/restock');stock=await ok('/api/products');orders=await ok('/api/orders')
    preview=await ok('/api/forecast-planning/preview?product_id=1&run_id='+str(report['run_id'])+'&example_stock=100&budget=20.00')
    assert preview['demo'] and preview['stock']==100 and preview['unit_cost']=='1' and preview['lead_time_days']==3
    assert preview['incoming_units']==0 and 'cannot create real purchase drafts' in preview['message']
    assert (await request('/api/forecast-planning/review','POST',review_body(report['run_id'])))[0]==409
    assert await ok('/api/restock')==before and await ok('/api/products')==stock and await ok('/api/orders')==orders


async def stale_preference_and_draft_guard(fake,draft):
    report=await train_actual()
    # Existing draft from before the review must be rejected even when sales
    # themselves have not changed since a newly-created average draft.
    await ok('/api/orders/1/cancel','POST',{'expected_version':1})
    saved=(await ok('/api/orders','POST',{'request_id':str(uuid4()),'budget':'10.00'},status=201))['order']
    await ok('/api/forecast-planning/review','POST',review_body(report['run_id']))
    status,data=await request('/api/orders/2/approve','POST',{'request_id':str(uuid4()),'expected_version':1,'shipping_cost':'0.00','tax_cost':'0.00','spending_limit':'10.00'})
    assert status==409 and 'Forecast review' in data['detail']
    with code.database() as db:
        db.execute("UPDATE daily_sales_history SET units_sold=11,revision=revision+1 WHERE sale_date='2026-10-13'")
    state=await ok('/api/forecast?product_id=1&source=actual')
    assert not state['planning']['active_run_id'] and 'outdated' in state['planning']['message']
    assert (await ok('/api/restock'))['items'][0]['demand_source']=='sales_average'
    assert (await request('/api/forecast-planning/review','POST',review_body(report['run_id'],1)))[0]==409


async def incoming_capture_dates_and_receipt(fake,draft):
    fake=settlement.FakeSettlement();code.SandboxPayPal=lambda:fake
    await settlement.held(fake,draft)
    await ok('/api/orders/1/paypal/capture','POST',{'expected_version':2})
    report=await train_actual()
    await ok('/api/forecast-planning/review','POST',review_body(report['run_id']))
    initial=await ok('/api/incoming-stock')
    assert len(initial['items'])==1 and initial['items'][0]['status']=='no_date'
    assert (await ok('/api/restock'))['items'][0]['suggested_quantity']==100
    body=delivery_body('2026-10-15')
    await ok('/api/incoming-stock/1','PUT',body)
    assert (await ok('/api/incoming-stock/1','PUT',body))['replayed']
    current=(await ok('/api/restock'))['items'][0]
    assert current['incoming_units']==10 and current['suggested_quantity']==90
    assert (await ok('/api/products'))[0]['stock']==17
    # The existing open-product guard still prevents a second purchase.
    assert (await request('/api/orders','POST',{'request_id':str(uuid4()),'budget':'10.00'}))[0]==409
    with code.database() as db:before=planning_context(db,1,TODAY)
    # A late delivery at the window end cannot erase an earlier stock deficit.
    await ok('/api/incoming-stock/1','PUT',delivery_body('2026-10-25',revision=1))
    late=(await ok('/api/restock'))['items'][0]
    assert late['incoming_units']==10 and late['suggested_quantity']==100 and late['status']=='delivery_risk'
    with code.database() as db:assert planning_context(db,1,TODAY)!=before
    await ok('/api/incoming-stock/1','PUT',delivery_body(None,revision=2))
    assert (await ok('/api/restock'))['items'][0]['incoming_units']==0
    await ok('/api/orders/1/receive','POST',{'request_id':str(uuid4()),'expected_version':2})
    assert (await ok('/api/incoming-stock'))['items']==[]
    assert (await ok('/api/products'))[0]['stock']==27 and (await ok('/api/restock'))['items'][0]['incoming_units']==0
    assert len(fake.captures)==1


async def invalid_dates_unpaid_and_concurrency(fake,draft):
    for identity in ['0','-1','999999999999999999999999']:
        assert (await request('/api/incoming-stock/'+identity,'PUT',delivery_body('2026-10-15')))[0]==422
    assert (await request('/api/incoming-stock/1','PUT',delivery_body('2026-10-15',version=1)))[0]==409
    fake=settlement.FakeSettlement();code.SandboxPayPal=lambda:fake
    await settlement.held(fake,draft)
    assert (await request('/api/incoming-stock/1','PUT',delivery_body('2026-10-15')))[0]==409
    await ok('/api/orders/1/paypal/capture','POST',{'expected_version':2})
    for day in ['2026-10-13','2026-02-30','2026-1-15','2027-03-01']:
        assert (await request('/api/incoming-stock/1','PUT',delivery_body(day)))[0]==422
    left,right=await asyncio.gather(request('/api/incoming-stock/1','PUT',delivery_body('2026-10-15')),
                                    request('/api/incoming-stock/1','PUT',delivery_body('2026-10-16')))
    assert sorted([left[0],right[0]])==[200,409]
    code.shop_today=lambda:TODAY+timedelta(days=5)
    assert (await ok('/api/incoming-stock'))['items'][0]['status']=='overdue'


async def review_concurrency_and_identity(fake,draft):
    report=await train_actual()
    left,right=await asyncio.gather(request('/api/forecast-planning/review','POST',review_body(report['run_id'])),
                                    request('/api/forecast-planning/review','POST',review_body(None,action='average')))
    assert sorted([left[0],right[0]])==[200,409]
    body=review_body(None,revision=1,action='average')
    await ok('/api/forecast-planning/review','POST',body)
    assert (await request('/api/forecast-planning/review','POST',{**body,'product_id':2}))[0]==409
    for bad in [{**body,'expected_revision':True},{**body,'source':'demo'},{**body,'expected_run_id':True}]:
        assert (await request('/api/forecast-planning/review','POST',bad))[0]==422
    assert (await request('/api/forecast-planning/requests/'+str(uuid4())))[0]==404


async def full_horizon_and_sales_remaining(fake,draft):
    report=await train_actual()
    await ok('/api/products/1/supplier-selection','DELETE')
    data=await ok('/api/forecast-planning/preview?product_id=1&run_id='+str(report['run_id'])+'&lead_time_days=30&coverage_days=30&buffer_days=14')
    assert len(data['daily'])==75 and data['daily'][0]['demand_units']=='7.000000'
    assert data['daily'][-1]['date']==(TODAY+timedelta(days=74)).isoformat()
    assert data['target_stock']==747 and data['suggested_quantity']==730
    # Additional actual sales reduce inventory and remaining-today demand once.
    await ok('/api/sales','POST',{'product_id':1,'quantity':2,'request_id':str(uuid4())},status=201)
    after=await ok('/api/forecast-planning/preview?product_id=1&run_id='+str(report['run_id'])+'&lead_time_days=30&coverage_days=30&buffer_days=14')
    assert after['daily'][0]['demand_units']=='5.000000' and after['stock']==15 and after['suggested_quantity']==730


async def exact_fraction_and_timing(fake,draft):
    demands=[(TODAY+timedelta(days=i),Fraction(4,7)) for i in range(1,8)]
    result=supply_projection(demands,0,[],TODAY,1)
    assert result['target_stock']==4 and result['suggested_quantity']==4
    early=[{'order_id':1,'quantity':10,'arrival_date':TODAY.isoformat()}]
    assert supply_projection(demands,0,early,TODAY,1)['suggested_quantity']==0
    late=[{'order_id':1,'quantity':10,'arrival_date':(TODAY+timedelta(days=7)).isoformat()}]
    assert supply_projection(demands,0,late,TODAY,1)['suggested_quantity']==4
    excluded=[{'order_id':1,'quantity':10,'arrival_date':(TODAY-timedelta(days=1)).isoformat()},
              {'order_id':2,'quantity':10,'arrival_date':None}]
    result=supply_projection(demands,0,excluded,TODAY,1)
    assert result['incoming_units']==0 and result['excluded_incoming_units']==20


async def main():
    for check in [actual_review_budget_and_frozen_order,demo_isolated_preview,stale_preference_and_draft_guard,
                  incoming_capture_dates_and_receipt,invalid_dates_unpaid_and_concurrency,review_concurrency_and_identity,
                  full_horizon_and_sales_remaining,exact_fraction_and_timing]:
        await model.scenario(check);print('PASS:',check.__name__)
    print('8 purchasing integration scenarios passed. Real ML; mocked payments only.')


if __name__=='__main__':asyncio.run(main())
