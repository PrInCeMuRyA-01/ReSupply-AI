"""Atomic quick setup and batch day closing; no payment actions or invented history."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import re
import sqlite3
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from demand_forecast import history_snapshot, response_view
from sales_history import validate_day, validate_total, daily_row, same_total, save_total, logged_units
from shop_workspace import planning_source


def initialize_easy(connection):
    connection.execute('CREATE TABLE IF NOT EXISTS easy_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    connection.execute("INSERT OR IGNORE INTO easy_settings VALUES('namespace',?)", (uuid4().hex[:12],))
    connection.execute('''CREATE TABLE IF NOT EXISTS easy_product_preferences (
        product_id INTEGER PRIMARY KEY REFERENCES products(id), daily_units INTEGER,
        CHECK(daily_units IS NULL OR daily_units BETWEEN 0 AND 1000000))''')
    connection.execute('''CREATE TABLE IF NOT EXISTS easy_requests (
        request_id TEXT PRIMARY KEY,payload TEXT NOT NULL,response TEXT NOT NULL,created_at TEXT NOT NULL)''')


class QuickProduct(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    request_id: UUID
    name: str = Field(min_length=1,max_length=120)
    stock: int = Field(ge=0,le=1000000,strict=True)
    unit_cost: Decimal = Field(gt=0,max_digits=12,decimal_places=2)
    supplier_name: str = Field(min_length=1,max_length=120)
    lead_time_days: int = Field(default=3,ge=1,le=30,strict=True)
    daily_units: int | None = Field(default=None,ge=0,le=1000000,strict=True)
    sku: str | None = Field(default=None,max_length=60,pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]*$')

    @field_validator('supplier_name',mode='before')
    @classmethod
    def clean_supplier(cls,value):
        return ' '.join(value.split()) if isinstance(value,str) else value


class CloseLine(BaseModel):
    model_config = ConfigDict(extra='forbid')
    product_id: int = Field(gt=0,le=9223372036854775807,strict=True)
    units_sold: int = Field(ge=0,le=1000000,strict=True)
    stockout: bool = Field(default=False,strict=True)
    expected_revision: int = Field(ge=0,strict=True)


class CloseDay(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    sale_date: str
    confirmed_complete: bool = Field(strict=True)
    items: list[CloseLine] = Field(min_length=1,max_length=1000)


def replay(connection,request_id,payload):
    row=connection.execute('SELECT * FROM easy_requests WHERE request_id=?',(str(request_id),)).fetchone()
    if row:
        if row['payload']!=payload:
            raise HTTPException(409,'This saved request has different values. Refresh before creating another request.')
        return {**json.loads(row['response']),'replayed':True}


def receipt(connection,request_id,payload,result):
    connection.execute('INSERT INTO easy_requests VALUES(?,?,?,?)',
        (str(request_id),payload,json.dumps(result,sort_keys=True),datetime.now(timezone.utc).isoformat()))


def easy_router(database,shop_today):
    router=APIRouter(prefix='/api/easy',tags=['Simple shop workflow'])

    @router.post('/products',status_code=201)
    def quick_product(data:QuickProduct):
        payload='product:'+data.model_dump_json(exclude={'request_id'})
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=replay(db,data.request_id,payload)
            if previous:return previous
            sku=data.sku.upper() if data.sku else 'ITEM-'+uuid4().hex[:12].upper()
            try:
                product_id=db.execute('INSERT INTO products(sku,name,stock,unit_cost_cents,currency) VALUES(?,?,?,?,?)',
                    (sku,data.name,data.stock,int(data.unit_cost*100),'USD')).lastrowid
            except sqlite3.IntegrityError:
                raise HTTPException(409,'This product code already exists. Use another code.') from None
            supplier=db.execute('SELECT id FROM suppliers WHERE name_key=?',(data.supplier_name.casefold(),)).fetchone()
            supplier_id=supplier['id'] if supplier else db.execute('INSERT INTO suppliers(name,name_key,contact) VALUES(?,?,?)',
                (data.supplier_name,data.supplier_name.casefold(),'')).lastrowid
            quote_id=db.execute('INSERT INTO supplier_quotes(product_id,supplier_id,unit_cost_cents,lead_time_days,updated_at) VALUES(?,?,?,?,?)',
                (product_id,supplier_id,int(data.unit_cost*100),data.lead_time_days,datetime.now(timezone.utc).isoformat())).lastrowid
            db.execute('INSERT INTO product_sourcing(product_id,quote_id) VALUES(?,?)',(product_id,quote_id))
            db.execute('INSERT INTO easy_product_preferences VALUES(?,?)',(product_id,data.daily_units))
            result={'product_id':product_id,'sku':sku,'name':data.name,'supplier_id':supplier_id,'quote_id':quote_id,
                'replayed':False,'message':'Product and selected supplier saved. Your daily estimate is separate from sales history.'}
            receipt(db,data.request_id,payload,result)
            return result

    @router.get('/status')
    def status():
        today=shop_today()
        source=planning_source()
        with database() as db:
            db.execute('BEGIN')
            products=[]
            for product in db.execute('SELECT p.*,e.daily_units,s.name AS supplier_name FROM products p '
                    'LEFT JOIN easy_product_preferences e ON e.product_id=p.id '
                    'LEFT JOIN product_sourcing ps ON ps.product_id=p.id '
                    'LEFT JOIN supplier_quotes q ON q.id=ps.quote_id '
                    'LEFT JOIN suppliers s ON s.id=q.supplier_id ORDER BY p.id').fetchall():
                snapshot=history_snapshot(db,product['id'],source,today)
                saved=db.execute('SELECT * FROM demand_forecast_runs WHERE product_id=? AND source=? ORDER BY id DESC LIMIT 1',
                    (product['id'],source)).fetchone()
                view=response_view(db,snapshot,saved)
                products.append({'id':product['id'],'name':product['name'],'sku':product['sku'],'stock':product['stock'],
                    'supplier_name':product['supplier_name'],'daily_units':product['daily_units'],
                    'ready':snapshot['ready'],'reason':snapshot['reason'],'consecutive_days':snapshot['coverage']['consecutive_days'],
                    'current':view['report_current'],'active_run_id':view['planning']['active_run_id'],
                    'selected_method':view['report']['selected_method'] if view['report_current'] else None,
                    'training_days':view['report']['training_days'] if view['report_current'] else 0,
                    'model_mae':view['report']['evaluation']['model_mae'] if view['report_current'] else None,
                    'baseline_mae':view['report']['evaluation']['baseline_mae'] if view['report_current'] else None})
            yesterday=(today-timedelta(days=1)).isoformat()
            pending=db.execute('SELECT COUNT(DISTINCT s.product_id) FROM sales s LEFT JOIN daily_sales_history h '
                'ON h.product_id=s.product_id AND h.sale_date=s.sale_date WHERE s.sale_date=? AND h.product_id IS NULL',(yesterday,)).fetchone()[0]
            return {'shop_date':today.isoformat(),'source':source,'products':products,'yesterday':yesterday,'unconfirmed_yesterday':pending}

    @router.get('/close-day')
    def close_preview(sale_date:str=Query()):
        day=validate_day(sale_date,shop_today())
        with database() as db:
            db.execute('BEGIN')
            rows=[]
            for product in db.execute('SELECT id,sku,name FROM products ORDER BY id').fetchall():
                old=daily_row(db,product['id'],day)
                count=logged_units(db,product['id'],day)
                rows.append({**dict(product),'logged_units':count,'units_sold':old['units_sold'] if old else count if count else None,
                    'stockout':bool(old['stockout']) if old else False,'expected_revision':old['revision'] if old else 0,
                    'saved_source':old['source'] if old else None})
            return {'sale_date':day,'source':planning_source(),'items':rows}

    @router.post('/close-day')
    def close_day(data:CloseDay):
        if not data.confirmed_complete:
            raise HTTPException(422,'Confirm these are complete daily totals, including any zero-sales rows.')
        ids=[item.product_id for item in data.items]
        if len(set(ids))!=len(ids):raise HTTPException(422,'A product appears more than once.')
        payload='close:'+data.model_dump_json(exclude={'request_id'})
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=replay(db,data.request_id,payload)
            if previous:return previous
            validate_day(data.sale_date,shop_today())
            changed=0
            for item in data.items:
                if not db.execute('SELECT 1 FROM products WHERE id=?',(item.product_id,)).fetchone():
                    raise HTTPException(404,'Product not found. Refresh this day.')
                row={**item.model_dump(),'sale_date':data.sale_date,'source':planning_source()}
                old=daily_row(db,item.product_id,data.sale_date)
                if (old['revision'] if old else 0)!=item.expected_revision:
                    raise HTTPException(409,'A daily total changed. Reload this day before confirming.')
                if old and old['source']!=row['source']:
                    raise HTTPException(409,'This day contains another data source. Review it on Sales history.')
                validate_total(db,row)
                if not same_total(old,row):save_total(db,row);changed+=1
            result={'sale_date':data.sale_date,'saved':len(data.items),'changed':changed,'replayed':False,
                'message':'Full-day totals saved together. Stock has not changed.'}
            receipt(db,data.request_id,payload,result)
            return result

    return router
