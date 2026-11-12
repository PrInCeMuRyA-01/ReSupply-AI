"""Real SQLite/FastAPI checks for daily totals and imports. No real payments."""
import asyncio
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

import check_paypal as base
from sales_history import planning_revision

code, request, ok = base.code, base.request, base.ok
TODAY = date(2026, 10, 14)


async def raw_request(url):
    messages = []
    async def receive(): return {'type':'http.request','body':b'','more_body':False}
    async def send(message): messages.append(message)
    parts = urlsplit(url)
    await code.app({'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1',
        'method':'GET','scheme':'http','path':parts.path,'raw_path':parts.path.encode(),
        'query_string':parts.query.encode(),'headers':[],'client':('test',1),'server':('test',80)},receive,send)
    status=next(m['status'] for m in messages if m['type']=='http.response.start')
    content=b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body')
    return status,content.decode()


def daily(value='2026-10-12',units=0,source='actual',revision=0,product=1,stockout=False):
    return {'request_id':str(uuid4()),'product_id':product,'sale_date':value,'units_sold':units,
            'source':source,'stockout':stockout,'expected_revision':revision}


async def save_day(**kwargs): return await ok('/api/sales-history/day','PUT',daily(**kwargs))
async def preview(text): return await ok('/api/sales-history/import/preview','POST',{'csv_text':text})
async def commit(result,request_id=None):
    return await ok('/api/sales-history/import/commit','POST',{'request_id':request_id or str(uuid4()),'preview_id':result['preview_id']})


async def scenario(check):
    with tempfile.TemporaryDirectory(prefix='resupply-history-') as folder:
        code.DB_PATH=Path(folder)/'resupply.db'
        code.shop_today=lambda:TODAY
        fake=base.FakePayPal()
        draft=await base.seed(fake)
        await check(fake,draft)


async def zero_missing_live(fake,draft):
    before=await ok('/api/products');sales=await ok('/api/sales')
    empty=await ok('/api/sales-history?product_id=1&days=7')
    assert empty['missing_days']==6 and empty['unconfirmed_days']==0
    today=empty['items'][-1]
    assert today['status']=='today_partial' and today['units_sold']==3
    assert all(item['units_sold'] is None for item in empty['items'][:-1])
    saved=await save_day()
    assert saved['changed'] and saved['revision']==1
    history=await ok('/api/sales-history?product_id=1&days=7')
    assert history['actual_days']==1 and history['zero_sales_days']==1 and history['missing_days']==5
    known=next(item for item in history['items'] if item['sale_date']=='2026-10-12')
    assert known['status']=='complete' and known['units_sold']==0
    baseline=(await ok('/api/restock'))['items'][0]
    assert baseline['history_status']=='completed_days' and baseline['average_daily_sales']==0
    assert await ok('/api/products')==before and await ok('/api/sales')==sales
    assert not fake.creates and not fake.authorizations


async def daily_retries_edits(fake,draft):
    body=daily(units=4)
    first=await ok('/api/sales-history/day','PUT',body)
    assert not first['replayed']
    assert (await ok('/api/sales-history/day','PUT',body))['replayed']
    assert (await ok('/api/sales-history/requests/'+body['request_id']))['replayed']
    changed={**body,'units_sold':5}
    assert (await request('/api/sales-history/day','PUT',changed))[0]==409
    assert (await request('/api/sales-history/day','PUT',daily(units=8)))[0]==409
    edited=await save_day(units=8,revision=1)
    assert edited['revision']==2
    # Same-value save does not increment data revisions or invalidate drafts again.
    identical=await save_day(units=8,revision=2)
    assert not identical['changed'] and identical['revision']==2
    with code.database() as connection:
        assert planning_revision(connection,1)==3  # one live event + two actual changes


async def conflicting_logged_total(fake,draft):
    with code.database() as connection:
        connection.execute("UPDATE sales SET sale_date='2026-10-13'")
    assert (await request('/api/sales-history/day','PUT',daily(value='2026-10-13',units=2)))[0]==409
    await save_day(value='2026-10-13',units=3)
    await save_day(value='2026-10-12',units=0)
    history=await ok('/api/sales-history?product_id=1&days=7')
    recorded=next(item for item in history['items'] if item['sale_date']=='2026-10-13')
    assert recorded['units_sold']==3 and recorded['logged_units']==3
    baseline=(await ok('/api/restock'))['items'][0]
    assert baseline['units_sold']==3 and baseline['days_used']==2 and baseline['average_daily_sales']==1.5
    assert (await ok('/api/products'))[0]['stock']==17


