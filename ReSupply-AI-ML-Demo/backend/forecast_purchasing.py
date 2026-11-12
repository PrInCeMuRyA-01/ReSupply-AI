"""Owner-reviewed demand and explicitly dated incoming goods for purchasing."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from math import ceil
import hashlib
import json
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Path as ApiPath
from pydantic import BaseModel, ConfigDict, Field

from demand_forecast import ALGORITHM_VERSION, history_snapshot
from shop_workspace import is_demo_shop, planning_source, order_number


def initialize_purchasing(connection, today):
    connection.execute("""CREATE TABLE IF NOT EXISTS forecast_planning_reviews (
        product_id INTEGER PRIMARY KEY REFERENCES products(id),
        run_id INTEGER REFERENCES demand_forecast_runs(id),
        revision INTEGER NOT NULL CHECK(revision>0), updated_at TEXT NOT NULL
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS expected_deliveries (
        order_id INTEGER PRIMARY KEY REFERENCES purchase_orders(id),
        arrival_date TEXT, revision INTEGER NOT NULL CHECK(revision>0), updated_at TEXT NOT NULL
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS purchasing_requests (
        request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, response TEXT NOT NULL, created_at TEXT NOT NULL
    )""")
    columns = {r['name'] for r in connection.execute('PRAGMA table_info(purchase_order_lines)')}
    if 'planning_basis' not in columns:
        connection.execute("ALTER TABLE purchase_order_lines ADD COLUMN planning_basis TEXT NOT NULL DEFAULT ''")
        # Existing unapproved drafts used the average method. Freeze that basis
        # at upgrade, so a later owner review cannot silently change assumptions.
        for line in connection.execute("SELECT l.id,l.product_id FROM purchase_order_lines l JOIN purchase_orders o ON o.id=l.order_id WHERE o.status='draft'").fetchall():
            basis = {**planning_context(connection,line['product_id'],today),'demand_source':'sales_average','incoming_units':0}
            connection.execute('UPDATE purchase_order_lines SET planning_basis=? WHERE id=?',(json.dumps(basis,sort_keys=True),line['id']))


def report_is_current(connection, saved, today):
    if not saved or saved['source'] != planning_source():
        return False
    r = json.loads(saved['report'])
    snapshot = history_snapshot(connection, saved['product_id'], saved['source'], today)
    return bool(saved['shop_date'] == today.isoformat() and snapshot['fingerprint'] == saved['data_fingerprint']
                and r.get('algorithm_version') == ALGORITHM_VERSION and r.get('planning_items'))


def reviewed_run(connection, product_id, today):
    review = connection.execute('SELECT * FROM forecast_planning_reviews WHERE product_id=?', (product_id,)).fetchone()
    saved = connection.execute('SELECT * FROM demand_forecast_runs WHERE id=?', (review['run_id'],)).fetchone() if review and review['run_id'] else None
    return review, saved if report_is_current(connection, saved, today) else None


def review_status(connection, product_id, source, report_saved, today):
    review, active = reviewed_run(connection, product_id, today)
    usable = source == planning_source() and report_is_current(connection, report_saved, today)
    source_label = 'demo / synthetic' if is_demo_shop() else 'actual'
    return {'review_revision': review['revision'] if review else 0,
            'reviewed_run_id': review['run_id'] if review else None,
            'active_run_id': active['id'] if active else None, 'can_use': bool(usable),
            'workspace': 'demo' if is_demo_shop() else 'real',
            'message': f"Purchasing uses reviewed {source_label} forecast #{active['id']}." if active else
                'Reviewed forecast is outdated; purchasing uses the sales-average fallback. Retrain and review again.' if review and review['run_id'] else
                f'Purchasing uses the sales-average method until you review a {source_label} forecast.'}


def incoming_rows(connection, product_id):
    # Payment alone does not imply delivery. An owner-entered date is required.
    return [dict(r) for r in connection.execute("""SELECT o.id AS order_id,o.version,l.quantity,d.arrival_date,
        d.revision,c.capture_id FROM purchase_orders o JOIN purchase_order_lines l ON l.order_id=o.id
        JOIN paypal_checkouts c ON c.order_id=o.id LEFT JOIN expected_deliveries d ON d.order_id=o.id
        LEFT JOIN stock_receipts received ON received.order_id=o.id
        WHERE l.product_id=? AND o.status='approved' AND c.state='captured' AND received.order_id IS NULL
        ORDER BY o.id""", (product_id,))]


def planning_context(connection, product_id, today):
    review, saved = reviewed_run(connection, product_id, today)
    return {'review_revision': review['revision'] if review else 0, 'forecast_run_id': saved['id'] if saved else None,
            'incoming_fingerprint': hashlib.sha256(json.dumps(incoming_rows(connection, product_id),sort_keys=True).encode()).hexdigest()}


def supply_projection(demands, stock, incoming, today, lead_days):
    """Demand occurs before end-of-day incoming delivery; round the peak gap once."""
    scheduled = {}
    excluded_units = 0
    last_day = max(day for day, _ in demands)
    counted = []
    for entry in incoming:
        eta = date.fromisoformat(entry['arrival_date']) if entry['arrival_date'] else None
        if eta is None or eta < today or eta > last_day:
            excluded_units += entry['quantity']
            continue
        scheduled[eta] = scheduled.get(eta,0) + entry['quantity']
        counted.append({'order_id':entry['order_id'],'arrival_date':entry['arrival_date'],'units':entry['quantity']})
    balance = Fraction(stock)
    peak_gap = Fraction(0)
    demand_total = Fraction(0)
    risk = False
    first_shortfall = None
    daily = []
    # Baseline demand starts tomorrow, but today's explicitly dated goods can arrive.
    demand_dates = {day for day,_ in demands}
    if today not in demand_dates:
        balance += scheduled.get(today,0)
    for day, units in demands:
        units = Fraction(str(units))
        demand_total += units
        balance -= units
        before_arrival = balance
        peak_gap = max(peak_gap, -balance)
        if balance < 0 and first_shortfall is None:
            first_shortfall = day.isoformat()
        if day <= today + timedelta(days=lead_days) and balance < 0:
            risk = True
        arriving = scheduled.get(day,0)
        balance += arriving
        daily.append({'date':day.isoformat(),'demand_units':format(float(units),'.6f'), 'incoming_units':arriving,
                      'balance_before_arrival':format(float(before_arrival),'.6f'),'balance_after_arrival':format(float(balance),'.6f')})
    return {'suggested_quantity':ceil(max(Fraction(0),peak_gap)),
            'target_stock':ceil(demand_total),
            'demand_units':format(float(demand_total),'.6f'),'incoming_units':sum(i['units'] for i in counted),
            'excluded_incoming_units':excluded_units,'incoming':counted,'delivery_risk':risk,
            'first_shortfall_date':first_shortfall,'window_end':last_day.isoformat(),'daily':daily}


def forecast_demands(report, today, target_days, today_units):
    rows = {r['date']:Fraction(r['selected_units']) for r in report['planning_items']}
    result = []
    for offset in range(target_days + 1):
        day = today + timedelta(days=offset)
        if day.isoformat() not in rows:
            raise HTTPException(409,'Forecast does not cover these planning dates. Retrain and review again.')
        total = rows[day.isoformat()]
        result.append((day,max(Fraction(0), total - today_units) if offset == 0 else total))
    return result


def product_projection(connection, product_id, today, stock, today_units, lead, coverage, buffer):
    review, saved = reviewed_run(connection,product_id,today)
    if not saved:
        return None, 'Reviewed forecast is outdated; using sales-average fallback.' if review and review['run_id'] else ''
    r = json.loads(saved['report'])
    demands = forecast_demands(r,today,lead+coverage+buffer,today_units)
    result = supply_projection(demands,stock,incoming_rows(connection,product_id),today,lead)
    result.update({'run_id':saved['id'],'selected_method':r['selected_method'], 'training_days':r['training_days'],
                   'data_start':r['data_start'],'data_end':r['data_end'],'training_units':r['training_units'],
                   'average_forecast':r['selected_total_units']/7})
    return result,''


class PlanningReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    product_id: int = Field(gt=0, le=9_223_372_036_854_775_807, strict=True)
    action: Literal['use','average']
    expected_run_id: int | None = Field(default=None,gt=0,le=9_223_372_036_854_775_807,strict=True)
    expected_revision: int = Field(ge=0, strict=True)


class DeliverySave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_order_version: int = Field(ge=1, strict=True)
    expected_revision: int = Field(ge=0, strict=True)
    arrival_date: str | None = Field(default=None,max_length=10)


def request_receipt(connection, request_id, payload):
    row = connection.execute('SELECT * FROM purchasing_requests WHERE request_id=?',(str(request_id),)).fetchone()
    if row:
        if row['payload'] != payload:
            raise HTTPException(409,'This request ID belongs to different planning or delivery values.')
        return {**json.loads(row['response']),'replayed':True}


def save_receipt(connection, request_id, payload, result):
    connection.execute('INSERT INTO purchasing_requests(request_id,payload,response,created_at) VALUES(?,?,?,?)',
        (str(request_id),payload,json.dumps(result,sort_keys=True),datetime.now(timezone.utc).isoformat()))


def purchasing_router(database, shop_today):
    router = APIRouter(tags=['Forecast purchasing'])

    @router.get('/api/forecast-planning/requests/{request_id}')
    def receipt(request_id:UUID):
        with database() as db:
            row = db.execute('SELECT response FROM purchasing_requests WHERE request_id=?',(str(request_id),)).fetchone()
            if not row:raise HTTPException(404,'This planning or delivery request has not been confirmed yet.')
            return {**json.loads(row['response']),'replayed':True}

    @router.post('/api/forecast-planning/review')
    def review(data:PlanningReview):
        payload = 'review:' + json.dumps(data.model_dump(exclude={'request_id'}),sort_keys=True)
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            replay = request_receipt(db,data.request_id,payload)
            if replay:return replay
            today = shop_today()
            history_snapshot(db,data.product_id,planning_source(),today)  # checks product
            old = db.execute('SELECT * FROM forecast_planning_reviews WHERE product_id=?',(data.product_id,)).fetchone()
            if (old['revision'] if old else 0) != data.expected_revision:
                raise HTTPException(409,'Planning review changed. Refresh forecast status before reviewing again.')
            saved = db.execute('SELECT * FROM demand_forecast_runs WHERE id=?',(data.expected_run_id,)).fetchone() if data.expected_run_id else None
            if data.action == 'use' and (not saved or saved['product_id'] != data.product_id or not report_is_current(db,saved,today)):
                raise HTTPException(409,'Only a current '+planning_source()+'-data forecast can be used for purchasing in this shop. Retrain and review its result.')
            if data.action == 'average' and data.expected_run_id is not None:
                raise HTTPException(422,'Average mode must not include a forecast run ID.')
            run_id = saved['id'] if data.action == 'use' else None
            changed = not old or old['run_id'] != run_id
            revision = (old['revision'] if old else 0) + int(changed)
            if changed:
                db.execute('INSERT INTO forecast_planning_reviews VALUES(?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET run_id=excluded.run_id,revision=excluded.revision,updated_at=excluded.updated_at',
                    (data.product_id,run_id,revision,datetime.now(timezone.utc).isoformat()))
            result = {'product_id':data.product_id,'run_id':run_id,'revision':revision,'replayed':False,
                      'message':('Demo / synthetic forecast reviewed for this isolated shop.' if is_demo_shop() else 'Actual forecast reviewed for purchasing.') if run_id else 'Sales-average purchasing selected.'}
            save_receipt(db,data.request_id,payload,result)
            return result

    @router.get('/api/forecast-planning/preview')
    def preview(product_id:int=Query(gt=0,le=9_223_372_036_854_775_807),run_id:int=Query(gt=0,le=9_223_372_036_854_775_807),
                lead_time_days:int=Query(default=3,ge=1,le=30),coverage_days:int=Query(default=7,ge=1,le=30),buffer_days:int=Query(default=2,ge=0,le=14),
                example_stock:int=Query(default=20,ge=0,le=1_000_000),
                budget:Decimal=Query(default=Decimal('200.00'),ge=0,le=Decimal('1000000.00'),decimal_places=2,allow_inf_nan=False)):
        with database() as db:
            db.execute('BEGIN')
            today = shop_today()
            saved = db.execute('SELECT * FROM demand_forecast_runs WHERE id=? AND product_id=?',(run_id,product_id)).fetchone()
            if not saved:raise HTTPException(404,'Forecast not found for this product.')
            snapshot = history_snapshot(db,product_id,saved['source'],today)
            r = json.loads(saved['report'])
            if saved['shop_date'] != today.isoformat() or snapshot['fingerprint'] != saved['data_fingerprint'] or r.get('algorithm_version') != ALGORITHM_VERSION or not r.get('planning_items'):
                raise HTTPException(409,'Forecast is outdated. Train again before previewing purchasing.')
            demo = saved['source'] == 'demo'
            simulation = demo and not is_demo_shop()
            stock = example_stock if simulation else snapshot['product']['stock']
            quote = db.execute('SELECT q.* FROM supplier_quotes q JOIN product_sourcing p ON p.quote_id=q.id WHERE p.product_id=?',(product_id,)).fetchone()
            lead = lead_time_days if simulation or not quote else quote['lead_time_days']
            unit_cents = 100 if simulation else quote['unit_cost_cents'] if quote else db.execute('SELECT unit_cost_cents FROM products WHERE id=?',(product_id,)).fetchone()[0]
            logged = 0 if simulation else db.execute('SELECT COALESCE(SUM(quantity),0) FROM sales WHERE product_id=? AND sale_date=?',(product_id,today.isoformat())).fetchone()[0]
            projection = supply_projection(forecast_demands(r,today,lead+coverage_days+buffer_days,logged),stock,[] if simulation else incoming_rows(db,product_id),today,lead)
            units = min(projection['suggested_quantity'],int(budget*100)//unit_cents) if unit_cents else 0
            return {**projection,'product_id':product_id,'run_id':run_id,'demo':demo,'isolated_demo_shop':is_demo_shop(),'stock':stock,'today_units':logged,
                'lead_time_days':lead,'coverage_days':coverage_days,'buffer_days':buffer_days,
                'unit_cost':str(Decimal(unit_cents)/100),'budget':str(budget),'budget_quantity':units,
                'budget_cost':str(Decimal(units*unit_cents)/100),
                'message':'DEMO simulation: example stock, $1.00/unit and no incoming orders. It cannot create real purchase drafts.' if simulation else
                    'DEMO shop projection: synthetic history with this demo inventory, selected quote and incoming orders. Review before applying only to demo purchasing. Longer horizons are not separately validated.' if is_demo_shop() else
                    'Single-product budget preview; the full planner shares budget across all products. Arrival is end-of-day. Horizons beyond 7 future days are extended projections, not separately validated.'}

    @router.get('/api/incoming-stock')
    def list_incoming():
        today = shop_today()
        with database() as db:
            db.execute('BEGIN')
            rows = db.execute("""SELECT o.id,o.version,o.created_at,d.arrival_date,d.revision,c.captured_at
                FROM purchase_orders o JOIN paypal_checkouts c ON c.order_id=o.id
                LEFT JOIN expected_deliveries d ON d.order_id=o.id LEFT JOIN stock_receipts received ON received.order_id=o.id
                WHERE o.status='approved' AND c.state='captured' AND received.order_id IS NULL ORDER BY o.id DESC""").fetchall()
            items = []
            for row in rows:
                lines = [dict(r) for r in db.execute('SELECT product_id,sku,name,quantity FROM purchase_order_lines WHERE order_id=? ORDER BY id',(row['id'],))]
                state = 'no_date' if not row['arrival_date'] else 'overdue' if row['arrival_date'] < today.isoformat() else 'expected'
                items.append({'order_id':row['id'],'number':order_number(db,row['id']),'order_version':row['version'],
                              'arrival_date':row['arrival_date'],'revision':row['revision'] or 0,'status':state,'items':lines})
            return {'shop_date':today.isoformat(),'items':items,'message':'Only fully captured orders awaiting receipt appear. Set your supplier expected date; overdue or undated goods are excluded from planning. Receive Stock remains a separate action.'}

    @router.put('/api/incoming-stock/{order_id}')
    def delivery(data:DeliverySave,order_id:int=ApiPath(gt=0,le=9_223_372_036_854_775_807)):
        payload = 'delivery:' + json.dumps({'order_id':order_id,**data.model_dump(exclude={'request_id'})},sort_keys=True)
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            replay = request_receipt(db,data.request_id,payload)
            if replay:return replay
            today = shop_today()
            row = db.execute("""SELECT o.version,o.status,c.state,r.order_id AS received FROM purchase_orders o
                LEFT JOIN paypal_checkouts c ON c.order_id=o.id LEFT JOIN stock_receipts r ON r.order_id=o.id WHERE o.id=?""",(order_id,)).fetchone()
            if not row:raise HTTPException(404,'Order not found.')
            if row['status'] != 'approved' or row['state'] != 'captured' or row['received'] is not None or row['version'] != data.expected_order_version:
                raise HTTPException(409,'Set a delivery date only for a fully captured order that is still awaiting stock. Refresh incoming orders.')
            value = data.arrival_date
            if value is not None:
                try:
                    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError()
                    parsed = date.fromisoformat(value)
                    if not today <= parsed <= today+timedelta(days=90):raise ValueError()
                except ValueError:raise HTTPException(422,'Expected arrival must be an ISO date from today through the next 90 days.') from None
            old = db.execute('SELECT * FROM expected_deliveries WHERE order_id=?',(order_id,)).fetchone()
            if (old['revision'] if old else 0) != data.expected_revision:
                raise HTTPException(409,'Expected delivery changed. Refresh incoming orders before saving.')
            changed = not old or old['arrival_date'] != value
            revision = (old['revision'] if old else 0)+int(changed)
            if changed:
                db.execute('INSERT INTO expected_deliveries VALUES(?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET arrival_date=excluded.arrival_date,revision=excluded.revision,updated_at=excluded.updated_at',
                    (order_id,value,revision,datetime.now(timezone.utc).isoformat()))
            result = {'order_id':order_id,'arrival_date':value,'revision':revision,'replayed':False,'message':'Expected delivery saved. Inventory changes only when you Receive Stock.'}
            save_receipt(db,data.request_id,payload,result)
            return result

    return router
