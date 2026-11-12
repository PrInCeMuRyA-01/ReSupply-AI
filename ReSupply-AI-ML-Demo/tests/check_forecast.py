"""Offline forecasts with real sklearn fits; PayPal remains mocked."""
import asyncio
from datetime import date, timedelta
from math import isfinite
from pathlib import Path
import tempfile
from unittest.mock import patch
from uuid import uuid4

import check_paypal as base
import demand_forecast as forecast
from sales_history import save_total

code, request, ok = base.code, base.request, base.ok
TODAY = date(2026, 10, 14)


def seed_history(source="demo", count=60, age=2, values=None):
    end = TODAY - timedelta(days=age)
    with code.database() as db:
        for index in range(count):
            day = end - timedelta(days=count - index - 1)
            units = values(index, day) if values else (25 if day.weekday() >= 5 else 5)
            save_total(db, {"product_id":1, "sale_date":day.isoformat(), "units_sold":units,
                            "source":source, "stockout":False})


def train_body(source="demo", product=1):
    return {"request_id":str(uuid4()), "product_id":product, "source":source}


async def scenario(check):
    with tempfile.TemporaryDirectory(prefix="resupply-forecast-") as folder:
        code.DB_PATH = Path(folder) / "resupply.db"
        code.shop_today = lambda:TODAY
        fake = base.FakePayPal()
        draft = await base.seed(fake)
        await check(fake, draft)


async def demo_import_and_train(fake, draft):
    # Exercise the exact Step 12 CSV route before the real ML training route.
    import check_sales_history as history
    status, text = await history.raw_request('/api/sales-history/demo?product_id=1')
    assert status == 200
    preview = await ok('/api/sales-history/import/preview', 'POST', {'csv_text':text})
    await ok('/api/sales-history/import/commit', 'POST', {'request_id':str(uuid4()), 'preview_id':preview['preview_id']})
    before = [await ok('/api/products'), await ok('/api/sales'), await ok('/api/orders'), await ok('/api/restock'), await ok('/api/purchase-plan')]
    assert not (await ok('/api/forecast?product_id=1&source=actual'))['ready']
    body = train_body()
    trained = await ok('/api/forecast/train', 'POST', body)
    r = trained['report']
    assert trained['report_current'] and r['demo'] and r['training_days'] == 60 and r['training_samples'] == 46
    assert r['bridge_days'] == 2 and r['bridge_estimates'][0]['date'] == '2026-10-13'
    assert [row['date'] for row in r['items']] == [(TODAY + timedelta(days=i)).isoformat() for i in range(1,8)]
    assert r['evaluation']['test_days'] == 14 and all(isfinite(row['model_units']) and row['model_units'] >= 0 for row in r['items'])
    assert trained['advice'] is None and 'synthetic' in trained['message']
    assert before == [await ok('/api/products'), await ok('/api/sales'), await ok('/api/orders'), await ok('/api/restock'), await ok('/api/purchase-plan')]
    assert not fake.creates and not fake.authorizations
    retry = await ok('/api/forecast/train', 'POST', body)
    assert retry['replayed'] and retry['run_id'] == trained['run_id'] and retry['report'] == r
    assert (await ok('/api/forecast/requests/' + body['request_id']))['run_id'] == trained['run_id']
    assert (await request('/api/forecast/train', 'POST', {**body,'source':'actual'}))[0] == 409
    with code.database() as db:
        assert db.execute('SELECT COUNT(*) FROM demand_forecast_runs').fetchone()[0] == 1


