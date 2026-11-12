"""ReSupply AI — Easy Start: stock updates, automatic drafts, owner-confirmed payments."""

from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
import json
import re
from math import ceil
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Path as ApiPath, Query, Response, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from pydantic import BaseModel, ConfigDict, Field, field_validator

from paypal_gateway import PayPalFailure, SandboxPayPal, public_config
from payment_checks import inspect_order
from sales_history import initialize_history, history_router, planning_revision, completed_planning_days
from demand_forecast import initialize_forecast, forecast_router
from forecast_purchasing import initialize_purchasing, purchasing_router, product_projection, incoming_rows, supply_projection, planning_context
from voice_assistant import assistant_router
from shop_workspace import is_demo_shop, demo_scope, planning_source, order_number, ShopWorkspaceMiddleware
from demo_shop import initialize_demo, demo_router
from easy_shop import initialize_easy, easy_router
from easy_llm import llm_router
from easy_autopilot import initialize_autopilot, autopilot_router


# Database isi main.py file ke paas banegi.
DB_PATH = Path(__file__).resolve().with_name("resupply-easy.db")
DEMO_DB_PATH = Path(__file__).resolve().with_name("resupply-new-paypal-demo.db")
FRONTEND_PATH = Path(__file__).resolve().with_name("index.html")
SHOP_TIMEZONE = timezone(timedelta(hours=5, minutes=30))


@contextmanager
def database():
    """Har request ka apna database connection; end mein close ho jayega."""
    path = DEMO_DB_PATH if is_demo_shop() else DB_PATH
    if is_demo_shop() and Path(path).resolve() == Path(DB_PATH).resolve():
        raise HTTPException(503, 'Demo database must be separate from the existing shop database.')
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    """Table pehli baar create hogi; existing products saved rahenge."""
    with database() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                stock INTEGER NOT NULL CHECK (stock >= 0),
                unit_cost_cents INTEGER NOT NULL CHECK (unit_cost_cents >= 0),
                currency TEXT NOT NULL DEFAULT 'USD'
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES products(id),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                sale_date TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                stock_after INTEGER NOT NULL CHECK (stock_after >= 0),
                request_id TEXT NOT NULL UNIQUE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                name_key TEXT NOT NULL UNIQUE,
                contact TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS supplier_quotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES products(id),
                supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
                unit_cost_cents INTEGER NOT NULL CHECK (unit_cost_cents > 0),
                lead_time_days INTEGER NOT NULL CHECK (lead_time_days BETWEEN 1 AND 30),
                updated_at TEXT NOT NULL,
                UNIQUE (product_id, supplier_id),
                UNIQUE (product_id, id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS product_sourcing (
                product_id INTEGER PRIMARY KEY REFERENCES products(id),
                quote_id INTEGER NOT NULL,
                FOREIGN KEY (product_id, quote_id) REFERENCES supplier_quotes(product_id, id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                request_payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
                created_at TEXT NOT NULL,
                approved_at TEXT,
                cancelled_at TEXT,
                budget_cents INTEGER NOT NULL CHECK (budget_cents >= 0),
                products_total_cents INTEGER NOT NULL CHECK (products_total_cents > 0),
                shipping_cents INTEGER NOT NULL DEFAULT 0 CHECK (shipping_cents >= 0),
                tax_cents INTEGER NOT NULL DEFAULT 0 CHECK (tax_cents >= 0),
                approval_limit_cents INTEGER NOT NULL CHECK (approval_limit_cents >= 0),
                approval_request_id TEXT UNIQUE,
                approval_payload TEXT,
                source_date TEXT NOT NULL,
                lead_time_days INTEGER NOT NULL,
                coverage_days INTEGER NOT NULL,
                buffer_days INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS purchase_order_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
                product_id INTEGER NOT NULL REFERENCES products(id),
                sku TEXT NOT NULL,
                name TEXT NOT NULL,
                supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
                supplier_name TEXT NOT NULL,
                quote_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                unit_cost_cents INTEGER NOT NULL CHECK (unit_cost_cents > 0),
                lead_time_days INTEGER NOT NULL,
                stock_at_draft INTEGER NOT NULL,
                sale_revision INTEGER NOT NULL,
                quote_updated_at TEXT NOT NULL,
                history_status TEXT NOT NULL,
                UNIQUE (order_id, product_id),
                FOREIGN KEY (product_id, quote_id) REFERENCES supplier_quotes(product_id, id)
            )
            """
        )


        connection.execute(
            """CREATE TABLE IF NOT EXISTS paypal_checkouts (
                order_id INTEGER PRIMARY KEY REFERENCES purchase_orders(id),
                order_version INTEGER NOT NULL,
                account_key TEXT NOT NULL,
                amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                state TEXT NOT NULL,
                create_request_id TEXT NOT NULL UNIQUE,
                authorize_request_id TEXT NOT NULL UNIQUE,
                paypal_order_id TEXT UNIQUE,
                authorization_id TEXT UNIQUE,
                paypal_status TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                authorized_at TEXT,
                authorization_started_at TEXT,
                expires_at TEXT,
                message TEXT NOT NULL DEFAULT '',
                operation_token TEXT,
                operation_started_at TEXT
            )"""
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(paypal_checkouts)")}
        if "authorization_started_at" not in columns:
            connection.execute("ALTER TABLE paypal_checkouts ADD COLUMN authorization_started_at TEXT")
            # Legacy records lack a sent marker. Preserve uncertain/approved attempts conservatively.
            connection.execute("""UPDATE paypal_checkouts SET authorization_started_at=updated_at
                WHERE state IN ('authorizing','authorize_unknown','authorized','review_required')
                   OR authorization_id IS NOT NULL OR paypal_status='APPROVED'""")

        # Additive migration: existing products, orders and active holds are preserved.
        for name in ("capture_id", "capture_status", "captured_at", "capture_request_id", "capture_started_at",
                     "void_request_id", "void_started_at"):
            if name not in columns:
                connection.execute(f"ALTER TABLE paypal_checkouts ADD COLUMN {name} TEXT")
        for name in ("capture_id", "capture_request_id", "void_request_id"):
            connection.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS paypal_unique_{name} ON paypal_checkouts({name})")
        connection.execute("""CREATE TABLE IF NOT EXISTS stock_receipts (
            order_id INTEGER PRIMARY KEY REFERENCES purchase_orders(id),
            request_id TEXT NOT NULL UNIQUE,
            order_version INTEGER NOT NULL,
            received_at TEXT NOT NULL,
            units INTEGER NOT NULL CHECK(units > 0),
            item_count INTEGER NOT NULL CHECK(item_count > 0)
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS stock_receipt_lines (
            order_id INTEGER NOT NULL REFERENCES stock_receipts(order_id),
            product_id INTEGER NOT NULL REFERENCES products(id),
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            stock_before INTEGER NOT NULL CHECK(stock_before >= 0),
            stock_after INTEGER NOT NULL CHECK(stock_after = stock_before + quantity),
            PRIMARY KEY(order_id, product_id),
            FOREIGN KEY(order_id, product_id) REFERENCES purchase_order_lines(order_id, product_id)
        )""")
        initialize_easy(connection)
        initialize_autopilot(connection)
        initialize_history(connection)
        initialize_forecast(connection)
        initialize_purchasing(connection,shop_today())
        if is_demo_shop():
            initialize_demo(connection)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    with demo_scope():
        initialize_database()
    yield


app = FastAPI(
    title="ReSupply AI",
    description="Easy Start: quick setup, daily sales, guided restocking and owner-confirmed Sandbox payments.",
    version="0.20.0",
    lifespan=lifespan,
    docs_url=None, redoc_url=None, openapi_url=None,
)
app.add_middleware(ShopWorkspaceMiddleware)


@app.get('/openapi.json',include_in_schema=False)
def scoped_openapi():
    schema=deepcopy(app.openapi())
    schema['servers']=[{'url':'/demo' if is_demo_shop() else '/'}]
    return schema


@app.get('/docs',include_in_schema=False)
def api_docs():
    return get_swagger_ui_html(openapi_url=('/demo' if is_demo_shop() else '')+'/openapi.json',title='ReSupply AI · API docs')


@app.get('/redoc',include_in_schema=False)
def api_redoc():
    return get_redoc_html(openapi_url=('/demo' if is_demo_shop() else '')+'/openapi.json',title='ReSupply AI · API docs')


class ProductCreate(BaseModel):
    """Product add karne ke liye required data aur validation rules."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    sku: str = Field(
        min_length=1,
        max_length=60,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        description="Unique product code; example NOTEBOOK-A5.",
    )
    name: str = Field(min_length=1, max_length=120)
    stock: int = Field(ge=0, le=1_000_000, strict=True)
    unit_cost: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2,
        description="Purchase cost per unit in USD; maximum 2 decimal places.",
    )
    currency: Literal["USD"] = "USD"

    @field_validator("sku", mode="before")
    @classmethod
    def normalize_sku(cls, value):
        # notebook-a5 aur NOTEBOOK-A5 ko same product code samjho.
        return value.strip().upper() if isinstance(value, str) else value


class Product(ProductCreate):
    id: int


class StockUpdate(BaseModel):
    """Sirf stock ki new absolute quantity accept karo."""

    model_config = ConfigDict(extra="forbid")
    stock: int = Field(ge=0, le=1_000_000, strict=True)


class SaleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0, strict=True)
    quantity: int = Field(gt=0, le=1_000_000, strict=True)
    request_id: UUID = Field(description="Unique request ID; retry the same sale with the same ID.")


class SaleRecord(BaseModel):
    id: int
    product_id: int
    sku: str
    name: str
    quantity: int
    sale_date: date
    recorded_at: datetime
    stock_after: int


class SaleReceipt(BaseModel):
    sale: SaleRecord
    product: Product
    replayed: bool


class SupplierCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    contact: str = Field(default="", max_length=120)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value


class Supplier(SupplierCreate):
    id: int


class QuoteUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_id: int = Field(gt=0, le=9_223_372_036_854_775_807, strict=True)
    unit_cost: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    lead_time_days: int = Field(ge=1, le=30, strict=True)


class QuoteSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: int = Field(gt=0, le=9_223_372_036_854_775_807, strict=True)


class SupplierQuote(BaseModel):
    id: int
    product_id: int
    sku: str
    product_name: str
    supplier_id: int
    supplier_name: str
    contact: str
    unit_cost: Decimal
    lead_time_days: int
    updated_at: datetime
    selected: bool
    currency: Literal["USD"] = "USD"