async def csv_commit_retries(fake,draft):
    text='\ufeffdate,sku,units_sold,source,stockout\r\n2026-10-12,pen,0,actual,0\r\n2026-10-11,PEN,8,demo,0\r\n'
    before=await ok('/api/products');sales=await ok('/api/sales')
    view=await preview(text)
    assert view['valid'] and view['new_rows']==2 and view['actual_rows']==view['demo_rows']==1
    assert (await ok('/api/sales-history?product_id=1&days=7'))['actual_days']==0
    key=str(uuid4())
    done=await commit(view,key)
    assert done['inserted']==2 and not done['replayed']
    assert (await commit(view,key))['replayed']
    new_key=str(uuid4())
    assert (await commit(view,new_key))['replayed']
    assert (await ok('/api/sales-history/requests/'+new_key))['replayed']
    assert (await request('/api/sales-history/day','PUT',{**daily(value='2026-10-10'), 'request_id':new_key}))[0]==409
    again=await preview(text)
    assert again['valid'] and again['new_rows']==0 and again['unchanged_rows']==2
    assert (await commit(again))['inserted']==0
    assert await ok('/api/products')==before and await ok('/api/sales')==sales
    with code.database() as connection:
        assert connection.execute('SELECT COUNT(*) FROM daily_sales_history').fetchone()[0]==2
        assert planning_revision(connection,1)==2


async def invalid_csv(fake,draft):
    header='date,sku,units_sold,source,stockout\n'
    cases=[
        '2026-10-14,PEN,0,actual,0', '2026-10-15,PEN,4,actual,0',
        '2026-02-30,PEN,4,actual,0', '20261012,PEN,4,actual,0',
        '2026-10-12,UNKNOWN,4,actual,0', '2026-10-12,PEN,,actual,0',
        '2026-10-12,PEN,-1,actual,0', '2026-10-12,PEN,1.5,actual,0',
        '2026-10-12,PEN,1000001,actual,0', '2026-10-12,PEN,4,invented,0',
        '2026-10-12,PEN,4,actual,yes', '2026-10-12,PEN,4,actual,0,EXTRA',
        '2026-10-12,PEN,4,actual',
        '2026-10-12,PEN,4,actual,0\n2026-10-12,pen,4,actual,0',
    ]
    for row in cases:
        result=await preview(header+row+'\n')
        assert not result['valid'] and result['preview_id'] is None and result['invalid_rows']>0,row
    assert (await request('/api/sales-history/import/preview','POST',{'csv_text':'sku,date,wrong\nPEN,2026-10-12,3\n'}))[0]==422
    assert (await request('/api/sales-history/import/preview','POST',{'csv_text':header}))[0]==422
    assert (await request('/api/sales-history/import/preview','POST',{'csv_text':header+'"unterminated'}))[0]==422
    with code.database() as connection:
        assert connection.execute('SELECT COUNT(*) FROM daily_sales_history').fetchone()[0]==0
        assert connection.execute('SELECT COUNT(*) FROM sales_history_previews').fetchone()[0]==0


async def stale_preview_rollback(fake,draft):
    view=await preview('date,sku,units_sold\n2026-10-12,PEN,4\n2026-10-11,PEN,8\n')
    await save_day(value='2026-10-11',units=7)
    body={'request_id':str(uuid4()),'preview_id':view['preview_id']}
    assert (await request('/api/sales-history/import/commit','POST',body))[0]==409
    with code.database() as connection:
        assert connection.execute("SELECT COUNT(*) FROM daily_sales_history WHERE sale_date='2026-10-12'").fetchone()[0]==0
        assert connection.execute('SELECT revision FROM sales_history_revisions').fetchone()[0]==1
        assert connection.execute('SELECT COUNT(*) FROM sales_history_requests WHERE request_id=?',(body['request_id'],)).fetchone()[0]==0


async def concurrent_commit(fake,draft):
    view=await preview('date,sku,units_sold\n2026-10-12,PEN,4\n')
    keys=[str(uuid4()),str(uuid4())]
    results=await asyncio.gather(*(request('/api/sales-history/import/commit','POST',{'request_id':key,'preview_id':view['preview_id']}) for key in keys))
    assert all(status==200 for status,_ in results)
    assert sorted(result['replayed'] for _,result in results)==[False,True]
    with code.database() as connection:
        assert connection.execute('SELECT COUNT(*) FROM daily_sales_history').fetchone()[0]==1
        assert connection.execute('SELECT revision FROM sales_history_revisions').fetchone()[0]==1
    for key in keys:
        assert (await ok('/api/sales-history/requests/'+key))['replayed']


async def concurrent_correction(fake,draft):
    results=await asyncio.gather(request('/api/sales-history/day','PUT',daily(units=4)),request('/api/sales-history/day','PUT',daily(units=7)))
    assert sorted(status for status,_ in results)==[200,409]
    record=await ok('/api/sales-history/day?product_id=1&sale_date=2026-10-12')
    assert record['revision']==1 and record['units_sold'] in (4,7)
    assert (await ok('/api/products'))[0]['stock']==17