async def weekly_pattern_quality_and_leakage(fake, draft):
    seed_history(source='actual', count=90, age=1)
    fits, predicts = [], []
    factory = forecast.new_model
    class Spy:
        def __init__(self): self.model = factory()
        def fit(self, X, y):
            fits.append(([list(row) for row in X], list(y)))
            self.model.fit(X,y)
            return self
        def predict(self, X):
            predicts.append([list(row) for row in X])
            return self.model.predict(X)
    with patch.object(forecast,'new_model',Spy):
        data = await ok('/api/forecast/train','POST',train_body('actual'))
    r = data['report']
    assert r['selected_method'] == 'random_forest' and r['evaluation']['model_mae'] < r['evaluation']['baseline_mae'] * .95
    assert len(fits) == 4  # three older->later folds plus final full-data refit
    # The first test forecast is later than every training label. Its previous-
    # day feature is known, and its second step uses a prediction, not a label.
    cut = 90 - 3 * 8
    first_day = TODAY - timedelta(days=90)
    series = [25 if (first_day+timedelta(days=i)).weekday() >= 5 else 5 for i in range(90)]
    assert fits[0][1] == series[14:cut]
    assert fits[0][0][-1][0] == series[cut-2]
    assert predicts[0][0][0] == series[cut-1]
    first_prediction = factory().fit(*fits[0]).predict(predicts[0])[0]
    assert abs(predicts[1][0][0] - first_prediction) < 1e-9
    for fold in r['evaluation']['folds']:
        assert fold['training_end'] < fold['test_start'] <= fold['test_end']
    assert data['advice']['seven_day_gap'] == max(0,data['advice']['forecast_units_rounded_up']-17)


async def zero_days_and_baseline_fallback(fake, draft):
    seed_history(source='actual', values=lambda i,d:0, age=1)
    data = await ok('/api/forecast/train','POST',train_body('actual'))
    r = data['report']
    assert r['selected_method'] == 'seven_day_mean' and r['selected_total_units'] == 0
    assert r['evaluation']['model_mae'] == r['evaluation']['baseline_mae'] == 0
    assert r['evaluation']['improvement_percent'] is None
    assert data['advice']['seven_day_gap'] == 0
    assert all(item['selected_units'] == 0 for item in r['items'])


async def missing_stockout_and_sources(fake, draft):
    seed_history(source='actual')
    with code.database() as db:
        db.execute("DELETE FROM daily_sales_history WHERE sale_date='2026-10-01'")
    data = await ok('/api/forecast?product_id=1&source=actual')
    assert not data['ready'] and data['coverage']['consecutive_days'] == 11
    assert (await request('/api/forecast/train','POST',train_body('actual')))[0] == 422
    with code.database() as db:
        save_total(db, {'product_id':1,'sale_date':'2026-10-01','units_sold':0,'source':'actual','stockout':True})
    assert not (await ok('/api/forecast?product_id=1&source=actual'))['ready']
    with code.database() as db:
        save_total(db, {'product_id':1,'sale_date':'2026-10-01','units_sold':0,'source':'demo','stockout':False})
    data = await ok('/api/forecast?product_id=1&source=actual')
    assert data['coverage']['other_source_days'] == 1 and not data['ready']
    with code.database() as db:
        save_total(db, {'product_id':1,'sale_date':'2026-10-01','units_sold':0,'source':'actual','stockout':False})
    assert (await ok('/api/forecast?product_id=1&source=actual'))['ready']


async def stale_dates_and_minimum(fake, draft):
    seed_history(count=55)
    assert not (await ok('/api/forecast?product_id=1&source=demo'))['ready']
    with code.database() as db: db.execute('DELETE FROM daily_sales_history')
    seed_history(count=56, age=7)
    data = await ok('/api/forecast/train','POST',train_body())
    assert data['report']['evaluation']['test_days'] == 7 and data['report']['bridge_days'] == 7
    code.shop_today = lambda:TODAY + timedelta(days=1)
    stale = await ok('/api/forecast?product_id=1&source=demo')
    assert not stale['ready'] and not stale['report_current'] and stale['advice'] is None