class RestockItem(BaseModel):
    product_id: int
    sku: str
    name: str
    stock: int
    unit_cost: Decimal
    supplier_id: int | None
    supplier_name: str | None
    quote_id: int | None
    lead_time_days: int
    target_days: int
    price_source: Literal["saved_product", "supplier_quote"]
    history_status: Literal["no_history", "today_only", "limited", "seven_days", "completed_days", "reviewed_forecast", "owner_estimate"]
    window_start: date | None
    window_end: date | None
    days_used: int
    units_sold: int
    today_units: int
    average_daily_sales: float | None
    estimated_days_left: float | None
    target_stock: int | None
    suggested_quantity: int | None
    estimated_cost: Decimal | None
    status: Literal[
        "no_history", "no_recent_sales", "out_of_stock",
        "delivery_risk", "restock", "enough_stock",
    ]
    reason: str
    demand_source: Literal['sales_average','reviewed_ml','reviewed_forecast_average','owner_estimate'] = 'sales_average'
    forecast_run_id: int | None = None
    incoming_units: int = 0
    excluded_incoming_units: int = 0


class RestockPlan(BaseModel):
    shop_date: date
    lead_time_days: int
    coverage_days: int
    buffer_days: int
    target_days: int
    suggested_products: int
    selected_supplier_products: int
    estimated_total_cost: Decimal
    currency: Literal["USD"] = "USD"
    method: Literal["daily_sales_average", "reviewed_forecast_mixed"] = "daily_sales_average"
    items: list[RestockItem]


class PurchasePlanItem(BaseModel):
    product_id: int
    sku: str
    name: str
    stock: int
    unit_cost: Decimal
    supplier_id: int | None
    supplier_name: str | None
    quote_id: int | None
    lead_time_days: int
    price_source: Literal["saved_product", "supplier_quote"]
    restock_status: str
    history_status: Literal["no_history", "today_only", "limited", "seven_days", "completed_days", "reviewed_forecast", "owner_estimate"]
    suggested_quantity: int | None
    planned_quantity: int
    deferred_quantity: int | None
    line_cost: Decimal
    allocation_status: Literal[
        "included", "partial", "budget_short", "price_required", "no_history", "not_needed",
    ]
    reason: str
    demand_source: Literal['sales_average','reviewed_ml','reviewed_forecast_average','owner_estimate'] = 'sales_average'
    forecast_run_id: int | None = None
    incoming_units: int = 0


class PurchasePlan(BaseModel):
    shop_date: date
    budget: Decimal
    planned_cost: Decimal
    remaining_budget: Decimal
    planned_products: int
    planned_units: int
    deferred_products: int
    price_check_products: int
    no_history_products: int
    planned_without_supplier: int
    lead_time_days: int
    coverage_days: int
    buffer_days: int
    currency: Literal["USD"] = "USD"
    method: Literal["priority_first"] = "priority_first"
    items: list[PurchasePlanItem]


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    budget: Decimal = Field(default=Decimal("200.00"), ge=0, le=Decimal("1000000.00"), max_digits=9, decimal_places=2)
    lead_time_days: int = Field(default=3, ge=1, le=30, strict=True)
    coverage_days: int = Field(default=7, ge=1, le=30, strict=True)
    buffer_days: int = Field(default=2, ge=0, le=14, strict=True)


class OrderApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_version: int = Field(ge=1, strict=True)
    shipping_cost: Decimal = Field(default=Decimal("0.00"), ge=0, le=Decimal("1000000.00"), max_digits=9, decimal_places=2)
    tax_cost: Decimal = Field(default=Decimal("0.00"), ge=0, le=Decimal("1000000.00"), max_digits=9, decimal_places=2)
    spending_limit: Decimal = Field(ge=0, le=Decimal("1000000.00"), max_digits=9, decimal_places=2)


class OrderCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, strict=True)


class OrderReceive(OrderCancel):
    request_id: UUID


class OrderLine(BaseModel):
    product_id: int
    sku: str
    name: str
    supplier_id: int
    supplier_name: str
    quote_id: int
    quantity: int
    unit_cost: Decimal
    line_total: Decimal
    lead_time_days: int
    history_status: str
    quote_updated_at: datetime
    demand_source: str = 'sales_average'
    forecast_run_id: int | None = None
    incoming_units: int = 0


class PaymentStatus(BaseModel):
    state: Literal["creating", "create_unknown", "create_failed", "ready", "authorizing",
                   "authorize_unknown", "authorized", "voided", "expired", "review_required", "cancelled_unpaid",
                   "capturing", "capture_unknown", "capture_pending", "capture_denied", "captured", "voiding", "void_unknown"]
    amount: Decimal
    paypal_order_id: str | None
    authorization_id: str | None
    paypal_status: str | None
    authorized_at: datetime | None
    expires_at: datetime | None
    message: str
    capture_id: str | None = None
    capture_status: str | None = None
    captured_at: datetime | None = None
    environment: Literal["sandbox"] = "sandbox"


class CheckoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, strict=True)


class CheckoutAuthorize(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paypal_order_id: str = Field(min_length=1, max_length=36, pattern=r"^[A-Z0-9]+$")


class CheckoutReceipt(BaseModel):
    paypal_order_id: str
    payment: PaymentStatus


class OrderSummary(BaseModel):
    id: int
    number: str
    status: Literal["draft", "approved", "cancelled", "received"]
    version: int
    created_at: datetime
    approved_at: datetime | None
    cancelled_at: datetime | None
    budget: Decimal
    products_total: Decimal
    shipping_cost: Decimal
    tax_cost: Decimal
    grand_total: Decimal
    spending_limit: Decimal
    item_count: int
    units: int
    supplier_count: int
    currency: Literal["USD"] = "USD"
    payment: PaymentStatus | None = None
    can_cancel: bool = True
    can_capture: bool = False
    can_void: bool = False
    can_receive: bool = False
    received_at: datetime | None = None


class StockReceiptLine(BaseModel):
    product_id: int
    sku: str
    name: str
    quantity: int
    stock_before: int
    stock_after: int


class StockReceipt(BaseModel):
    received_at: datetime
    units: int
    item_count: int
    items: list[StockReceiptLine]


class OrderDetails(OrderSummary):
    source_date: date
    lead_time_days: int
    coverage_days: int
    buffer_days: int
    items: list[OrderLine]
    receipt: StockReceipt | None = None


class OrderReceipt(BaseModel):
    order: OrderDetails
    replayed: bool


def product_from_row(row: sqlite3.Row) -> Product:
    # Cost integer cents mein store hoti hai; response mein dollars milenge.
    return Product(
        id=row["id"],
        sku=row["sku"],
        name=row["name"],
        stock=row["stock"],
        unit_cost=(Decimal(row["unit_cost_cents"]) / Decimal(100)).quantize(Decimal("0.01")),
        currency=row["currency"],
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request):
    if not FRONTEND_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail="Copy index.html into the backend folder, next to main.py.",
        )
    html = FRONTEND_PATH.read_text(encoding='utf-8')
    view=request.url.path.rstrip('/').rsplit('/',1)[-1]
    view='history' if view=='sales-history' else view
    if view not in {'inventory','sales','history','forecast','suppliers','purchasing','orders','assistant','demo-guide'}:
        view='overview'
    html=html.replace('data-start-view="overview"','data-start-view="'+view+'"')
    # Initial HTML shows only the requested page, including direct refreshes.
    for screen in ('overview','inventory','sales','history','forecast','suppliers','purchasing','orders','assistant','demo-guide'):
        marker='data-screen="'+screen+'"'
        html=html.replace(marker+' hidden',marker) if screen==view else html.replace(marker+'>',marker+' hidden>')
    if is_demo_shop():
        html = html.replace('data-workspace="real" data-api-prefix=""', 'data-workspace="demo" data-api-prefix="/demo"')
        html = html.replace('src="/assets/', 'src="/demo/assets/')
        html = html.replace('href="/assets/', 'href="/demo/assets/')
        html = html.replace('<title>', '<title>DEMO Shop · ', 1)
        html=re.sub(r'<a\b[^>]*\bdata-view="[^"]+"[^>]*>',
            lambda match:match.group(0).replace('href="/','href="/demo/'),html)
    return HTMLResponse(html, headers={'Cache-Control':'no-store'})


for page in ('inventory','sales','sales-history','forecast','suppliers','purchasing','orders','assistant','demo-guide'):
    app.add_api_route('/'+page,home,response_class=HTMLResponse,include_in_schema=False)


