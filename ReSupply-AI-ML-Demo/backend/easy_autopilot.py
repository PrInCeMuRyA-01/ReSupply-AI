"""Stock updates -> automatic demand checks -> one unpaid draft. Money needs PayPal consent."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from math import ceil
import threading
import sqlite3
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from demand_forecast import history_snapshot, train_report, response_view
from forecast_purchasing import report_is_current
from sales_history import daily_row, logged_units, save_total
from shop_workspace import planning_source
from easy_shop import replay, receipt


def initialize_autopilot(db):
    db.execute('CREATE TABLE IF NOT EXISTS easy_auto_policy (id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,body TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS easy_auto_orders (order_id INTEGER PRIMARY KEY REFERENCES purchase_orders(id),signature TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS easy_tracking (product_id INTEGER PRIMARY KEY REFERENCES products(id),started_on TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS easy_stockout_days (product_id INTEGER REFERENCES products(id),sale_date TEXT NOT NULL,PRIMARY KEY(product_id,sale_date))')


class AutoPolicy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision: int=Field(ge=0,strict=True)
    enabled: bool=Field(strict=True)
    spending_limit: Decimal=Field(gt=0,le=1000000,decimal_places=2)
    shipping: Decimal=Field(default=Decimal('0'),ge=0,le=1000000,decimal_places=2)
    tax: Decimal=Field(default=Decimal('0'),ge=0,le=1000000,decimal_places=2)
    coverage_days: int=Field(default=7,ge=1,le=30,strict=True)
    buffer_days: int=Field(default=2,ge=0,le=14,strict=True)
    auto_history: bool=Field(default=False,strict=True)
    zero_days_confirmed: bool=Field(default=False,strict=True)


class StockEntry(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id: UUID
    product_id: int=Field(gt=0,le=9223372036854775807,strict=True)
    mode: Literal['sold','remaining']='sold'
    quantity: int=Field(ge=0,le=1000000,strict=True)
    expected_stock: int=Field(ge=0,le=1000000,strict=True)


class PayReady(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id: UUID
    order_id: int=Field(gt=0,le=9223372036854775807,strict=True)
    expected_version: int=Field(gt=0,strict=True)
    expected_policy_revision: int=Field(ge=0,strict=True)


def policy(db):
    row=db.execute('SELECT * FROM easy_auto_policy WHERE id=1').fetchone()
    return {'revision':row['revision'],'settings':json.loads(row['body'])} if row else {
        'revision':0,'settings':{'enabled':False,'spending_limit':'100.00','shipping':'0.00','tax':'0.00',
            'coverage_days':7,'buffer_days':2,'auto_history':False,'zero_days_confirmed':False}}


def close_tracked_days(db,today,settings):
    if not settings['auto_history']:return
    source=planning_source()
    for product in db.execute('SELECT * FROM easy_tracking').fetchall():
        start=date.fromisoformat(product['started_on'])
        # Only dates since opt-in, never a synthetic backfill before tracking began.
        for offset in range(max(0,(today-start).days)):
            day=(start+timedelta(days=offset)).isoformat()
            if daily_row(db,product['product_id'],day):continue
            units=logged_units(db,product['product_id'],day)
            if not units and not settings['zero_days_confirmed']:continue
            stockout=db.execute('SELECT 1 FROM easy_stockout_days WHERE product_id=? AND sale_date=?',
                (product['product_id'],day)).fetchone() is not None
            save_total(db,{'product_id':product['product_id'],'sale_date':day,'source':source,'units_sold':units,'stockout':stockout})


def update_forecasts(database,today):
    """Train ready products, preserve date/fingerprint checks, apply under the opt-in policy."""
    source=planning_source()
    with database() as db:ids=[r['id'] for r in db.execute('SELECT id FROM products')]
    for product_id in ids:
        with database() as db:
            db.execute('BEGIN')
            snapshot=history_snapshot(db,product_id,source,today)
            if not snapshot['ready']:continue
            saved=db.execute('SELECT * FROM demand_forecast_runs WHERE product_id=? AND source=? ORDER BY id DESC LIMIT 1',
                (product_id,source)).fetchone()
            current=report_is_current(db,saved,today)
        report=None if current else train_report(snapshot)
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            active=policy(db)
            if not active['settings']['enabled']:return
            fresh=history_snapshot(db,product_id,source,today)
            if fresh['fingerprint']!=snapshot['fingerprint'] or fresh['shop_date']!=snapshot['shop_date']:
                raise HTTPException(409,'Sales history changed while checking AI. Update suggestions again.')
            latest=db.execute('SELECT * FROM demand_forecast_runs WHERE product_id=? AND source=? ORDER BY id DESC LIMIT 1',
                (product_id,source)).fetchone()
            if report_is_current(db,latest,today):saved=latest
            else:
                stamp=datetime.now(timezone.utc).isoformat()
                cursor=db.execute('INSERT INTO demand_forecast_runs(request_id,request_payload,product_id,source,data_fingerprint,shop_date,report,created_at) VALUES(?,?,?,?,?,?,?,?)',
                    (str(uuid4()),json.dumps({'product_id':product_id,'source':source},sort_keys=True),product_id,source,
                        fresh['fingerprint'],fresh['shop_date'],json.dumps(report,allow_nan=False),stamp))
                saved=db.execute('SELECT * FROM demand_forecast_runs WHERE id=?',(cursor.lastrowid,)).fetchone()
            old=db.execute('SELECT * FROM forecast_planning_reviews WHERE product_id=?',(product_id,)).fetchone()
            if not old or old['run_id']!=saved['id']:
                db.execute('INSERT INTO forecast_planning_reviews VALUES(?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET run_id=excluded.run_id,revision=excluded.revision,updated_at=excluded.updated_at',
                    (product_id,saved['id'],(old['revision'] if old else 0)+1,datetime.now(timezone.utc).isoformat()))


def autopilot_router(database,shop_today,calculate_plan,calculate_restock,create_draft,approve_draft,cancel_draft,order_details):
    router=APIRouter(prefix='/api/easy',tags=['Stock autopilot'])
    # Serialize local planning; core SQLite transactions also reject stale stock/quotes and overlapping orders.
    locks={'actual':threading.RLock(),'demo':threading.RLock()}

    def run():
        with locks[planning_source()]:
            today=shop_today()
            with database() as db:
                db.execute('BEGIN IMMEDIATE')
                current=policy(db);settings=current['settings']
                if not settings['enabled']:return {**current,'order':None,'message':'Finish the one-time setup to turn on automatic restocking.'}
                for p in db.execute('SELECT id,stock FROM products').fetchall():
                    db.execute('INSERT OR IGNORE INTO easy_tracking VALUES(?,?)',(p['id'],today.isoformat()))
                    if p['stock']==0:db.execute('INSERT OR IGNORE INTO easy_stockout_days VALUES(?,?)',(p['id'],today.isoformat()))
                close_tracked_days(db,today,settings)
                open_orders=db.execute("SELECT o.id,o.status,a.signature FROM purchase_orders o LEFT JOIN easy_auto_orders a ON a.order_id=o.id WHERE o.status IN ('draft','approved') ORDER BY o.id").fetchall()
                # Never replace an approved order or dismiss an uncertain PayPal result.
                if open_orders and (len(open_orders)>1 or open_orders[0]['status']=='approved' or open_orders[0]['signature'] is None):
                    order=order_details(db,open_orders[0]['id']).model_dump(mode='json')
                    return {**current,'order':order,'message':'Finish this saved order first. Its payment and quantities are preserved.'}
            update_forecasts(database,today)
            with database() as db:
                db.execute('BEGIN')
                fresh=policy(db)
                if fresh['revision']!=current['revision']:raise HTTPException(409,'Auto settings changed. Refresh the shop.')
                budget=Decimal(settings['spending_limit'])-Decimal(settings['shipping'])-Decimal(settings['tax'])
                plan=calculate_plan(db,budget,3,settings['coverage_days'],settings['buffer_days'])
                low=any((p.suggested_quantity or 0)>0 and p.average_daily_sales is not None and
                    p.stock<=ceil(p.average_daily_sales*(p.lead_time_days+settings['buffer_days']))
                    for p in calculate_restock(db,3,settings['coverage_days'],settings['buffer_days']).items)
                # This signature includes the complete planning result, not just the total price.
                signature=json.dumps({'plan':plan.model_dump(mode='json'),'policy_revision':current['revision']},sort_keys=True)
                if open_orders and low and open_orders[0]['signature']==signature:
                    return {**current,'order':order_details(db,open_orders[0]['id']).model_dump(mode='json'),
                        'message':'Low stock detected. Your order is ready; pay when you choose.'}
            if open_orders:cancel_draft(open_orders[0]['id'])
            if not low:return {**current,'order':None,'message':('Some products need a daily-sales estimate or recorded sales before restocking can be estimated. Use the setup or Sales history tools.' if plan.no_history_products else 'Stock is sufficient for the current delivery and buffer estimate. Keep recording sales.')}
            if not plan.planned_units:return {**current,'order':None,'message':'Stock is low, but this budget cannot cover a purchase. Review the budget or demand data.'}
            if plan.planned_without_supplier:return {**current,'order':None,'message':'Choose a supplier for the planned products. Quick setup saves and selects one together.'}
            result=create_draft(budget,settings['coverage_days'],settings['buffer_days'])
            with database() as db:
                db.execute('INSERT OR IGNORE INTO easy_auto_orders VALUES(?,?)',(result.id,signature))
            return {**current,'order':result.model_dump(mode='json'),'message':'Low stock detected. Your order is ready; pay when you choose.'}

    @router.get('/autopilot')
    def get_policy():
        with database() as db:return policy(db)

    @router.put('/autopilot')
    def save_policy(data:AutoPolicy):
        if data.shipping+data.tax>=data.spending_limit:
            raise HTTPException(422,'Spending limit must leave some money after shipping and tax.')
        with locks[planning_source()]:
            with database() as db:
                db.execute('BEGIN IMMEDIATE')
                old=policy(db)
                if old['revision']!=data.expected_revision:raise HTTPException(409,'Settings changed in another tab. Reload first.')
                if old['settings']['enabled']:
                    close_tracked_days(db,shop_today(),old['settings'])
                body=data.model_dump(mode='json',exclude={'expected_revision'})
                db.execute('INSERT INTO easy_auto_policy VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,body=excluded.body',
                    (old['revision']+1,json.dumps(body,sort_keys=True)))
                if data.enabled:
                    for p in db.execute('SELECT id FROM products').fetchall():
                        reset = (not old['settings']['enabled'] or (data.auto_history and not old['settings']['auto_history']) or (data.zero_days_confirmed and not old['settings']['zero_days_confirmed']))
                        sql = 'INSERT INTO easy_tracking VALUES(?,?) ON CONFLICT(product_id) DO UPDATE SET started_on=excluded.started_on' if reset else 'INSERT OR IGNORE INTO easy_tracking VALUES(?,?)'
                        db.execute(sql,(p['id'],shop_today().isoformat()))
            return run()

    @router.post('/autopilot/run')
    def run_now():return run()

    @router.post('/stock-update')
    def update_stock(data:StockEntry):
        payload='stock:'+data.model_dump_json(exclude={'request_id'})
        with locks[planning_source()]:
            with database() as db:
                db.execute('BEGIN IMMEDIATE')
                saved=replay(db,data.request_id,payload)
                if not saved:
                    p=db.execute('SELECT * FROM products WHERE id=?',(data.product_id,)).fetchone()
                    if not p:raise HTTPException(404,'Product not found.')
                    if p['stock']!=data.expected_stock:raise HTTPException(409,'Stock changed in another tab. Refresh the count before saving.')
                    if data.mode=='sold' and data.quantity==0:raise HTTPException(422,'Enter at least one sold unit.')
                    after=p['stock']-data.quantity if data.mode=='sold' else data.quantity
                    if after<0:raise HTTPException(409,'Sold quantity is greater than current stock.')
                    sold=max(0,p['stock']-after)
                    db.execute('UPDATE products SET stock=? WHERE id=?',(after,data.product_id))
                    stamp=datetime.now(timezone.utc).isoformat();day=shop_today().isoformat()
                    if sold:db.execute('INSERT INTO sales(product_id,quantity,sale_date,recorded_at,stock_after,request_id) VALUES(?,?,?,?,?,?)',
                        (data.product_id,sold,day,stamp,after,str(data.request_id)))
                    if after==0 or p['stock']==0:db.execute('INSERT OR IGNORE INTO easy_stockout_days VALUES(?,?)',(data.product_id,day))
                    saved={'product_id':data.product_id,'stock_after':after,'sold_units':sold,'replayed':False,
                        'message':'Stock saved. Decreases are recorded as sales; increases are count corrections.'}
                    receipt(db,data.request_id,payload,saved)
            # Stock is already durably saved even if planning needs a retry.
            try:auto=run()
            except Exception as error:
                if not isinstance(error,(HTTPException,ValueError,sqlite3.Error)):raise
                auto={'order':None,'message':'Stock is saved. Automatic planning needs a refresh; do not enter the sale twice.','needs_retry':True}
            return {**saved,'autopilot':auto}

    @router.post('/autopilot/pay-ready')
    def pay_ready(data:PayReady):
        with locks[planning_source()]:
            with database() as db:
                current=policy(db)
                if data.expected_policy_revision!=current['revision']:raise HTTPException(409,'Spending settings changed. Refresh the order total first.')
                auto=db.execute('SELECT 1 FROM easy_auto_orders WHERE order_id=?',(data.order_id,)).fetchone()
                if not auto:raise HTTPException(409,'Review this manually created order in Orders.')
            return approve_draft(data,current['settings'])

    return router
