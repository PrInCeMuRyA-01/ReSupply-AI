"""Persistent synthetic shop setup and truthful progress; no payment shortcuts."""
from datetime import date, datetime, timedelta, timezone
import json
from hashlib import sha256
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from demand_forecast import history_snapshot, response_view
from sales_history import save_total
from shop_workspace import is_demo_shop

SEED_VERSION = 'synthetic-shop-v1'
PRODUCTS = [
    ('PEN-BLUE', 'Blue Pen', 12, 60, 2, (4, 5, 5, 5, 6, 18, 20)),
    ('NOTEBOOK-A5', 'A5 Notebook', 10, 180, 3, (2, 3, 3, 4, 4, 12, 13)),
    ('RICE-1KG', 'Rice 1 kg', 24, 325, 4, (4, 4, 4, 4, 4, 4, 4)),
]


def initialize_demo(connection):
    connection.execute('CREATE TABLE IF NOT EXISTS demo_shop_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    connection.execute("INSERT OR IGNORE INTO demo_shop_settings VALUES('namespace',?)", (uuid4().hex,))


def setting(connection, key):
    row = connection.execute('SELECT value FROM demo_shop_settings WHERE key=?', (key,)).fetchone()
    return row['value'] if row else None


def demo_daily_units(sample,day,varied=False):
    units=sample[5][day.weekday()]
    if varied and sample[0]!='RICE-1KG':
        # Reproducible daily variation, independent of model training or test results.
        units+=int.from_bytes(sha256((sample[0]+'|'+day.isoformat()).encode()).digest()[:4],'big')%3-1
    return max(0,units)


def prepare_samples(connection, today, history_days=60, varied=False):
    """One atomic seed; subsequent prepares add only new completed dates."""
    if not isinstance(history_days,int) or isinstance(history_days,bool) or not 56 <= history_days <= 365:
        raise ValueError('Demo history must contain 56-365 days.')
    seed = setting(connection, 'seed')
    stamp = datetime.now(timezone.utc).isoformat()
    if seed:
        data = json.loads(seed)
        if data['version'] != SEED_VERSION:
            raise HTTPException(409, 'This demo shop uses another seed version. Keep its payment records and use the matching source version.')
    else:
        # Demo initialization never copies the real shop or its payment records.
        if connection.execute('SELECT COUNT(*) FROM products').fetchone()[0]:
            raise HTTPException(409, 'This demo database already has manually added products. Keep it intact; sample setup requires an empty, unprepared demo shop.')
        suppliers = []
        for name in ('Metro Wholesale', 'Swift Supplies'):
            suppliers.append(connection.execute('INSERT INTO suppliers(name,name_key,contact) VALUES(?,?,?)',
                (name, name.casefold(), 'Synthetic demo supplier; no supplier payout')).lastrowid)
        ids = []
        for sku, name, stock, cents, lead, _ in PRODUCTS:
            product_id = connection.execute('INSERT INTO products(sku,name,stock,unit_cost_cents) VALUES(?,?,?,?)',
                (sku, name, stock, cents)).lastrowid
            ids.append(product_id)
            selected = connection.execute('INSERT INTO supplier_quotes(product_id,supplier_id,unit_cost_cents,lead_time_days,updated_at) VALUES(?,?,?,?,?)',
                (product_id, suppliers[0], cents, lead, stamp)).lastrowid
            connection.execute('INSERT INTO supplier_quotes(product_id,supplier_id,unit_cost_cents,lead_time_days,updated_at) VALUES(?,?,?,?,?)',
                (product_id, suppliers[1], cents + 20, max(1, lead - 1), stamp))
            connection.execute('INSERT INTO product_sourcing VALUES(?,?)', (product_id, selected))
        data = {'version': SEED_VERSION, 'product_ids': ids, 'prepared_at': stamp,
                'sales_profile':'weekday-with-variation-v1' if varied else 'weekly-v1',
                'history_start': (today - timedelta(days=history_days)).isoformat(),
                'history_end': (today - timedelta(days=1)).isoformat()}
        connection.execute("INSERT INTO demo_shop_settings VALUES('seed',?)", (json.dumps(data),))
    # Only extend after the previously prepared day. Never reset stock, orders,
    # reviews, quotes, edited totals, receipt ledgers, payment UUIDs or namespace.
    start = (today - timedelta(days=history_days)) if not seed else date.fromisoformat(data['history_end']) + timedelta(days=1)
    end = today - timedelta(days=1)
    # A long absence needs at most the most recent 60 days for this demo model.
    start = max(start, today - timedelta(days=history_days))
    if seed and history_days > 60:
        start = today - timedelta(days=history_days)
        data['history_start'] = min(data['history_start'], start.isoformat())
    added = 0
    for offset in range(max(0, (end - start).days + 1)):
        day = start + timedelta(days=offset)
        for product_id, sample in zip(data['product_ids'], PRODUCTS):
            if not connection.execute('SELECT 1 FROM daily_sales_history WHERE product_id=? AND sale_date=?',
                                      (product_id, day.isoformat())).fetchone():
                save_total(connection, {'product_id': product_id, 'sale_date': day.isoformat(),
                    'units_sold': demo_daily_units(sample,day,data.get('sales_profile')=='weekday-with-variation-v1'), 'source': 'demo', 'stockout': False})
                added += 1
    if end.isoformat() > data['history_end'] or (seed and history_days > 60):
        data['history_end'] = end.isoformat()
        connection.execute("UPDATE demo_shop_settings SET value=? WHERE key='seed'", (json.dumps(data),))
    return added


def demo_router(database, shop_today, order_details):
    router = APIRouter(tags=['Demo shop'])

    def require_demo():
        if not is_demo_shop():
            raise HTTPException(409, 'Open /demo/ to prepare the isolated synthetic shop. Existing shop data is not seeded.')

    @router.get('/api/demo-shop')
    def status():
        if not is_demo_shop():
            return {'workspace': 'real', 'demo_url': '/demo/', 'message': 'Demo shop opens separately. Your existing shop stays at /.'}
        with database() as connection:
            connection.execute('BEGIN')
            today = shop_today()
            seed = setting(connection, 'seed')
            data = json.loads(seed) if seed else None
            products = []
            for product in connection.execute('SELECT id,sku,name,stock FROM products ORDER BY id').fetchall():
                snapshot = history_snapshot(connection, product['id'], 'demo', today)
                saved = connection.execute("SELECT * FROM demand_forecast_runs WHERE product_id=? AND source='demo' ORDER BY id DESC LIMIT 1", (product['id'],)).fetchone()
                view = response_view(connection, snapshot, saved)
                products.append({**dict(product), 'ready': view['ready'], 'reason': view['reason'],
                    'run_id': view['run_id'], 'current': view['report_current'],
                    'active_run_id': view['planning']['active_run_id'],
                    'selected_method': view['report']['selected_method'] if view['report_current'] else None,
                    'training_days': view['report']['training_days'] if view['report_current'] else 0,
                    'sample': bool(data and product['id'] in data['product_ids'])})
            focus = connection.execute('SELECT id FROM purchase_orders ORDER BY id DESC LIMIT 1').fetchone()
            order = order_details(connection, focus['id']).model_dump(mode='json') if focus else None
            return {'workspace': 'demo', 'synthetic': True, 'prepared': bool(seed), 'shop_date': today.isoformat(),
                'products': products, 'seed': data, 'focus_order': order, 'suggested_budget': '100.00',
                'counts': {table: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                    for table in ('products', 'suppliers', 'supplier_quotes', 'daily_sales_history', 'purchase_orders', 'stock_receipts')},
                'message': 'Synthetic shop and stock only. PayPal uses genuine Sandbox API calls with your configured test merchant. No automatic approval, authorization, capture or receipt.'}

    @router.post('/api/demo-shop/setup')
    def setup():
        require_demo()
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            added = prepare_samples(connection, shop_today())
        return {'workspace': 'demo', 'added_history_rows': added,
                'message': 'Demo samples ready. Existing demo progress is preserved; review forecasts before planning.'}

    return router
