"""Completed daily totals for forecasting; imports never mutate live inventory."""
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
import re
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from shop_workspace import is_demo_shop, planning_source

MAX_CSV_BYTES = 300_000
MAX_CSV_ROWS = 1000


def initialize_history(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS daily_sales_history (
        product_id INTEGER NOT NULL REFERENCES products(id),
        sale_date TEXT NOT NULL,
        units_sold INTEGER NOT NULL CHECK(units_sold BETWEEN 0 AND 1000000),
        source TEXT NOT NULL CHECK(source IN ('actual','demo')),
        stockout INTEGER NOT NULL CHECK(stockout IN (0,1)),
        revision INTEGER NOT NULL CHECK(revision > 0),
        updated_at TEXT NOT NULL,
        PRIMARY KEY(product_id,sale_date)
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS sales_history_revisions (
        product_id INTEGER PRIMARY KEY REFERENCES products(id), revision INTEGER NOT NULL
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS sales_history_requests (
        request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, response TEXT NOT NULL,
        preview_id TEXT UNIQUE, created_at TEXT NOT NULL
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS sales_history_previews (
        id TEXT PRIMARY KEY, rows_payload TEXT NOT NULL, created_at TEXT NOT NULL
    )""")


class DaySave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    product_id: int = Field(gt=0, le=9_223_372_036_854_775_807, strict=True)
    sale_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    units_sold: int = Field(ge=0, le=1_000_000, strict=True)
    source: Literal["actual", "demo"] = "actual"
    stockout: bool = Field(default=False, strict=True)
    expected_revision: int = Field(ge=0, strict=True)


class CSVPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str = Field(min_length=1, max_length=MAX_CSV_BYTES)


class CSVCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    preview_id: UUID


def product_row(connection, product_id):
    row = connection.execute("SELECT id,sku,name FROM products WHERE id=?", (product_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Product not found.")
    return row


def validate_day(value, today):
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError()
        result = date.fromisoformat(value)
        if result < date(1900, 1, 1) or result >= today:
            raise ValueError()
        return result.isoformat()
    except (ValueError, TypeError):
        raise HTTPException(422, "Use a valid past date (YYYY-MM-DD). Today is still partial; record today's sales with Record sale.") from None


def logged_units(connection, product_id, sale_date):
    return connection.execute("SELECT COALESCE(SUM(quantity),0) FROM sales WHERE product_id=? AND sale_date=?",
                              (product_id, sale_date)).fetchone()[0]


def daily_row(connection, product_id, sale_date):
    return connection.execute("SELECT * FROM daily_sales_history WHERE product_id=? AND sale_date=?",
                              (product_id, sale_date)).fetchone()


def validate_total(connection, row):
    if is_demo_shop() and row['source'] != 'demo':
        raise HTTPException(409, 'Demo shop history must stay labeled demo / synthetic. Use the existing shop for actual records.')
    if row["source"] == "actual" and row["units_sold"] < logged_units(connection, row["product_id"], row["sale_date"]):
        raise HTTPException(409, "Actual daily total is lower than sales already logged for this product/date. Include those sales in the full-day total.")


def same_total(old, row):
    return old is not None and all(old[key] == row[key] for key in ("units_sold", "source", "stockout"))


def save_total(connection, row):
    old = daily_row(connection, row["product_id"], row["sale_date"])
    revision = (old["revision"] if old else 0) + 1
    now = datetime.now(timezone.utc).isoformat()
    connection.execute("""INSERT INTO daily_sales_history(product_id,sale_date,units_sold,source,stockout,revision,updated_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(product_id,sale_date) DO UPDATE SET
        units_sold=excluded.units_sold,source=excluded.source,stockout=excluded.stockout,
        revision=excluded.revision,updated_at=excluded.updated_at""",
        (row["product_id"], row["sale_date"], row["units_sold"], row["source"], int(row["stockout"]), revision, now))
    if is_demo_shop() or row["source"] == "actual" or (old and old["source"] == "actual"):
        connection.execute("""INSERT INTO sales_history_revisions(product_id,revision) VALUES(?,1)
            ON CONFLICT(product_id) DO UPDATE SET revision=revision+1""", (row["product_id"],))
    return revision


def cached_request(connection, request_id, payload):
    saved = connection.execute("SELECT * FROM sales_history_requests WHERE request_id=?", (str(request_id),)).fetchone()
    if saved:
        if saved["payload"] != payload:
            raise HTTPException(409, "This request ID belongs to different sales-history values.")
        return {**json.loads(saved["response"]), "replayed": True}


def record_request(connection, request_id, payload, response, preview_id=None):
    connection.execute("INSERT INTO sales_history_requests(request_id,payload,response,preview_id,created_at) VALUES(?,?,?,?,?)",
        (str(request_id), payload, json.dumps(response, sort_keys=True), preview_id, datetime.now(timezone.utc).isoformat()))


def planning_revision(connection, product_id):
    return connection.execute("""SELECT (SELECT COALESCE(MAX(id),0) FROM sales WHERE product_id=?) +
        COALESCE((SELECT revision FROM sales_history_revisions WHERE product_id=?),0)""", (product_id, product_id)).fetchone()[0]


def completed_planning_days(connection, start, end, source='actual'):
    rows = connection.execute("""SELECT product_id,sale_date,units_sold,stockout FROM daily_sales_history
        WHERE source=? AND sale_date>=? AND sale_date<? ORDER BY sale_date""",
        (source, start.isoformat(), end.isoformat())).fetchall()
    result = {}
    for row in rows:
        result.setdefault(row["product_id"], []).append(row)
    return result


def completed_actual_days(connection, start, end):
    return completed_planning_days(connection, start, end, 'actual')


def history_router(database, shop_today):
    router = APIRouter(prefix="/api/sales-history", tags=["Daily sales history"])

    @router.get("/day")
    def get_day(product_id: int = Query(gt=0, le=9_223_372_036_854_775_807), sale_date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$")):
        validate_day(sale_date, shop_today())
        with database() as connection:
            product = product_row(connection, product_id)
            row = daily_row(connection, product_id, sale_date)
            return {"product_id": product_id, "sku": product["sku"], "sale_date": sale_date,
                "units_sold": row["units_sold"] if row else None, "source": row["source"] if row else planning_source(),
                "stockout": bool(row["stockout"]) if row else False, "revision": row["revision"] if row else 0,
                "logged_units": logged_units(connection, product_id, sale_date)}

    @router.put("/day")
    def put_day(data: DaySave):
        row = data.model_dump(exclude={"request_id"})
        payload = "day:" + json.dumps(row, sort_keys=True)
        with database() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = cached_request(connection, data.request_id, payload)
            if previous:
                return previous
            validate_day(data.sale_date, shop_today())
            product_row(connection, data.product_id)
            validate_total(connection, row)
            old = daily_row(connection, data.product_id, data.sale_date)
            if (old["revision"] if old else 0) != data.expected_revision:
                raise HTTPException(409, "This daily total changed. Reload the day before saving your correction.")
            changed = not same_total(old, row)
            revision = save_total(connection, row) if changed else old["revision"]
            result = {"product_id": data.product_id, "sale_date": data.sale_date, "revision": revision,
                      "changed": changed, "replayed": False, "message": "Full-day total saved. Inventory is unchanged."}
            record_request(connection, data.request_id, payload, result)
            return result

    @router.get("/requests/{request_id}")
    def request_status(request_id: UUID):
        with database() as connection:
            row = connection.execute("SELECT response FROM sales_history_requests WHERE request_id=?", (str(request_id),)).fetchone()
        if row is None:
            raise HTTPException(404, "This history request has not been confirmed yet.")
        return {**json.loads(row["response"]), "replayed": True}

    @router.get("")
    def get_history(product_id: int = Query(gt=0, le=9_223_372_036_854_775_807), days: int = Query(default=90, ge=7, le=365)):
        today = shop_today()
        start = today - timedelta(days=days-1)
        with database() as connection:
            product = product_row(connection, product_id)
            records = {row["sale_date"]: row for row in connection.execute("SELECT * FROM daily_sales_history WHERE product_id=? AND sale_date BETWEEN ? AND ?",
                       (product_id, start.isoformat(), today.isoformat()))}
            logged = {row["sale_date"]: row["units"] for row in connection.execute("SELECT sale_date,SUM(quantity) AS units FROM sales WHERE product_id=? AND sale_date BETWEEN ? AND ? GROUP BY sale_date",
                      (product_id, start.isoformat(), today.isoformat()))}
        items = []
        for offset in range(days):
            value = (start + timedelta(days=offset)).isoformat()
            record = records.get(value)
            state = "stockout" if record and record["stockout"] else "complete" if record else "today_partial" if value == today.isoformat() else "logged_only" if value in logged else "missing"
            items.append({"sale_date": value, "units_sold": record["units_sold"] if record else logged.get(value),
                "source": record["source"] if record else "live" if value in logged else None,
                "status": state, "stockout": bool(record["stockout"]) if record else False,
                "revision": record["revision"] if record else 0, "logged_units": logged.get(value, 0)})
        actual = sum(bool(r) and r["source"] == "actual" for r in records.values())
        demo = sum(bool(r) and r["source"] == "demo" for r in records.values())
        zero = sum(r["units_sold"] == 0 and not r["stockout"] for r in records.values())
        eligible = sum(r["source"] == "actual" and not r["stockout"] for r in records.values())
        return {"product_id": product_id, "sku": product["sku"], "name": product["name"], "shop_date": today.isoformat(),
            "start_date": start.isoformat(), "end_date": today.isoformat(), "actual_days": actual, "demo_days": demo,
            "eligible_actual_days": eligible, "zero_sales_days": zero, "stockout_days": sum(bool(r["stockout"]) for r in records.values()),
            "missing_days": sum(item["status"] == "missing" for item in items),
            "unconfirmed_days": sum(item["status"] == "logged_only" for item in items),
            "message": "Missing dates are unknown, not zero. Logged-only days need a confirmed full-day total. Demo and stockout days are excluded from the actual completed-day purchasing baseline. Train actual and demo records separately in ML demand forecast.",
            "items": items}

    @router.post("/import/preview")
    def preview_csv(data: CSVPreview):
        if len(data.csv_text.encode("utf-8")) > MAX_CSV_BYTES:
            raise HTTPException(422, "CSV must be at most 300 KB.")
        try:
            reader = csv.DictReader(io.StringIO(data.csv_text.lstrip("\ufeff")), strict=True)
            headers = reader.fieldnames or []
            required, allowed = {"date", "sku", "units_sold"}, {"date", "sku", "units_sold", "source", "stockout"}
            if len(headers) != len(set(headers)) or not required <= set(headers) or not set(headers) <= allowed:
                raise HTTPException(422, "CSV headers must be date,sku,units_sold with optional source,stockout.")
            input_rows = []
            for row in reader:
                input_rows.append((reader.line_num, row))
                if len(input_rows) > MAX_CSV_ROWS:
                    raise HTTPException(422, "Import at most 1000 data rows per CSV.")
        except csv.Error:
            raise HTTPException(422, "CSV quoting or structure is invalid.") from None
        if not input_rows or len(input_rows) > MAX_CSV_ROWS:
            raise HTTPException(422, "Import 1 to 1000 data rows per CSV.")
        results, saved_rows, seen = [], [], set()
        today = shop_today()
        with database() as connection:
            products = {row["sku"]: row for row in connection.execute("SELECT id,sku FROM products")}
            for line, raw in input_rows:
                errors = []
                sku = (raw.get("sku") or "").strip().upper()
                value = (raw.get("date") or "").strip()
                quantity = (raw.get("units_sold") or "").strip()
                source = (raw.get("source") or "actual").strip().lower()
                stockout = (raw.get("stockout") or "0").strip().lower()
                product = products.get(sku)
                if None in raw or any(raw.get(key) is None for key in headers):
                    errors.append("Row has missing or extra columns.")
                if not product:
                    errors.append("SKU does not exist. Add the product first.")
                try:
                    validate_day(value, today)
                except HTTPException as issue:
                    errors.append(issue.detail)
                units = int(quantity) if re.fullmatch(r"[0-9]{1,7}", quantity) else None
                if units is None or units > 1_000_000:
                    errors.append("Units must be a whole number from 0 to 1000000; a blank value is not zero.")
                if source not in ("actual", "demo"):
                    errors.append("Source must be actual or demo.")
                if stockout not in ("0", "1", "false", "true"):
                    errors.append("Stockout must be 0/1 or false/true.")
                key = (sku, value)
                if key in seen:
                    errors.append("Duplicate SKU/date in this CSV.")
                seen.add(key)
                normalized = {"product_id": product["id"] if product else None, "sku": sku, "sale_date": value,
                              "units_sold": units, "source": source, "stockout": stockout in ("1", "true")}
                old = daily_row(connection, product["id"], value) if product else None
                normalized["expected_revision"] = old["revision"] if old else 0
                if not errors:
                    try:
                        validate_total(connection, normalized)
                    except HTTPException as issue:
                        errors.append(issue.detail)
                    if old and not same_total(old, normalized):
                        errors.append("A different daily total already exists. Correct it with Save full-day total before importing.")
                state = "invalid" if errors else "unchanged" if old else "new"
                results.append({**normalized, "line": line, "status": state, "errors": errors})
                saved_rows.append(normalized)
            valid = all(row["status"] != "invalid" for row in results)
            preview_id = str(uuid4()) if valid else None
            if valid:
                connection.execute("INSERT INTO sales_history_previews(id,rows_payload,created_at) VALUES(?,?,?)",
                    (preview_id, json.dumps(saved_rows, sort_keys=True), datetime.now(timezone.utc).isoformat()))
        return {"preview_id": preview_id, "valid": valid, "new_rows": sum(r["status"] == "new" for r in results),
            "unchanged_rows": sum(r["status"] == "unchanged" for r in results), "invalid_rows": sum(r["status"] == "invalid" for r in results),
            "actual_rows": sum(r["source"] == "actual" for r in results), "demo_rows": sum(r["source"] == "demo" for r in results), "rows": results}

    @router.post("/import/commit")
    def commit_csv(data: CSVCommit):
        payload = "import:" + str(data.preview_id)
        today = shop_today()
        with database() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = cached_request(connection, data.request_id, payload)
            if previous:
                return previous
            applied = connection.execute("SELECT response FROM sales_history_requests WHERE preview_id=?", (str(data.preview_id),)).fetchone()
            if applied:
                result = {**json.loads(applied["response"]), "replayed": True}
                record_request(connection, data.request_id, payload, result)
                return result
            preview = connection.execute("SELECT * FROM sales_history_previews WHERE id=?", (str(data.preview_id),)).fetchone()
            if preview is None:
                raise HTTPException(404, "Preview not found. Preview the CSV again.")
            if datetime.now(timezone.utc) - datetime.fromisoformat(preview["created_at"]) > timedelta(minutes=20):
                raise HTTPException(409, "Preview expired. Preview the CSV again before importing.")
            rows = json.loads(preview["rows_payload"])
            inserted = unchanged = 0
            for row in rows:
                validate_day(row["sale_date"], today)
                product = product_row(connection, row["product_id"])
                if product["sku"] != row["sku"]:
                    raise HTTPException(409, "A product changed. Preview the CSV again.")
                old = daily_row(connection, row["product_id"], row["sale_date"])
                if (old["revision"] if old else 0) != row["expected_revision"]:
                    raise HTTPException(409, "Daily data changed after preview. Preview the CSV again; nothing was imported.")
                validate_total(connection, row)
                if old:
                    unchanged += 1
                else:
                    save_total(connection, row)
                    inserted += 1
            result = {"inserted": inserted, "unchanged": unchanged,
                      "actual_rows": sum(r["source"] == "actual" for r in rows), "demo_rows": sum(r["source"] == "demo" for r in rows),
                      "replayed": False, "message": "Daily history imported. Current inventory and live sales events are unchanged."}
            record_request(connection, data.request_id, payload, result, str(data.preview_id))
            return result

    def csv_response(rows, filename):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["date", "sku", "units_sold", "source", "stockout"])
        writer.writerows(rows)
        return Response(stream.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})

    @router.get("/template")
    def template(product_id: int = Query(gt=0, le=9_223_372_036_854_775_807)):
        with database() as connection:
            product = product_row(connection, product_id)
        yesterday = (shop_today() - timedelta(days=1)).isoformat()
        return csv_response([[yesterday, product["sku"], "", planning_source(), 0]], "resupply-sales-template.csv")

    @router.get("/demo")
    def demo(product_id: int = Query(gt=0, le=9_223_372_036_854_775_807)):
        with database() as connection:
            product = product_row(connection, product_id)
        end = shop_today() - timedelta(days=2)
        rows = []
        for index in range(60):
            day = end - timedelta(days=59-index)
            units = 0 if index % 17 == 0 else 5 + (day.weekday() >= 5) * 4 + index % 4
            rows.append([day.isoformat(), product["sku"], units, "demo", 0])
        return csv_response(rows, "resupply-demo-sales.csv")

    @router.get("/export")
    def export(product_id: int = Query(gt=0, le=9_223_372_036_854_775_807)):
        with database() as connection:
            product = product_row(connection, product_id)
            rows = connection.execute("SELECT sale_date,units_sold,source,stockout FROM daily_sales_history WHERE product_id=? ORDER BY sale_date", (product_id,)).fetchall()
        return csv_response([[r["sale_date"], product["sku"], r["units_sold"], r["source"], r["stockout"]] for r in rows], "resupply-sales-history.csv")

    return router