@app.get("/health", tags=["Setup"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/products", response_model=Product, status_code=201, tags=["Inventory"])
def add_product(product: ProductCreate):
    try:
        with database() as connection:
            cursor = connection.execute(
                """
                INSERT INTO products (sku, name, stock, unit_cost_cents, currency)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    product.sku,
                    product.name,
                    product.stock,
                    int(product.unit_cost * 100),
                    product.currency,
                ),
            )
            row = connection.execute(
                "SELECT * FROM products WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="This SKU already exists. Use a different product code.",
        ) from error
    return product_from_row(row)


@app.get("/api/products", response_model=list[Product], tags=["Inventory"])
def list_products():
    with database() as connection:
        rows = connection.execute("SELECT * FROM products ORDER BY id").fetchall()
    return [product_from_row(row) for row in rows]


@app.patch(
    "/api/products/{product_id}/stock",
    response_model=Product,
    tags=["Inventory"],
)
def update_stock(update: StockUpdate, product_id: int = ApiPath(gt=0)):
    """Example: stock 25 se 20 karna; product ki same ID rahegi."""
    with database() as connection:
        result = connection.execute(
            "UPDATE products SET stock = ? WHERE id = ?",
            (update.stock, product_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found.")
        row = connection.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
    return product_from_row(row)


def sale_from_row(connection, sale_id: int) -> SaleRecord:
    row = connection.execute(
        """
        SELECT s.*, p.sku, p.name FROM sales s
        JOIN products p ON p.id = s.product_id WHERE s.id = ?
        """,
        (sale_id,),
    ).fetchone()
    return SaleRecord(**dict(row))


@app.post("/api/sales", response_model=SaleReceipt, status_code=201, tags=["Sales"])
def record_sale(sale: SaleCreate, response: Response):
    with database() as connection:
        # Request check, stock decrement aur sale insert ek atomic transaction hain.
        connection.execute("BEGIN IMMEDIATE")
        previous = connection.execute(
            "SELECT * FROM sales WHERE request_id = ?", (str(sale.request_id),)
        ).fetchone()
        if previous:
            if previous["product_id"] != sale.product_id or previous["quantity"] != sale.quantity:
                raise HTTPException(status_code=409, detail="This request ID belongs to a different sale.")
            row = connection.execute(
                "SELECT * FROM products WHERE id = ?", (sale.product_id,)
            ).fetchone()
            response.status_code = 200
            return SaleReceipt(
                sale=sale_from_row(connection, previous["id"]),
                product=product_from_row(row),
                replayed=True,
            )

        row = connection.execute(
            "SELECT * FROM products WHERE id = ?", (sale.product_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Product not found.")
        result = connection.execute(
            "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
            (sale.quantity, sale.product_id, sale.quantity),
        )
        if result.rowcount == 0:
            raise HTTPException(
                status_code=409,
                detail=f"Not enough stock. Current stock is {row['stock']}.",
            )
        stock_after = row["stock"] - sale.quantity
        now = datetime.now(timezone.utc)
        cursor = connection.execute(
            """
            INSERT INTO sales (product_id, quantity, sale_date, recorded_at, stock_after, request_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sale.product_id,
                sale.quantity,
                shop_today().isoformat(),
                now.isoformat(),
                stock_after,
                str(sale.request_id),
            ),
        )
        updated = connection.execute(
            "SELECT * FROM products WHERE id = ?", (sale.product_id,)
        ).fetchone()
        return SaleReceipt(
            sale=sale_from_row(connection, cursor.lastrowid),
            product=product_from_row(updated),
            replayed=False,
        )


@app.get("/api/sales", response_model=list[SaleRecord], tags=["Sales"])
def list_sales(limit: int = Query(default=100, ge=1, le=500)):
    with database() as connection:
        rows = connection.execute(
            """
            SELECT s.*, p.sku, p.name FROM sales s
            JOIN products p ON p.id = s.product_id ORDER BY s.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [SaleRecord(**dict(row)) for row in rows]


def shop_today() -> date:
    return datetime.now(SHOP_TIMEZONE).date()


def ensure_product(connection, product_id: int):
    if connection.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Product not found.")


def quote_from_row(row: sqlite3.Row) -> SupplierQuote:
    return SupplierQuote(
        id=row["id"], product_id=row["product_id"], sku=row["sku"],
        product_name=row["product_name"], supplier_id=row["supplier_id"],
        supplier_name=row["supplier_name"], contact=row["contact"],
        unit_cost=(Decimal(row["unit_cost_cents"]) / Decimal(100)).quantize(Decimal("0.01")),
        lead_time_days=row["lead_time_days"], updated_at=row["updated_at"],
        selected=bool(row["selected"]),
    )


def quote_rows(connection, product_id: int):
    return connection.execute(
        """
        SELECT q.*, p.sku, p.name AS product_name, s.name AS supplier_name, s.contact,
            CASE WHEN ps.quote_id = q.id THEN 1 ELSE 0 END AS selected
        FROM supplier_quotes q
        JOIN products p ON p.id = q.product_id
        JOIN suppliers s ON s.id = q.supplier_id
        LEFT JOIN product_sourcing ps ON ps.product_id = q.product_id
        WHERE q.product_id = ? ORDER BY q.unit_cost_cents, q.lead_time_days, q.id
        """,
        (product_id,),
    ).fetchall()


@app.post("/api/suppliers", response_model=Supplier, status_code=201, tags=["Suppliers"])
def add_supplier(supplier: SupplierCreate):
    try:
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO suppliers (name, name_key, contact) VALUES (?, ?, ?)",
                (supplier.name, supplier.name.casefold(), supplier.contact),
            )
            supplier_id = cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="This supplier name already exists. Choose it from the list.") from error
    return Supplier(id=supplier_id, **supplier.model_dump())


@app.get("/api/suppliers", response_model=list[Supplier], tags=["Suppliers"])
def list_suppliers():
    with database() as connection:
        rows = connection.execute("SELECT * FROM suppliers ORDER BY name_key, id").fetchall()
    return [Supplier(id=row["id"], name=row["name"], contact=row["contact"]) for row in rows]


@app.get("/api/products/{product_id}/quotes", response_model=list[SupplierQuote], tags=["Suppliers"])
def list_quotes(product_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    with database() as connection:
        ensure_product(connection, product_id)
        rows = quote_rows(connection, product_id)
    return [quote_from_row(row) for row in rows]


@app.put("/api/products/{product_id}/quotes", response_model=SupplierQuote, status_code=201, tags=["Suppliers"])
def save_quote(quote: QuoteUpsert, response: Response, product_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        ensure_product(connection, product_id)
        if connection.execute("SELECT id FROM suppliers WHERE id = ?", (quote.supplier_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Supplier not found.")
        existing = connection.execute(
            "SELECT id FROM supplier_quotes WHERE product_id = ? AND supplier_id = ?",
            (product_id, quote.supplier_id),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO supplier_quotes (product_id, supplier_id, unit_cost_cents, lead_time_days, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(product_id, supplier_id) DO UPDATE SET
                unit_cost_cents=excluded.unit_cost_cents,
                lead_time_days=excluded.lead_time_days,
                updated_at=excluded.updated_at
            """,
            (product_id, quote.supplier_id, int(quote.unit_cost * 100), quote.lead_time_days, datetime.now(timezone.utc).isoformat()),
        )
        saved = next(row for row in quote_rows(connection, product_id) if row["supplier_id"] == quote.supplier_id)
        if existing:
            response.status_code = 200
        return quote_from_row(saved)


@app.put("/api/products/{product_id}/supplier-selection", response_model=SupplierQuote, tags=["Suppliers"])
def select_supplier(selection: QuoteSelection, product_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        ensure_product(connection, product_id)
        row = connection.execute(
            "SELECT id FROM supplier_quotes WHERE id = ? AND product_id = ?",
            (selection.quote_id, product_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Quote not found for this product.")
        connection.execute(
            "INSERT INTO product_sourcing (product_id, quote_id) VALUES (?, ?) ON CONFLICT(product_id) DO UPDATE SET quote_id=excluded.quote_id",
            (product_id, selection.quote_id),
        )
        return quote_from_row(next(row for row in quote_rows(connection, product_id) if row["id"] == selection.quote_id))


@app.delete("/api/products/{product_id}/supplier-selection", tags=["Suppliers"])
def clear_supplier_selection(product_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    with database() as connection:
        ensure_product(connection, product_id)
        connection.execute("DELETE FROM product_sourcing WHERE product_id = ?", (product_id,))
    return {"status": "cleared", "product_id": product_id}


def calculate_restock(connection, lead_time_days: int, coverage_days: int, buffer_days: int):
    """Selected quote ki delivery use karo; otherwise default setting apply hoti hai."""
    today = shop_today()
    earliest = today - timedelta(days=7)
    target_days = lead_time_days + coverage_days + buffer_days
    # The caller owns the connection, so a draft captures one transaction's snapshot.
    rows = connection.execute(
        """
        SELECT p.*, q.id AS selected_quote_id, q.supplier_id AS selected_supplier_id,
            supplier.name AS selected_supplier_name, q.lead_time_days AS selected_lead_time,
            COALESCE(q.unit_cost_cents, p.unit_cost_cents) AS planning_cost_cents,
            MIN(s.sale_date) AS first_sale_date,
            COALESCE(SUM(CASE WHEN s.sale_date >= ? AND s.sale_date < ?
                THEN s.quantity ELSE 0 END), 0) AS completed_units,
            COALESCE(SUM(CASE WHEN s.sale_date = ?
                THEN s.quantity ELSE 0 END), 0) AS today_units
        FROM products p
        LEFT JOIN product_sourcing ps ON ps.product_id = p.id
        LEFT JOIN supplier_quotes q ON q.id = ps.quote_id AND q.product_id = p.id
        LEFT JOIN suppliers supplier ON supplier.id = q.supplier_id
        LEFT JOIN sales s ON s.product_id = p.id AND s.sale_date <= ?
        GROUP BY p.id ORDER BY p.id
        """,
        (earliest.isoformat(), today.isoformat(), today.isoformat(), today.isoformat()),
    ).fetchall()

    items = []
    total_cost_cents = 0
    confirmed_days = completed_planning_days(connection, earliest, today, planning_source())
    for row in rows:
        item_lead_time = row["selected_lead_time"] or lead_time_days
        item_target_days = item_lead_time + coverage_days + buffer_days
        first_sale = date.fromisoformat(row["first_sale_date"]) if row["first_sale_date"] else None
        today_units = row["today_units"]
        if first_sale and first_sale < today:
            start = max(first_sale, earliest)
            end = today - timedelta(days=1)
            days = (today - start).days
            units = row["completed_units"]
            history = "seven_days" if days == 7 else "limited"
        elif first_sale == today:
            # Shop ne aaj start kiya: a clearly labelled partial-day preview.
            start = end = today
            days = 1
            units = today_units
            history = "today_only"
        else:
            start = end = None
            days = units = 0
            history = "no_history"

        flagged_only = False
        if row["id"] in confirmed_days:
            observed = [day for day in confirmed_days[row["id"]] if not day["stockout"]]
            if observed:
                start, end = date.fromisoformat(observed[0]["sale_date"]), date.fromisoformat(observed[-1]["sale_date"])
                days, units, history = len(observed), sum(day["units_sold"] for day in observed), "completed_days"
            else:
                start = end = None
                days = units = 0
                history, flagged_only = "no_history", True

        # Owner input is a planning estimate, never a fabricated daily sales record.
        initial = connection.execute('SELECT daily_units FROM easy_product_preferences WHERE product_id=?',(row['id'],)).fetchone()
        if not flagged_only and history in {'no_history','today_only'} and initial and initial['daily_units'] is not None and (history == 'no_history' or initial['daily_units'] > 0):
            days, units, history = 1, initial['daily_units'], 'owner_estimate'
            start = end = None

        average = None
        days_left = None
        target_stock = None
        quantity = None
        cost = None
        if not days:
            status = "out_of_stock" if row["stock"] == 0 else "no_history"
            reason = "All confirmed actual days in this window have stockout flags. Confirm other full days before estimating demand." if flagged_only else "Record sales to estimate how much to buy."
        elif units == 0:
            average = 0.0
            target_stock = quantity = 0
            cost = Decimal("0.00")
            status = "out_of_stock" if row["stock"] == 0 else "no_recent_sales"
            reason = "No sales recorded in this window; review demand before buying."
        else:
            # Fraction keeps ceiling and risk comparisons exact, even at 1/7 unit/day.
            rate = Fraction(units, days)
            average = round(float(rate), 2)
            days_left = round(float(Fraction(row["stock"], 1) / rate), 1)
            target_stock = ceil(rate * item_target_days)
            quantity = max(0, target_stock - row["stock"])
            cost_cents = quantity * row["planning_cost_cents"]
            cost = (Decimal(cost_cents) / Decimal(100)).quantize(Decimal("0.01"))
            if row["stock"] == 0:
                status = "out_of_stock"
                reason = "No stock left. Review the suggested quantity."
            elif row["stock"] <= rate * item_lead_time:
                status = "delivery_risk"
                reason = "Stock may run out before or when the supplier delivery arrives."
            elif quantity > 0:
                status = "restock"
                reason = "Below your target stock for delivery, coverage and buffer."
            else:
                status = "enough_stock"
                reason = "Current stock meets this estimate's target."

        if history == "owner_estimate":
            reason += " Uses your starting daily-sales estimate; this is not a trained ML forecast or recorded history."
        elif history == "today_only":
            reason += " Today's sales are a partial-day estimate."
        elif history == "limited":
            reason += f" Only {days} completed calendar day(s) in this estimate."
        elif history == "completed_days":
            reason += f" Uses {days} confirmed actual day(s) from the last 7 days. Missing, demo and stockout days are excluded; incomplete coverage can bias this baseline."

        demand_source, run_id, incoming_units, excluded_incoming = ('owner_estimate' if history == 'owner_estimate' else 'sales_average'), None, 0, 0
        projection, fallback_note = product_projection(connection,row['id'],today,row['stock'],today_units,item_lead_time,coverage_days,buffer_days)
        arrivals = incoming_rows(connection,row['id'])
        if projection:
            demand_source = 'reviewed_ml' if projection['selected_method'] == 'random_forest' else 'reviewed_forecast_average'
            run_id, history = projection['run_id'], 'reviewed_forecast'
            days, units = projection['training_days'], projection['training_units']
            start, end = date.fromisoformat(projection['data_start']), date.fromisoformat(projection['data_end'])
            average, days_left = round(projection['average_forecast'],2), None
            reason = f"Reviewed actual {'ML' if demand_source == 'reviewed_ml' else 'forecast average'} #{run_id}. Today's remaining estimate plus {item_target_days} future delivery/coverage/buffer days. Longer than 7-day projections are not separately validated."
        elif arrivals and days and units:
            projection = supply_projection([(today+timedelta(days=i),Fraction(units,days)) for i in range(1,item_target_days+1)],row['stock'],arrivals,today,item_lead_time)
        if projection:
            target_stock, quantity = projection['target_stock'], projection['suggested_quantity']
            incoming_units, excluded_incoming = projection['incoming_units'], projection['excluded_incoming_units']
            cost = money(quantity * row['planning_cost_cents'])
            status = 'out_of_stock' if row['stock'] == 0 else 'delivery_risk' if projection['delivery_risk'] else 'restock' if quantity else 'enough_stock'
            if projection['delivery_risk']:reason += " Stock may run out before new supplier delivery; a normal purchase cannot remove that earlier risk."
            reason += f" Counts {incoming_units} expected incoming units at end-of-day arrival; undated, overdue or beyond-window goods ({excluded_incoming} units) are excluded."
        if fallback_note:reason += ' '+fallback_note
        if cost is not None:total_cost_cents += int(cost*100)

        items.append(RestockItem(
            product_id=row["id"], sku=row["sku"], name=row["name"], stock=row["stock"],
            unit_cost=(Decimal(row["planning_cost_cents"]) / Decimal(100)).quantize(Decimal("0.01")),
            supplier_id=row["selected_supplier_id"], supplier_name=row["selected_supplier_name"],
            quote_id=row["selected_quote_id"], lead_time_days=item_lead_time, target_days=item_target_days,
            price_source="supplier_quote" if row["selected_quote_id"] else "saved_product",
            history_status=history, window_start=start, window_end=end,
            days_used=days, units_sold=units, today_units=today_units,
            average_daily_sales=average, estimated_days_left=days_left,
            target_stock=target_stock, suggested_quantity=quantity,
            estimated_cost=cost, status=status, reason=reason,
            demand_source=demand_source,forecast_run_id=run_id,incoming_units=incoming_units,excluded_incoming_units=excluded_incoming,
        ))

    priority = {"out_of_stock": 0, "delivery_risk": 1, "restock": 2,
                "no_history": 3, "no_recent_sales": 4, "enough_stock": 5}
    items.sort(key=lambda item: (priority[item.status], item.product_id))
    return RestockPlan(
        shop_date=today, lead_time_days=lead_time_days, coverage_days=coverage_days,
        buffer_days=buffer_days, target_days=target_days,
        suggested_products=sum(1 for item in items if (item.suggested_quantity or 0) > 0),
        selected_supplier_products=sum(1 for item in items if item.quote_id is not None),
        estimated_total_cost=(Decimal(total_cost_cents) / Decimal(100)).quantize(Decimal("0.01")),
        method='reviewed_forecast_mixed' if any(item.forecast_run_id for item in items) else 'daily_sales_average',items=items,
    )


@app.get("/api/restock", response_model=RestockPlan, tags=["Planning"])
def restock_suggestions(
    lead_time_days: int = Query(default=3, ge=1, le=30),
    coverage_days: int = Query(default=7, ge=1, le=30),
    buffer_days: int = Query(default=2, ge=0, le=14),
):
    with database() as connection:
        return calculate_restock(connection, lead_time_days, coverage_days, buffer_days)


def calculate_purchase_plan(restock: RestockPlan, budget: Decimal):
    budget_cents = int(budget * 100)
    remaining_cents = budget_cents
    items = []
    # Restock items already have a stable urgency order; equal urgency uses product ID.
    for item in restock.items:
        suggested = item.suggested_quantity
        unit_cents = int(item.unit_cost * 100)
        planned = 0
        if suggested is None:
            status = "no_history"
            reason = "Record sales before estimating a purchase quantity."
        elif suggested == 0:
            status = "not_needed"
            reason = "No purchase quantity suggested by the current estimate."
        elif unit_cents == 0:
            status = "price_required"
            reason = "Zero unit cost: confirm a purchase price before including this item."
        else:
            planned = min(suggested, remaining_cents // unit_cents)
            remaining_cents -= planned * unit_cents
            if planned == suggested:
                status = "included"
                reason = "The full suggested quantity fits in the remaining budget."
            elif planned > 0:
                status = "partial"
                reason = "Only part of the suggested quantity fits after higher-priority items."
            else:
                status = "budget_short"
                reason = "The remaining budget cannot cover one unit; quantity is deferred."
        items.append(PurchasePlanItem(
            product_id=item.product_id, sku=item.sku, name=item.name,
            stock=item.stock, unit_cost=item.unit_cost,
            supplier_id=item.supplier_id, supplier_name=item.supplier_name, quote_id=item.quote_id,
            lead_time_days=item.lead_time_days, price_source=item.price_source,
            restock_status=item.status, history_status=item.history_status,
            suggested_quantity=suggested, planned_quantity=planned,
            deferred_quantity=None if suggested is None else suggested - planned,
            line_cost=(Decimal(planned * unit_cents) / Decimal(100)).quantize(Decimal("0.01")),
            allocation_status=status, reason=reason,
            demand_source=item.demand_source,forecast_run_id=item.forecast_run_id,incoming_units=item.incoming_units,
        ))

    return PurchasePlan(
        shop_date=restock.shop_date,
        budget=(Decimal(budget_cents) / Decimal(100)).quantize(Decimal("0.01")),
        planned_cost=(Decimal(budget_cents - remaining_cents) / Decimal(100)).quantize(Decimal("0.01")),
        remaining_budget=(Decimal(remaining_cents) / Decimal(100)).quantize(Decimal("0.01")),
        planned_products=sum(1 for item in items if item.planned_quantity > 0),
        planned_units=sum(item.planned_quantity for item in items),
        deferred_products=sum(1 for item in items if (item.deferred_quantity or 0) > 0),
        price_check_products=sum(1 for item in items if item.allocation_status == "price_required"),
        no_history_products=sum(1 for item in items if item.allocation_status == "no_history"),
        planned_without_supplier=sum(1 for item in items if item.planned_quantity > 0 and item.quote_id is None),
        lead_time_days=restock.lead_time_days, coverage_days=restock.coverage_days, buffer_days=restock.buffer_days,
        items=items,
    )


@app.get("/api/purchase-plan", response_model=PurchasePlan, tags=["Planning"])
def purchase_plan(
    budget: Decimal = Query(default=Decimal("200.00"), ge=0, le=Decimal("1000000.00"), max_digits=9, decimal_places=2, allow_inf_nan=False),
    lead_time_days: int = Query(default=3, ge=1, le=30),
    coverage_days: int = Query(default=7, ge=1, le=30),
    buffer_days: int = Query(default=2, ge=0, le=14),
):
    with database() as connection:
        return calculate_purchase_plan(calculate_restock(connection, lead_time_days, coverage_days, buffer_days), budget)


def money(cents: int) -> Decimal:
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))


ORDER_QUERY = """
    SELECT o.*,
        (SELECT COUNT(*) FROM purchase_order_lines l WHERE l.order_id=o.id) AS item_count,
        (SELECT COALESCE(SUM(quantity),0) FROM purchase_order_lines l WHERE l.order_id=o.id) AS units,
        (SELECT COUNT(DISTINCT supplier_id) FROM purchase_order_lines l WHERE l.order_id=o.id) AS supplier_count,
        pc.state AS payment_state, pc.amount_cents AS payment_amount_cents,
        pc.paypal_order_id, pc.authorization_id, pc.paypal_status, pc.authorized_at,
        pc.expires_at, pc.message AS payment_message, pc.authorization_started_at,
        pc.capture_id, pc.capture_status, pc.captured_at, pc.capture_started_at, pc.void_started_at,
        pc.operation_token, pc.operation_started_at, sr.received_at
    FROM purchase_orders o LEFT JOIN paypal_checkouts pc ON pc.order_id=o.id
    LEFT JOIN stock_receipts sr ON sr.order_id=o.id
"""


def order_summary(row, connection) -> OrderSummary:
    payment = None if row["payment_state"] is None else PaymentStatus(
        state=row["payment_state"], amount=money(row["payment_amount_cents"]),
        paypal_order_id=row["paypal_order_id"], authorization_id=row["authorization_id"],
        paypal_status=row["paypal_status"], authorized_at=row["authorized_at"],
        expires_at=row["expires_at"], message=row["payment_message"],
        capture_id=row["capture_id"], capture_status=row["capture_status"], captured_at=row["captured_at"],
    )
    busy = bool(row["operation_token"] and row["operation_started_at"] and
                (payment_now() - datetime.fromisoformat(row["operation_started_at"])).total_seconds() < PAYPAL_LEASE_SECONDS)
    active = row["status"] == "approved" and not busy
    capture_retry = settlement_retry_allowed(row["capture_started_at"])
    void_retry = settlement_retry_allowed(row["void_started_at"])
    return OrderSummary(
        id=row["id"], number=order_number(connection,row['id']), status=row["status"], version=row["version"],
        created_at=row["created_at"], approved_at=row["approved_at"], cancelled_at=row["cancelled_at"],
        budget=money(row["budget_cents"]), products_total=money(row["products_total_cents"]),
        shipping_cost=money(row["shipping_cents"]), tax_cost=money(row["tax_cents"]),
        grand_total=money(row["products_total_cents"] + row["shipping_cents"] + row["tax_cents"]),
        spending_limit=money(row["approval_limit_cents"]), item_count=row["item_count"],
        units=row["units"], supplier_count=row["supplier_count"], payment=payment,
        can_cancel=row["status"] in ("draft", "approved") and (
            payment is None or (payment.state in ("create_failed", "voided", "expired") and not row["capture_started_at"]) or (
                payment.paypal_order_id is not None and payment.authorization_id is None
                and row["authorization_started_at"] is None and payment.state in (
                    "ready", "create_unknown", "authorize_unknown"))),
        can_capture=bool(active and payment and not row["void_started_at"] and (
            (payment.state == "authorized" and not row["capture_started_at"]) or
            (payment.state in ("capture_unknown", "capturing") and row["capture_started_at"] and capture_retry))),
        can_void=bool(active and payment and not row["capture_started_at"] and (
            (payment.state == "authorized" and not row["void_started_at"]) or
            (payment.state in ("void_unknown", "voiding") and row["void_started_at"] and void_retry))),
        can_receive=bool(active and payment and payment.state == "captured" and not row["received_at"]),
        received_at=row["received_at"],
    )


def order_details(connection, order_id: int) -> OrderDetails:
    row = connection.execute(ORDER_QUERY + " WHERE o.id=?", (order_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    lines = connection.execute("SELECT * FROM purchase_order_lines WHERE order_id=? ORDER BY id", (order_id,)).fetchall()
    items = [OrderLine(
        product_id=line["product_id"], sku=line["sku"], name=line["name"],
        supplier_id=line["supplier_id"], supplier_name=line["supplier_name"], quote_id=line["quote_id"],
        quantity=line["quantity"], unit_cost=money(line["unit_cost_cents"]),
        line_total=money(line["quantity"] * line["unit_cost_cents"]),
        lead_time_days=line["lead_time_days"], history_status=line["history_status"],
        quote_updated_at=line["quote_updated_at"],
        demand_source=json.loads(line['planning_basis']).get('demand_source','sales_average') if line['planning_basis'] else 'sales_average',
        forecast_run_id=json.loads(line['planning_basis']).get('forecast_run_id') if line['planning_basis'] else None,
        incoming_units=json.loads(line['planning_basis']).get('incoming_units',0) if line['planning_basis'] else 0,
    ) for line in lines]
    receipt = None
    if row["received_at"]:
        received = connection.execute("""SELECT r.*, l.sku, l.name FROM stock_receipt_lines r
            JOIN purchase_order_lines l ON l.order_id=r.order_id AND l.product_id=r.product_id
            WHERE r.order_id=? ORDER BY l.id""", (order_id,)).fetchall()
        receipt = StockReceipt(received_at=row["received_at"], units=sum(item["quantity"] for item in received),
            item_count=len(received), items=[StockReceiptLine(**{field: item[field] for field in
                ("product_id", "sku", "name", "quantity", "stock_before", "stock_after")}) for item in received])
    return OrderDetails(**order_summary(row,connection).model_dump(), source_date=row["source_date"],
        lead_time_days=row["lead_time_days"], coverage_days=row["coverage_days"], buffer_days=row["buffer_days"], items=items, receipt=receipt)


@app.get("/api/orders", response_model=list[OrderSummary], tags=["Orders"])
def list_orders(limit: int = Query(default=50, ge=1, le=100)):
    with database() as connection:
        rows = connection.execute(ORDER_QUERY + " ORDER BY o.id DESC LIMIT ?", (limit,)).fetchall()
        return [order_summary(row,connection) for row in rows]


@app.get("/api/orders/{order_id}", response_model=OrderDetails, tags=["Orders"])
def get_order(order_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    with database() as connection:
        return order_details(connection, order_id)


@app.post("/api/orders", response_model=OrderReceipt, status_code=201, tags=["Orders"])
def create_order(data: OrderCreate, response: Response):
    payload = json.dumps({"budget_cents": int(data.budget * 100), "lead": data.lead_time_days,
        "coverage": data.coverage_days, "buffer": data.buffer_days}, sort_keys=True)
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = connection.execute("SELECT * FROM purchase_orders WHERE request_id=?", (str(data.request_id),)).fetchone()
        if previous:
            if previous["request_payload"] != payload:
                raise HTTPException(status_code=409, detail="This request ID belongs to a different draft request.")
            response.status_code = 200
            return OrderReceipt(order=order_details(connection, previous["id"]), replayed=True)
        restock = calculate_restock(connection, data.lead_time_days, data.coverage_days, data.buffer_days)
        plan = calculate_purchase_plan(restock, data.budget)
        lines = [item for item in plan.items if item.planned_quantity > 0]
        if not lines:
            raise HTTPException(status_code=409, detail="No purchase quantities fit this plan. Check sales history, prices and budget.")
        if plan.planned_without_supplier:
            raise HTTPException(status_code=409, detail="Choose a supplier for every planned product before saving a draft.")
        if len(lines) > 100:
            raise HTTPException(status_code=422, detail="This prototype supports up to 100 product lines per order.")
        marks = ",".join("?" for _ in lines)
        active = connection.execute(
            "SELECT o.id FROM purchase_orders o JOIN purchase_order_lines l ON l.order_id=o.id "
            f"WHERE o.status IN ('draft','approved') AND l.product_id IN ({marks}) LIMIT 1",
            tuple(item.product_id for item in lines),
        ).fetchone()
        if active:
            raise HTTPException(status_code=409, detail=f"A planned product is already in open order {order_number(connection,active['id'])}. Review or cancel it first.")
        now = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute(
            """INSERT INTO purchase_orders (request_id,request_payload,created_at,budget_cents,
            products_total_cents,approval_limit_cents,source_date,lead_time_days,coverage_days,buffer_days)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (str(data.request_id), payload, now, int(data.budget * 100), int(plan.planned_cost * 100),
             int(data.budget * 100), plan.shop_date.isoformat(), data.lead_time_days, data.coverage_days, data.buffer_days),
        )
        order_id = cursor.lastrowid
        for item in lines:
            quote = connection.execute("SELECT updated_at FROM supplier_quotes WHERE id=?", (item.quote_id,)).fetchone()
            revision = planning_revision(connection, item.product_id)
            basis = {**planning_context(connection,item.product_id,plan.shop_date),'demand_source':item.demand_source,'incoming_units':item.incoming_units}
            connection.execute(
                """INSERT INTO purchase_order_lines (order_id,product_id,sku,name,supplier_id,supplier_name,
                quote_id,quantity,unit_cost_cents,lead_time_days,stock_at_draft,sale_revision,quote_updated_at,history_status,planning_basis)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (order_id, item.product_id, item.sku, item.name, item.supplier_id, item.supplier_name,
                 item.quote_id, item.planned_quantity, int(item.unit_cost * 100), item.lead_time_days,
                 item.stock, revision, quote["updated_at"], item.history_status,json.dumps(basis,sort_keys=True)),
            )
        return OrderReceipt(order=order_details(connection, order_id), replayed=False)


@app.post("/api/orders/{order_id}/approve", response_model=OrderReceipt, tags=["Orders"])
def approve_order(data: OrderApproval, order_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    shipping = int(data.shipping_cost * 100)
    tax = int(data.tax_cost * 100)
    limit = int(data.spending_limit * 100)
    payload = json.dumps({"version": data.expected_version, "shipping": shipping, "tax": tax, "limit": limit}, sort_keys=True)
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM purchase_orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Order not found.")
        used = connection.execute("SELECT id FROM purchase_orders WHERE approval_request_id=?", (str(data.request_id),)).fetchone()
        if used and used["id"] != order_id:
            raise HTTPException(status_code=409, detail="This approval request ID belongs to another order.")
        if row["status"] == "approved":
            if row["approval_request_id"] == str(data.request_id) and row["approval_payload"] == payload:
                return OrderReceipt(order=order_details(connection, order_id), replayed=True)
            raise HTTPException(status_code=409, detail="Order is already approved. Refresh saved orders to view it.")
        if row["status"] != "draft" or row["version"] != data.expected_version:
            raise HTTPException(status_code=409, detail="Order state changed. Refresh saved orders before continuing.")
        if row["source_date"] != shop_today().isoformat():
            raise HTTPException(status_code=409, detail="The estimate date changed. Cancel this draft and create a fresh one.")
        lines = connection.execute("SELECT * FROM purchase_order_lines WHERE order_id=?", (order_id,)).fetchall()
        for line in lines:
            if line['planning_basis']:
                basis = json.loads(line['planning_basis'])
                context = planning_context(connection,line['product_id'],shop_today())
                if any(basis.get(key) != value for key,value in context.items()):
                    raise HTTPException(409,'Forecast review or expected incoming stock changed. Cancel this draft and create a fresh one.')
            current = connection.execute(
                """SELECT p.stock, ps.quote_id, q.unit_cost_cents, q.lead_time_days,
                ((SELECT COALESCE(MAX(s.id),0) FROM sales s WHERE s.product_id=p.id) +
                 COALESCE((SELECT revision FROM sales_history_revisions WHERE product_id=p.id),0)) AS sale_revision
                FROM products p LEFT JOIN product_sourcing ps ON ps.product_id=p.id
                LEFT JOIN supplier_quotes q ON q.id=ps.quote_id WHERE p.id=?""", (line["product_id"],),
            ).fetchone()
            changed = current is None or any(current[field] != line[field] for field in ("quote_id", "unit_cost_cents", "lead_time_days", "sale_revision"))
            if changed or current["stock"] != line["stock_at_draft"]:
                raise HTTPException(status_code=409, detail="Inventory or supplier quote changed. Cancel this draft and create a fresh one.")
        total = row["products_total_cents"] + shipping + tax
        if total > limit:
            raise HTTPException(status_code=409, detail=f"Order total ${money(total)} exceeds spending limit ${money(limit)}. Review charges or the limit.")
        connection.execute(
            """UPDATE purchase_orders SET status='approved',version=version+1,approved_at=?,shipping_cents=?,
            tax_cents=?,approval_limit_cents=?,approval_request_id=?,approval_payload=? WHERE id=?""",
            (datetime.now(timezone.utc).isoformat(), shipping, tax, limit, str(data.request_id), payload, order_id),
        )
        return OrderReceipt(order=order_details(connection, order_id), replayed=False)


@app.post("/api/orders/{order_id}/cancel", response_model=OrderDetails, tags=["Orders"])
def cancel_order(data: OrderCancel, order_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM purchase_orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Order not found.")
        if row["status"] == "cancelled":
            return order_details(connection, order_id)
        if row["status"] not in ("draft", "approved") or row["version"] != data.expected_version:
            raise HTTPException(status_code=409, detail="Order state changed. Refresh saved orders before cancelling.")
        checkout = checkout_row(connection, order_id)
        if checkout and (checkout["capture_started_at"] or checkout["capture_id"] or checkout["state"] in ("captured", "capture_pending")):
            raise HTTPException(status_code=409, detail="A capture was started or confirmed. Unpaid cancellation cannot cancel this payment.")
        if checkout is None or checkout["state"] in ("create_failed", "voided", "expired"):
            connection.execute("UPDATE purchase_orders SET status='cancelled',version=version+1,cancelled_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), order_id))
            return order_details(connection, order_id)
        if checkout["state"] == "authorized" or checkout["authorization_id"]:
            raise HTTPException(status_code=409, detail="A PayPal authorization hold exists. It must be voided before cancelling; unpaid cancellation cannot release funds.")
        if checkout["authorization_started_at"]:
            raise HTTPException(status_code=409, detail="An authorization request was sent or its old result is uncertain. Refresh payment status first; unpaid cancellation cannot dismiss an unresolved authorization.")
        if not checkout["paypal_order_id"]:
            raise HTTPException(status_code=409, detail="The PayPal create result is still unknown. Refresh payment status and reconcile this checkout before cancelling.")
        gateway = payment_gateway()
        require_same_account(checkout, gateway)
        # The same durable lease blocks simultaneous authorize/create/cancel requests.
        token = claim_checkout(connection, checkout)
        snapshot = order_details(connection, order_id)
        remote_id = checkout["paypal_order_id"]
    try:
        result = read_paypal(gateway, snapshot, checkout, remote_id)
    except PayPalFailure as issue:
        save_payment_result(order_id, token, message=str(issue))
        raise HTTPException(status_code=502, detail=str(issue)) from None
    except ValueError as issue:
        save_payment_result(order_id, token, state="review_required", message=str(issue))
        raise HTTPException(status_code=409, detail=str(issue)) from None
    may_cancel = result["state"] in ("ready", "voided", "expired")
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute("SELECT status,version FROM purchase_orders WHERE id=?", (order_id,)).fetchone()
        if current["status"] != "approved" or current["version"] != data.expected_version:
            raise HTTPException(status_code=409, detail="Order state changed. Refresh saved orders before continuing.")
        if result["state"] == "ready":
            result.update(state="cancelled_unpaid", message="Order cancelled locally after PayPal reported no authorization. This app disables further authorization for the old checkout; no PayPal void or refund was sent.")
        # Verification result and local cancellation commit together with the lease token.
        write_payment_result(connection, order_id, token, **result)
        if may_cancel:
            connection.execute("UPDATE purchase_orders SET status='cancelled',version=version+1,cancelled_at=? WHERE id=?",
                (payment_now().isoformat(), order_id))
        saved = order_details(connection, order_id)
    if not may_cancel:
        raise HTTPException(status_code=409, detail="PayPal reports an authorization or pending payment. This order was not cancelled. Refresh its payment status; a hold needs a void before cancellation.")
    return saved


# PayPal operations use short SQLite transactions. Network calls never keep a DB lock.
# One durable lease per order serializes concurrent callbacks, including after restart.
PAYPAL_LEASE_SECONDS = 180
CREATE_RETRY_SECONDS = 300  # Deliberately much shorter than SDK-documented 6-hour create-key retention.
SETTLEMENT_RETRY_SECONDS = 300  # Old uncertain operations require dashboard review, not a new key.
PAYPAL_ID = re.compile(r"^[A-Z0-9]{1,36}$")


def payment_now():
    return datetime.now(timezone.utc)


def settlement_retry_allowed(started_at):
    return not started_at or (payment_now() - datetime.fromisoformat(started_at)).total_seconds() <= SETTLEMENT_RETRY_SECONDS


def checkout_row(connection, order_id):
    return connection.execute("SELECT * FROM paypal_checkouts WHERE order_id=?", (order_id,)).fetchone()


def approved_for_payment(connection, order_id, expected_version=None):
    order = order_details(connection, order_id)
    if order.status != "approved" or (expected_version is not None and order.version != expected_version):
        raise HTTPException(status_code=409, detail="Approve this order first, then refresh its saved details.")
    if order.grand_total <= 0 or order.grand_total > order.spending_limit:
        raise HTTPException(status_code=409, detail="The approved amount is outside the spending limit.")
    return order


def payment_gateway():
    try:
        return SandboxPayPal()
    except PayPalFailure as issue:
        raise HTTPException(status_code=503, detail=str(issue)) from None


def require_same_account(row, gateway):
    if row["account_key"] != gateway.account_key:
        raise HTTPException(status_code=409, detail="This checkout belongs to a different sandbox app. Restore its original Client ID before continuing.")


def claim_checkout(connection, row, state=None):
    now = payment_now()
    if row["operation_token"] and row["operation_started_at"]:
        elapsed = (now - datetime.fromisoformat(row["operation_started_at"])).total_seconds()
        if elapsed < PAYPAL_LEASE_SECONDS:
            raise HTTPException(status_code=409, detail="A PayPal request is still running. Wait for it, then refresh payment status.")
    token = str(uuid4())
    connection.execute(
        "UPDATE paypal_checkouts SET operation_token=?,operation_started_at=?,updated_at=?,state=? WHERE order_id=?",
        (token, now.isoformat(), now.isoformat(), state or row["state"], row["order_id"]),
    )
    return token


def write_payment_result(connection, order_id, token, close_order=False, **changes):
    allowed = {"state", "paypal_order_id", "authorization_id", "paypal_status", "authorized_at", "expires_at", "message",
               "capture_id", "capture_status", "captured_at"}
    assert set(changes) <= allowed
    changes["updated_at"] = payment_now().isoformat()
    changes["operation_token"] = changes["operation_started_at"] = None
    count = connection.execute(
        "UPDATE paypal_checkouts SET " + ",".join(field + "=?" for field in changes) + " WHERE order_id=? AND operation_token=?",
        (*changes.values(), order_id, token),
    ).rowcount
    if count != 1:
        raise HTTPException(status_code=409, detail="Payment state changed. Refresh payment status before continuing.")
    row = checkout_row(connection, order_id)
    if changes.get("state") in ("voided", "expired") and (close_order or row["void_started_at"]) and not row["capture_started_at"]:
        connection.execute("""UPDATE purchase_orders SET status='cancelled',version=version+1,cancelled_at=?
            WHERE id=? AND status='approved'""", (payment_now().isoformat(), order_id))
    return order_details(connection, order_id)


def save_payment_result(order_id, token, **changes):
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        return write_payment_result(connection, order_id, token, **changes)


def paypal_body(order):
    def amount(value):
        return {"currency_code": "USD", "value": format(value, ".2f")}
    # AUTHORIZE supports one purchase unit. This demo uses one sandbox merchant.
    return {
        "intent": "AUTHORIZE",
        "purchase_units": [{
            "reference_id": order.number,
            "custom_id": f"{order.number}-v{order.version}",
            "description": "ReSupply AI sandbox purchasing demo",
            "amount": {**amount(order.grand_total), "breakdown": {
                "item_total": amount(order.products_total),
                "shipping": amount(order.shipping_cost), "tax_total": amount(order.tax_cost),
            }},
            "items": [{"name": item.name, "sku": item.sku,
                       "description": ("Supplier: " + item.supplier_name)[:127],
                       "quantity": str(item.quantity), "category": "PHYSICAL_GOODS",
                       "unit_amount": amount(item.unit_cost)} for item in order.items],
        }],
    }


def inspect_paypal(remote, order, remote_id, version=None):
    return inspect_order(remote, order, remote_id, version or order.version, payment_now())


def read_paypal(gateway, order, row, remote_id=None):
    """Order binding, live authorization and capture GETs must all agree."""
    remote_id = remote_id or row["paypal_order_id"]
    remote = gateway.get(remote_id)
    result = inspect_paypal(remote, order, remote_id, row["order_version"])
    hold_id = result.get("authorization_id") or row["authorization_id"]
    capture_id = result.get("capture_id") or row["capture_id"]
    if row["authorization_id"] and hold_id != row["authorization_id"]:
        raise ValueError("PayPal authorization changed. Check the sandbox dashboard.")
    if row["capture_id"] and capture_id != row["capture_id"]:
        raise ValueError("PayPal capture changed. Check the sandbox dashboard.")
    hold = gateway.get_authorization(hold_id) if hold_id else None
    capture = gateway.get_capture(capture_id) if capture_id else None
    if hold and hold.get("id") != hold_id:
        raise ValueError("PayPal returned a different authorization. Check the sandbox dashboard.")
    if capture and capture.get("id") != capture_id:
        raise ValueError("PayPal returned a different capture. Check the sandbox dashboard.")
    result = inspect_order(remote, order, remote_id, row["order_version"], payment_now(), hold, capture)
    if row["capture_started_at"] and not result.get("capture_id") and result["state"] in ("authorized", "expired", "voided"):
        result.update(state="capture_unknown", message="A capture request was sent and its result is still unconfirmed. Refresh payment status before continuing; void and receiving are blocked.")
    elif row["void_started_at"] and result["state"] == "authorized":
        result.update(state="void_unknown", message="A void request was sent and its result is still unconfirmed. Refresh payment status or retry the same void; capture is blocked.")
    return result


@app.get("/api/paypal/config", tags=["PayPal sandbox"])
def paypal_config(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return public_config()


@app.post("/api/orders/{order_id}/paypal/create", response_model=CheckoutReceipt, tags=["PayPal sandbox"])
def create_paypal_checkout(data: CheckoutCreate, order_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    gateway = payment_gateway()
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        order = approved_for_payment(connection, order_id, data.expected_version)
        row = checkout_row(connection, order_id)
        if row is None:
            now = payment_now().isoformat()
            connection.execute(
                """INSERT INTO paypal_checkouts (order_id,order_version,account_key,amount_cents,state,
                create_request_id,authorize_request_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (order_id, order.version, gateway.account_key, int(order.grand_total * 100), "creating",
                 str(uuid4()), str(uuid4()), now, now),
            )
            row = checkout_row(connection, order_id)
        require_same_account(row, gateway)
        if row["order_version"] != order.version or row["amount_cents"] != int(order.grand_total * 100):
            raise HTTPException(status_code=409, detail="Checkout does not match the saved approval.")
        if row["state"] == "ready" and row["paypal_order_id"] and not row["operation_token"]:
            return CheckoutReceipt(paypal_order_id=row["paypal_order_id"], payment=order.payment)
        if row["capture_started_at"] or row["void_started_at"] or row["state"] in (
                "authorized", "authorizing", "authorize_unknown", "voided", "expired", "review_required", "captured", "capture_pending", "capture_denied"):
            raise HTTPException(status_code=409, detail="Refresh payment status and review this checkout before continuing.")
        if not row["paypal_order_id"] and row["state"] != "create_failed":
            age = (payment_now() - datetime.fromisoformat(row["created_at"])).total_seconds()
            if age > CREATE_RETRY_SECONDS:
                raise HTTPException(status_code=409, detail="The initial PayPal create result is still unknown. Check the sandbox dashboard; automatic creation is blocked to avoid a duplicate checkout.")
        if row["state"] == "create_failed":
            # A confirmed rejection created no remote resource; a fresh key is safe.
            connection.execute("UPDATE paypal_checkouts SET create_request_id=?,created_at=? WHERE order_id=?",
                               (str(uuid4()), payment_now().isoformat(), order_id))
            row = checkout_row(connection, order_id)
        token = claim_checkout(connection, row, "creating")
        remote_id, request_id = row["paypal_order_id"], row["create_request_id"]
    try:
        if not remote_id:
            created = gateway.create(paypal_body(order), request_id)
            remote_id = created.get("id", "")
            if not isinstance(remote_id, str) or not PAYPAL_ID.fullmatch(remote_id):
                raise ValueError("PayPal returned an invalid order ID. Check the sandbox dashboard.")
            # Save ID before the GET. A failed verification must not cause another CREATE.
            with database() as connection:
                changed = connection.execute("UPDATE paypal_checkouts SET paypal_order_id=? WHERE order_id=? AND operation_token=?",
                                             (remote_id, order_id, token)).rowcount
                if changed != 1:
                    raise HTTPException(status_code=409, detail="Checkout state changed. Refresh payment status.")
        result = read_paypal(gateway, order, row, remote_id)
        saved = save_payment_result(order_id, token, **result)
    except PayPalFailure as issue:
        state = "create_failed" if issue.confirmed and not remote_id else "create_unknown"
        save_payment_result(order_id, token, state=state, message=str(issue))
        raise HTTPException(status_code=502, detail=str(issue)) from None
    except ValueError as issue:
        save_payment_result(order_id, token, state="review_required", message=str(issue))
        raise HTTPException(status_code=409, detail=str(issue)) from None
    if saved.payment.state != "ready":
        raise HTTPException(status_code=409, detail=saved.payment.message)
    return CheckoutReceipt(paypal_order_id=remote_id, payment=saved.payment)


@app.post("/api/orders/{order_id}/paypal/authorize", response_model=OrderDetails, tags=["PayPal sandbox"])
def authorize_paypal_checkout(data: CheckoutAuthorize, order_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    gateway = payment_gateway()
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        order = approved_for_payment(connection, order_id)
        row = checkout_row(connection, order_id)
        if row is None or row["paypal_order_id"] != data.paypal_order_id:
            raise HTTPException(status_code=409, detail="This PayPal order ID is not linked to the saved purchase order.")
        require_same_account(row, gateway)
        if row["state"] in ("authorized", "captured"):
            return order  # Idempotent callback, no second authorization.
        if row["capture_started_at"] or row["void_started_at"]:
            raise HTTPException(status_code=409, detail="Payment settlement already started. Refresh payment status.")
        if row["state"] in ("voided", "expired", "review_required"):
            raise HTTPException(status_code=409, detail="This checkout needs review. Refresh payment status.")
        token = claim_checkout(connection, row, "authorizing")
        request_id = row["authorize_request_id"]
    try:
        result = read_paypal(gateway, order, row, data.paypal_order_id)
        if result["state"] == "ready" and result["paypal_status"] == "APPROVED":
            # GET first recovers an authorization even if a previous POST response was lost.
            with database() as connection:
                connection.execute("BEGIN IMMEDIATE")
                approved_for_payment(connection, order_id, order.version)
                changed = connection.execute("""UPDATE paypal_checkouts
                    SET authorization_started_at=COALESCE(authorization_started_at,?),operation_started_at=?
                    WHERE order_id=? AND operation_token=?""",
                    (payment_now().isoformat(), payment_now().isoformat(), order_id, token)).rowcount
                if changed != 1:
                    raise HTTPException(status_code=409, detail="Payment operation changed. Refresh payment status before authorizing.")
            gateway.authorize(data.paypal_order_id, request_id)
            result = read_paypal(gateway, order, row, data.paypal_order_id)
        saved = save_payment_result(order_id, token, **result)
    except PayPalFailure as issue:
        save_payment_result(order_id, token, state="authorize_unknown", message=str(issue))
        raise HTTPException(status_code=502, detail=str(issue)) from None
    except ValueError as issue:
        save_payment_result(order_id, token, state="review_required", message=str(issue))
        raise HTTPException(status_code=409, detail=str(issue)) from None
    if saved.payment.state not in ("authorized", "authorize_unknown"):
        raise HTTPException(status_code=409, detail=saved.payment.message)
    return saved


@app.post("/api/orders/{order_id}/paypal/sync", response_model=OrderDetails, tags=["PayPal sandbox"])
def sync_paypal_checkout(order_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    gateway = payment_gateway()
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        order = order_details(connection, order_id)
        row = checkout_row(connection, order_id)
        if row is None:
            raise HTTPException(status_code=409, detail="This order has no PayPal checkout yet.")
        require_same_account(row, gateway)
        if order.status == "cancelled" and row["state"] == "cancelled_unpaid":
            return order
        if order.status not in ("approved", "received", "cancelled"):
            raise HTTPException(status_code=409, detail="This order has no approved checkout.")
        token = claim_checkout(connection, row)
        remote_id = row["paypal_order_id"]
    if not remote_id:
        return save_payment_result(order_id, token, message="No PayPal order ID was confirmed. Retry checkout within 5 minutes, or check the sandbox dashboard before proceeding.")
    try:
        result = read_paypal(gateway, order, row, remote_id)
        return save_payment_result(order_id, token, **result)
    except PayPalFailure as issue:
        save_payment_result(order_id, token, message=str(issue))
        raise HTTPException(status_code=502, detail=str(issue)) from None
    except ValueError as issue:
        save_payment_result(order_id, token, state="review_required", message=str(issue))
        raise HTTPException(status_code=409, detail=str(issue)) from None


def settlement_post_fence(order_id, token, version, action):
    """Persist the chosen mutation before POST; stale workers cannot send it."""
    column = "capture_started_at" if action == "capture" else "void_started_at"
    other = "void_started_at" if action == "capture" else "capture_started_at"
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        approved_for_payment(connection, order_id, version)
        row = checkout_row(connection, order_id)
        if row["operation_token"] != token or row[other]:
            raise HTTPException(status_code=409, detail="The payment operation changed. Refresh its status before continuing.")
        now = payment_now().isoformat()
        connection.execute(f"UPDATE paypal_checkouts SET {column}=COALESCE({column},?),operation_started_at=? WHERE order_id=? AND operation_token=?",
                           (now, now, order_id, token))


def settle_paypal(order_id, data, action):
    gateway = payment_gateway()
    started_field = "capture_started_at" if action == "capture" else "void_started_at"
    opposite = "void_started_at" if action == "capture" else "capture_started_at"
    key_field = "capture_request_id" if action == "capture" else "void_request_id"
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        order = order_details(connection, order_id)
        row = checkout_row(connection, order_id)
        if row is None or not row["authorization_id"]:
            raise HTTPException(status_code=409, detail="A verified authorization hold is required first.")
        require_same_account(row, gateway)
        if action == "capture" and row["state"] == "captured":
            return order  # Receipt can already be received; never recapture.
        if action == "void" and row["state"] in ("voided", "expired") and order.status == "cancelled":
            return order
        order = approved_for_payment(connection, order_id, data.expected_version)
        if row[opposite]:
            raise HTTPException(status_code=409, detail="The other payment action was already sent. Refresh payment status; capture and void cannot overlap.")
        if row["state"] in ("capture_pending", "capture_denied", "captured", "review_required"):
            raise HTTPException(status_code=409, detail="This payment cannot be settled again. Refresh its status and check the sandbox dashboard.")
        if not settlement_retry_allowed(row[started_field]):
            raise HTTPException(status_code=409, detail="This uncertain payment attempt is older than 5 minutes. Refresh and check the sandbox dashboard; a new payment request is blocked.")
        previous_state = row["state"]
        request_id = row[key_field] or str(uuid4())
        connection.execute(f"UPDATE paypal_checkouts SET {key_field}=? WHERE order_id=?", (request_id, order_id))
        token = claim_checkout(connection, row, "capturing" if action == "capture" else "voiding")
        hold_id = row["authorization_id"]
    try:
        result = read_paypal(gateway, order, row)
        completed = result["state"] == "captured" if action == "capture" else result["state"] in ("voided", "expired")
        if not completed:
            retry_state = "capture_unknown" if action == "capture" else "void_unknown"
            if result["state"] not in ("authorized", retry_state):
                saved = save_payment_result(order_id, token, **result)
                raise HTTPException(status_code=409, detail=saved.payment.message)
            # Unknown CAPTURED details are GET-only until the capture ID is visible.
            if action == "capture" and result["state"] == "capture_unknown":
                live = gateway.get_authorization(hold_id)
                if live.get("status") != "CREATED":
                    saved = save_payment_result(order_id, token, **result)
                    raise HTTPException(status_code=409, detail=saved.payment.message)
            settlement_post_fence(order_id, token, order.version, action)
            if action == "capture":
                body = {"amount": {"currency_code": "USD", "value": format(order.grand_total, ".2f")},
                        "final_capture": True, "invoice_id": f"{order.number}-v{row['order_version']}"}
                captured = gateway.capture(hold_id, body, request_id)
                capture_id = captured.get("id")
                if not isinstance(capture_id, str) or not PAYPAL_ID.fullmatch(capture_id):
                    raise ValueError("PayPal returned no valid capture ID. Refresh payment status and check the sandbox dashboard.")
                # Checkpoint the remote ID before any verification GET can fail.
                with database() as connection:
                    changed = connection.execute("UPDATE paypal_checkouts SET capture_id=? WHERE order_id=? AND operation_token=?",
                                                 (capture_id, order_id, token)).rowcount
                    if changed != 1:
                        raise HTTPException(status_code=409, detail="Payment state changed. Refresh its status.")
            else:
                gateway.void(hold_id, request_id)
            with database() as connection:
                current = checkout_row(connection, order_id)
            result = read_paypal(gateway, order, current)
        saved = save_payment_result(order_id, token, close_order=action == "void", **result)
        if action == "capture" and saved.payment.state not in ("captured", "capture_pending", "capture_unknown"):
            raise HTTPException(status_code=409, detail=saved.payment.message)
        if action == "void" and saved.payment.state not in ("voided", "expired", "void_unknown"):
            raise HTTPException(status_code=409, detail=saved.payment.message)
        return saved
    except PayPalFailure as issue:
        with database() as connection:
            current = checkout_row(connection, order_id)
        state = ("capture_unknown" if action == "capture" else "void_unknown") if current[started_field] else previous_state
        save_payment_result(order_id, token, state=state, message=str(issue))
        raise HTTPException(status_code=502, detail=str(issue)) from None
    except ValueError as issue:
        save_payment_result(order_id, token, state="review_required", message=str(issue))
        raise HTTPException(status_code=409, detail=str(issue)) from None


@app.post("/api/orders/{order_id}/paypal/capture", response_model=OrderDetails, tags=["PayPal sandbox"])
def capture_paypal_checkout(data: CheckoutCreate, order_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    return settle_paypal(order_id, data, "capture")


@app.post("/api/orders/{order_id}/paypal/void", response_model=OrderDetails, tags=["PayPal sandbox"])
def void_paypal_checkout(data: CheckoutCreate, order_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    return settle_paypal(order_id, data, "void")


@app.post("/api/orders/{order_id}/receive", response_model=OrderReceipt, tags=["Stock receiving"])
def receive_order(data: OrderReceive, order_id: int = ApiPath(gt=0, le=9_223_372_036_854_775_807)):
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        order = order_details(connection, order_id)
        used = connection.execute("SELECT order_id FROM stock_receipts WHERE request_id=?", (str(data.request_id),)).fetchone()
        if used and used["order_id"] != order_id:
            raise HTTPException(status_code=409, detail="This receiving request belongs to another order.")
        if order.receipt:
            return OrderReceipt(order=order, replayed=True)
        order = approved_for_payment(connection, order_id, data.expected_version)
        row = checkout_row(connection, order_id)
        if row is None or row["state"] != "captured":
            raise HTTPException(status_code=409, detail="A completed sandbox capture is required before receiving stock.")
        gateway = payment_gateway()
        require_same_account(row, gateway)
        token = claim_checkout(connection, row)
    try:
        result = read_paypal(gateway, order, row)
        if result["state"] != "captured":
            saved = save_payment_result(order_id, token, **result)
            raise HTTPException(status_code=409, detail="Payment capture is not confirmed. No stock was received. " + saved.payment.message)
        with database() as connection:
            connection.execute("BEGIN IMMEDIATE")
            approved_for_payment(connection, order_id, data.expected_version)
            if checkout_row(connection, order_id)["operation_token"] != token:
                raise HTTPException(status_code=409, detail="The receiving operation changed. Refresh this order.")
            used = connection.execute("SELECT order_id FROM stock_receipts WHERE request_id=?", (str(data.request_id),)).fetchone()
            if used and used["order_id"] != order_id:
                raise HTTPException(status_code=409, detail="This receiving request belongs to another order.")
            connection.execute("""INSERT INTO stock_receipts(order_id,request_id,order_version,received_at,units,item_count)
                VALUES(?,?,?,?,?,?)""", (order_id, str(data.request_id), order.version, payment_now().isoformat(), order.units, order.item_count))
            for line in order.items:
                product = connection.execute("SELECT stock FROM products WHERE id=?", (line.product_id,)).fetchone()
                if product is None or product["stock"] + line.quantity > 1_000_000:
                    raise HTTPException(status_code=409, detail=f"Receiving {line.sku} would exceed the stock limit. No items were received; check current stock.")
                before, after = product["stock"], product["stock"] + line.quantity
                connection.execute("UPDATE products SET stock=? WHERE id=?", (after, line.product_id))
                connection.execute("INSERT INTO stock_receipt_lines(order_id,product_id,quantity,stock_before,stock_after) VALUES(?,?,?,?,?)",
                                   (order_id, line.product_id, line.quantity, before, after))
            write_payment_result(connection, order_id, token, **result)
            connection.execute("UPDATE purchase_orders SET status='received',version=version+1 WHERE id=? AND status='approved'", (order_id,))
            saved = order_details(connection, order_id)
        return OrderReceipt(order=saved, replayed=False)
    except PayPalFailure as issue:
        save_payment_result(order_id, token, message=str(issue))
        raise HTTPException(status_code=502, detail=str(issue)) from None
    except ValueError as issue:
        save_payment_result(order_id, token, state="review_required", message=str(issue))
        raise HTTPException(status_code=409, detail=str(issue)) from None
    except HTTPException:
        # Rollback already undid every stock/receipt write. Release only our own lease.
        with database() as connection:
            connection.execute("UPDATE paypal_checkouts SET operation_token=NULL,operation_started_at=NULL WHERE order_id=? AND operation_token=?", (order_id, token))
        raise


# Keep the history router independent of payment and stock mutations.
app.include_router(history_router(database, lambda: shop_today()))
app.include_router(forecast_router(database, lambda: shop_today()))
app.include_router(purchasing_router(database, lambda: shop_today()))
app.include_router(assistant_router(database,lambda:shop_today(),calculate_restock,calculate_purchase_plan))
app.include_router(demo_router(database,lambda:shop_today(),order_details))
app.include_router(easy_router(database,lambda:shop_today()))
app.include_router(llm_router())


def automatic_plan(connection,budget,lead,coverage,buffer):
    return calculate_purchase_plan(calculate_restock(connection,lead,coverage,buffer),budget)


def automatic_draft(budget,coverage,buffer):
    return create_order(OrderCreate(request_id=uuid4(),budget=budget,lead_time_days=3,
        coverage_days=coverage,buffer_days=buffer),Response()).order


def automatic_approval(data,settings):
    return approve_order(OrderApproval(request_id=data.request_id,expected_version=data.expected_version,
        shipping_cost=Decimal(settings['shipping']),tax_cost=Decimal(settings['tax']),
        spending_limit=Decimal(settings['spending_limit'])),data.order_id)


def automatic_cancel(order_id):
    with database() as connection:
        saved=order_details(connection,order_id)
    return cancel_order(OrderCancel(expected_version=saved.version),order_id)


app.include_router(autopilot_router(database,lambda:shop_today(),automatic_plan,calculate_restock,
    automatic_draft,automatic_approval,automatic_cancel,order_details))


@app.get('/assets/shop-workspace.js',include_in_schema=False)
def workspace_script():
    return FileResponse(FRONTEND_PATH.with_name('shop_workspace_ui.js'),media_type='application/javascript',headers={'Cache-Control':'no-store'})


@app.get('/assets/app-ui.css',include_in_schema=False)
def app_styles():
    return FileResponse(FRONTEND_PATH.with_name('app_ui.css'),media_type='text/css',headers={'Cache-Control':'no-store'})


@app.get('/assets/app-ui.js',include_in_schema=False)
def app_navigation():
    return FileResponse(FRONTEND_PATH.with_name('app_ui.js'),media_type='application/javascript',headers={'Cache-Control':'no-store'})


@app.get('/assets/demo-shop.js',include_in_schema=False)
def demo_shop_script():
    return FileResponse(FRONTEND_PATH.with_name('demo_shop_ui.js'),media_type='application/javascript',headers={'Cache-Control':'no-store'})


@app.get("/assets/sales-history.js", include_in_schema=False)
def sales_history_script():
    return FileResponse(FRONTEND_PATH.with_name("sales_history_ui.js"), media_type="application/javascript",
                        headers={"Cache-Control":"no-store"})


@app.get("/assets/demand-forecast.js", include_in_schema=False)
def demand_forecast_script():
    return FileResponse(FRONTEND_PATH.with_name("demand_forecast_ui.js"), media_type="application/javascript",
                        headers={"Cache-Control":"no-store"})


@app.get('/assets/forecast-purchasing.js',include_in_schema=False)
def forecast_purchasing_script():
    return FileResponse(FRONTEND_PATH.with_name('forecast_purchasing_ui.js'),media_type='application/javascript',headers={'Cache-Control':'no-store'})


@app.get('/assets/voice-assistant.js',include_in_schema=False)
def voice_assistant_script():
    return FileResponse(FRONTEND_PATH.with_name('voice_assistant_ui.js'),media_type='application/javascript',headers={'Cache-Control':'no-store'})


@app.get('/assets/easy-shop.js',include_in_schema=False)
def easy_script():
    return FileResponse(FRONTEND_PATH.with_name('easy_shop_ui.js'),media_type='application/javascript',headers={'Cache-Control':'no-store'})


@app.get('/assets/easy-shop.css',include_in_schema=False)
def easy_style():
    return FileResponse(FRONTEND_PATH.with_name('easy_shop.css'),media_type='text/css',headers={'Cache-Control':'no-store'})
