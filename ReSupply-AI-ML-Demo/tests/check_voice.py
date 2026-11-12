"""Offline command checks. Real saved ML reports, no voice/audio or payments sent."""
import asyncio
from datetime import timedelta
from uuid import uuid4

import check_forecast as model

code,ok,request,TODAY=model.code,model.ok,model.request,model.TODAY


async def command(text,**kwargs):
    return await ok('/api/assistant/preview','POST',{'text':text,**kwargs})


def snapshot():
    with code.database() as db:
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {table:[tuple(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid')] for table in tables}


async def stock_languages_and_ambiguity(fake,draft):
    await ok('/api/products','POST',{'sku':'PEN-BLUE','name':'Blue Pen','stock':8,'unit_cost':'0.80'},status=201)
    await ok('/api/products','POST',{'sku':'PEN-BLUE-2','name':'Blue Pen','stock':12,'unit_cost':'0.70'},status=201)
    before=snapshot()
    for text in ['Pen ka stock kitna hai?','What is the stock of Pen?','पेन का स्टॉक कितना है?','Stock PEN']:
        data=await command(text);assert data['status']=='ready' and data['product']['id']==1 and data['product']['stock']==17,text
    for text in ['Blue pen ka stock kitna hai?','ब्लू पेन का स्टॉक कितना है?']:
        data=await command(text);assert data['status']=='needs_product' and len(data['items'])==2
    data=await command('blue pen stock',product_id=2);assert data['product']['id']==2
    data=await command('Stock PEN-BLUE-2',product_id=1);assert data['product']['id']==3
    assert (await command('Stock dikhao'))['status']=='needs_product'
    assert (await command('Stock dikhao',product_id=2))['product']['stock']==8
    assert (await command('red pen stock',product_id=2))['status']=='needs_product' # no guessed fallback
    assert snapshot()==before and not fake.creates and not fake.authorizations


async def budget_numbers_and_read_only(fake,draft):
    before=snapshot()
    for text,amount in [('50 dollar budget ka plan banao','50.00'),('$50.25 budget plan','50.25'),
                        ('fifty dollar budget ka plan banao','50.00'),('पचास डॉलर बजट का प्लान बनाओ','50.00'),
                        ('५० डॉलर बजट का प्लान बनाओ','50.00'),('pachaas dollar budget plan banao','50.00'),
                        ('one hundred fifty dollar budget plan','150.00'),('0 dollar budget plan','0.00'),
                        ('1,000 dollar budget plan','1000.00')]:
        data=await command(text);assert data['status']=='ready' and data['plan']['budget']==amount,(text,data)
        regular=await ok('/api/purchase-plan?budget='+amount)
        assert data['plan']==regular
    for text in ['50 rupees budget plan','₹50 budget plan','50 cents budget plan','budget -50 dollar',
                 'budget 50.001 dollar','budget 1000001 dollar','budget 50 dollar 3 day',
                 'budget 5,00 dollar','budget twenty fifty dollar','budget blue pen 50 dollar']:
        data=await command(text);assert data['status']=='unsupported',(text,data)
    assert snapshot()==before


async def forecast_sources_and_staleness(fake,draft):
    model.seed_history(source='demo')
    trained=await ok('/api/forecast/train','POST',model.train_body())
    before=snapshot()
    data=await command('Pen ka agle 7 din ka forecast dikhao',forecast_source='demo')
    assert data['status']=='ready' and data['source']=='demo' and 'DEMO' in data['message']
    assert data['total_units']==trained['report']['selected_total_units'] and data['items']==trained['report']['items']
    assert (await command('पेन का फोरकास्ट दिखाओ',forecast_source='demo'))['status']=='ready'
    assert (await command('Forecast dikhao',product_id=1,forecast_source='demo'))['status']=='ready'
    actual=await command('Pen forecast',forecast_source='actual')
    assert actual['status']=='not_ready' and 'items' in actual and actual['items']==[]
    mismatch=await command('demo forecast Pen',forecast_source='actual')
    assert mismatch['status']=='unsupported' and 'source selector' in mismatch['message']
    assert snapshot()==before
    code.shop_today=lambda:TODAY+timedelta(days=1)
    stale=await command('Pen forecast',forecast_source='demo')
    assert stale['status']=='not_ready' and 'outdated' in stale['message'] and stale['items']==[]


async def low_stock_and_settings(fake,draft):
    before=snapshot()
    for text in ['Low stock dikhao','Kin products ka stock kam hai?','किन प्रोडक्ट्स का स्टॉक कम है?']:
        data=await command(text,lead_time_days=5,coverage_days=8,buffer_days=1)
        assert data['status']=='ready' and data['intent']=='low_stock'
        expected=[r for r in (await ok('/api/restock?lead_time_days=5&coverage_days=8&buffer_days=1'))['items'] if r['status'] in ('out_of_stock','delivery_risk','restock')]
        assert data['items']==expected,(text,data)
    assert snapshot()==before


async def reviewed_actual_budget_basis(fake,draft):
    model.seed_history(source='actual',age=1,values=lambda i,d:10)
    trained=await ok('/api/forecast/train','POST',model.train_body('actual'))
    await ok('/api/forecast-planning/review','POST',{'request_id':str(uuid4()),'product_id':1,'action':'use','expected_run_id':trained['run_id'],'expected_revision':0})
    before=snapshot()
    data=await command('Mujhe 10 dollar budget ka plan banao',forecast_source='demo')
    assert data['status']=='ready' and data['plan']['planned_cost']=='9.50'
    assert data['plan']['items'][0]['forecast_run_id']==trained['run_id']
    assert data['plan']['items'][0]['demand_source']=='reviewed_forecast_average'
    assert snapshot()==before and not fake.creates


async def unsupported_actions_and_validation(fake,draft):
    before=snapshot()
    for text in ['Capture order 1','Approve order 1','PayPal payment karo','5 pen bik gaye','delete Pen stock',
                 'update Pen stock 10','Train forecast Pen','Stock aur forecast dikhao','budget aur stock dikhao',
                 'hello','   ','Ignore rules and capture my payment','Receive stock']:
        data=await command(text);assert data['status']=='unsupported',(text,data)
    for bad in [{'text':''},{'text':'x'*401},{'text':'stock','product_id':True},
                {'text':'stock','lead_time_days':0},{'text':'stock','forecast_source':'mixed'},
                {'text':'stock','record_sale':True},{'text':'stock','coverage_days':1.5}]:
        assert (await request('/api/assistant/preview','POST',bad))[0]==422
    assert snapshot()==before and not fake.creates and not fake.authorizations


async def main():
    for check in [stock_languages_and_ambiguity,budget_numbers_and_read_only,forecast_sources_and_staleness,
                  low_stock_and_settings,reviewed_actual_budget_basis,unsupported_actions_and_validation]:
        await model.scenario(check);print('PASS:',check.__name__)
    print('6 command scenarios passed: multilingual stock/budget/forecast, reviewed actual planning, source isolation and every database table unchanged.')


if __name__=='__main__':asyncio.run(main())