async def changed_history_and_live_stock(fake, draft):
    seed_history(source='actual', age=1)
    body = train_body('actual')
    data = await ok('/api/forecast/train','POST',body)
    # Stock changes affect the live comparison, without rewriting saved training.
    await ok('/api/products/1/stock','PATCH',{'stock':1})
    updated = await ok('/api/forecast?product_id=1&source=actual')
    assert updated['report_current'] and updated['report'] == data['report'] and updated['advice']['stock_now'] == 1
    with code.database() as db:
        save_total(db, {'product_id':1,'sale_date':'2026-07-01','units_sold':99,'source':'demo','stockout':False})
    assert (await ok('/api/forecast?product_id=1&source=actual'))['report_current']
    with code.database() as db:
        row = dict(db.execute("SELECT * FROM daily_sales_history WHERE sale_date='2026-10-13'").fetchone())
    identical = {key:row[key] for key in ('product_id','sale_date','units_sold','source')}
    await ok('/api/sales-history/day','PUT',{**identical,'stockout':False,'expected_revision':row['revision'],'request_id':str(uuid4())})
    assert (await ok('/api/forecast?product_id=1&source=actual'))['report_current']
    await ok('/api/sales-history/day','PUT',{**identical,'units_sold':30,'stockout':False,'expected_revision':row['revision'],'request_id':str(uuid4())})
    stale = await ok('/api/forecast?product_id=1&source=actual')
    assert not stale['report_current'] and stale['advice'] is None
    assert not (await ok('/api/forecast/train','POST',body))['report_current']  # exact retry returns its old receipt
    fresh = await ok('/api/forecast/train','POST',train_body('actual'))
    assert fresh['report_current'] and fresh['run_id'] != data['run_id']


async def concurrent_retry_once(fake, draft):
    seed_history()
    body = train_body()
    left, right = await asyncio.gather(ok('/api/forecast/train','POST',body),ok('/api/forecast/train','POST',body))
    assert left['run_id'] == right['run_id'] and left['report'] == right['report']
    with code.database() as db: assert db.execute('SELECT COUNT(*) FROM demand_forecast_runs').fetchone()[0] == 1


async def change_during_training_rolls_back(fake, draft):
    seed_history()
    real = forecast.train_report
    def changed(snapshot):
        result = real(snapshot)
        with code.database() as db:
            save_total(db, {'product_id':1,'sale_date':'2026-10-12','units_sold':60,'source':'demo','stockout':False})
        return result
    with patch.object(forecast,'train_report',changed):
        status, data = await request('/api/forecast/train','POST',train_body())
    assert status == 409 and 'changed during training' in data['detail']
    with code.database() as db: assert db.execute('SELECT COUNT(*) FROM demand_forecast_runs').fetchone()[0] == 0


async def invalid_api_and_dependency(fake, draft):
    assert (await request('/api/forecast?product_id=0'))[0] == 422
    assert (await request('/api/forecast?product_id=999'))[0] == 404
    assert (await request('/api/forecast?product_id=1&source=mixed'))[0] == 422
    body = train_body()
    for invalid in ({**body,'product_id':True},{**body,'product_id':'1'},{**body,'source':'mixed'},
                    {**body,'request_id':'bad'},{**body,'capture':True}):
        assert (await request('/api/forecast/train','POST',invalid))[0] == 422
    assert (await request('/api/forecast/requests/'+str(uuid4())))[0] == 404
    seed_history()
    import sys
    with patch.dict(sys.modules, {'sklearn.ensemble':None}):
        status, data = await request('/api/forecast/train','POST',body)
    assert status == 503 and 'pip install' in data['detail']
    assert (await ok('/api/products'))[0]['stock'] == 17


async def main():
    for check in [demo_import_and_train, weekly_pattern_quality_and_leakage, zero_days_and_baseline_fallback,
                  missing_stockout_and_sources, stale_dates_and_minimum, changed_history_and_live_stock,
                  concurrent_retry_once, change_during_training_rolls_back, invalid_api_and_dependency]:
        await scenario(check)
        print('PASS:', check.__name__)
    print('9 forecast scenarios passed. Real ML fits; no PayPal requests sent.')


if __name__ == '__main__':
    asyncio.run(main())