async def demo_and_stockout(fake,draft):
    original=await ok('/api/restock')
    await save_day(units=300,source='demo')
    assert await ok('/api/restock')==original
    with code.database() as connection: assert planning_revision(connection,1)==1
    await save_day(units=4,source='actual',revision=1,stockout=True)
    flagged=(await ok('/api/restock'))['items'][0]
    assert flagged['average_daily_sales'] is None and 'stockout' in flagged['reason']
    await save_day(value='2026-10-11',units=2)
    actual=(await ok('/api/restock'))['items'][0]
    assert actual['units_sold']==2 and actual['days_used']==1 and actual['average_daily_sales']==2
    history=await ok('/api/sales-history?product_id=1&days=7')
    assert history['actual_days']==2 and history['eligible_actual_days']==1 and history['stockout_days']==1


async def stale_draft_frozen_approved(fake,draft):
    await save_day(units=4)
    assert (await request('/api/orders/1/approve','POST',{'request_id':str(uuid4()),'expected_version':1,'spending_limit':'100.00'}))[0]==409
    await ok('/api/orders/1/cancel','POST',{'expected_version':1})
    new=(await ok('/api/orders','POST',{'request_id':str(uuid4()),'budget':'100.00'},status=201))['order']
    approved=(await ok('/api/orders/2/approve','POST',{'request_id':str(uuid4()),'expected_version':1,'spending_limit':'100.00'}))['order']
    await save_day(units=20,revision=1)
    after=await ok('/api/orders/2')
    assert after['items']==approved['items'] and after['grand_total']==approved['grand_total'] and after['version']==2
    receipt=await ok('/api/orders/2/paypal/create','POST',{'expected_version':2})
    assert fake.creates[0][0]['purchase_units'][0]['amount']['value']==approved['grand_total']
    assert receipt['paypal_order_id']


async def template_demo_export(fake,draft):
    status,text=await raw_request('/api/sales-history/template?product_id=1')
    rows=list(csv.DictReader(io.StringIO(text)))
    assert status==200 and rows[0]['sku']=='PEN' and rows[0]['units_sold']==''
    assert not (await preview(text))['valid']  # Template needs actual data, not guessed zeros.
    _,text=await raw_request('/api/sales-history/demo?product_id=1')
    rows=list(csv.DictReader(io.StringIO(text)))
    assert len(rows)==60 and all(row['source']=='demo' for row in rows)
    assert rows[-1]['date']=='2026-10-12' and any(row['units_sold']=='0' for row in rows)
    before=await ok('/api/restock')
    await commit(await preview(text))
    assert await ok('/api/restock')==before
    history=await ok('/api/sales-history?product_id=1&days=90')
    assert history['demo_days']==60 and history['actual_days']==0
    _,exported=await raw_request('/api/sales-history/export?product_id=1')
    rows=list(csv.DictReader(io.StringIO(exported)))
    assert len(rows)==60 and all(row['source']=='demo' for row in rows)
    assert (await preview(exported))['unchanged_rows']==60


async def invalid_api_expiry(fake,draft):
    for changes in ({'units_sold':True},{'units_sold':-1},{'units_sold':1.5},{'stockout':1},{'quantity':5},
                    {'sale_date':'2026-10-14'},{'sale_date':'2026-10-15'},{'product_id':True}):
        assert (await request('/api/sales-history/day','PUT',{**daily(),**changes}))[0]==422
    assert (await request('/api/sales-history/day','PUT',daily(product=999)))[0]==404
    assert (await request('/api/sales-history?product_id=1&days=1000'))[0]==422
    view=await preview('date,sku,units_sold\n2026-10-12,PEN,4\n')
    with code.database() as connection:
        connection.execute('UPDATE sales_history_previews SET created_at=?',((datetime.now(timezone.utc)-timedelta(minutes=21)).isoformat(),))
    assert (await request('/api/sales-history/import/commit','POST',{'request_id':str(uuid4()),'preview_id':view['preview_id']}))[0]==409
    with code.database() as connection:
        assert connection.execute('SELECT COUNT(*) FROM daily_sales_history').fetchone()[0]==0


async def run():
    original_today=code.shop_today
    for check in (zero_missing_live,daily_retries_edits,conflicting_logged_total,csv_commit_retries,invalid_csv,
                  stale_preview_rollback,concurrent_commit,concurrent_correction,demo_and_stockout,
                  stale_draft_frozen_approved,template_demo_export,invalid_api_expiry):
        await scenario(check);print('PASS:',check.__name__)
    code.shop_today=original_today
    print('PASS: daily data quality, actual/demo separation, safe CSV preview/commit, zero/missing distinction, stale edits/imports and unchanged stock/payments.')


if __name__=='__main__': asyncio.run(run())
