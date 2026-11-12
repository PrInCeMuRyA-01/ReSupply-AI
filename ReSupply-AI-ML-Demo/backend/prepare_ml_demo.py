"""Prepare a fresh-date synthetic ML demo. No payment calls and no real-shop seeding."""
import json
from datetime import datetime, timezone

from demo_shop import prepare_samples, setting
from easy_autopilot import policy, update_forecasts
from shop_workspace import demo_scope

HISTORY_DAYS = 90


def prepare_ml_demo(code):
    """Idempotent preparation; retain stock, corrections, settings, orders and holds."""
    code.initialize_database()
    with demo_scope():
        code.initialize_database()
        today=code.shop_today()
        with code.database() as db:
            db.execute('BEGIN IMMEDIATE')
            added=prepare_samples(db,today,history_days=HISTORY_DAYS,varied=True)
            current=policy(db)
            # Launching the dedicated demo opts only this isolated sample shop in.
            # A saved policy, including an owner's pause, is never overwritten.
            if current['revision']==0:
                body={**current['settings'],'enabled':True,'auto_history':False,'zero_days_confirmed':False}
                db.execute('INSERT INTO easy_auto_policy VALUES(1,1,?)',(json.dumps(body,sort_keys=True),))
            marker={'dataset':'synthetic-weekday-patterns-v1','minimum_recent_days':HISTORY_DAYS,
                'prepared_at':datetime.now(timezone.utc).isoformat(),'source':'demo'}
            db.execute("INSERT INTO demo_shop_settings VALUES('ml-demo-ready',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(marker),))
        # This fits the real sklearn model, evaluates it and saves the measured report.
        # Fitting remains outside database transactions; the service checks freshness.
        update_forecasts(code.database,today)
        with code.database() as db:
            products=[]
            for row in db.execute('SELECT p.id,p.name,p.sku,p.stock FROM products p ORDER BY id').fetchall():
                saved=db.execute("SELECT id,report FROM demand_forecast_runs WHERE product_id=? AND source='demo' ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
                report=json.loads(saved['report']) if saved else None
                products.append({**dict(row),'training_days':report['training_days'] if report else 0,
                    'selected_method':report['selected_method'] if report else None,
                    'model_mae':report['evaluation']['model_mae'] if report else None,
                    'baseline_mae':report['evaluation']['baseline_mae'] if report else None})
            return {'source':'demo','synthetic':True,'shop_date':today.isoformat(),'added_history_rows':added,
                'daily_history_rows':db.execute('SELECT COUNT(*) FROM daily_sales_history').fetchone()[0],
                'products':products,'auto_enabled':policy(db)['settings']['enabled'],
                'message':'Synthetic data only. Real model training and measured errors. Payment still needs your Sandbox checkout approval.'}


if __name__=='__main__':
    import main
    result=prepare_ml_demo(main)
    print(json.dumps(result,indent=2))
