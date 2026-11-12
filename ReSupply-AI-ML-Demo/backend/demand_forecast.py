"""Per-SKU ML forecasts. Training reads history; reports never place orders."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from fractions import Fraction
from math import ceil, isfinite
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from shop_workspace import is_demo_shop

ALGORITHM_VERSION = "rf-daily-v2-planning"
LOOKBACK = 14
MIN_DAYS = 56
MIN_TRAIN_SAMPLES = 21
MAX_AGE_DAYS = 7
FORECAST_DAYS = 7
FEATURES = ["Previous day", "Same weekday last week", "Last 7-day average",
            "Last 14-day average"] + ["Weekday " + str(i) for i in range(7)]


def initialize_forecast(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS demand_forecast_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL UNIQUE,
        request_payload TEXT NOT NULL,
        product_id INTEGER NOT NULL REFERENCES products(id),
        source TEXT NOT NULL CHECK(source IN ('actual','demo')),
        data_fingerprint TEXT NOT NULL,
        shop_date TEXT NOT NULL,
        report TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS forecast_product_source ON demand_forecast_runs(product_id,source,id)")


class TrainForecast(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    product_id: int = Field(gt=0, le=9_223_372_036_854_775_807, strict=True)
    source: Literal["actual", "demo"] = "actual"


def history_snapshot(connection, product_id, source, today):
    product = connection.execute("SELECT id,sku,name,stock FROM products WHERE id=?", (product_id,)).fetchone()
    if product is None:
        raise HTTPException(404, "Product not found.")
    start = today - timedelta(days=365)
    all_rows = [dict(r) for r in connection.execute("""SELECT sale_date,units_sold,source,stockout,revision
        FROM daily_sales_history WHERE product_id=? AND sale_date>=? AND sale_date<? ORDER BY sale_date""",
        (product_id, start.isoformat(), today.isoformat()))]
    rows = [r for r in all_rows if r["source"] == source]
    fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    eligible = {date.fromisoformat(r["sale_date"]): r for r in rows if not r["stockout"]}
    end = max(eligible) if eligible else None
    run = []
    cursor = end
    while cursor in eligible:
        run.append({"date": cursor, "units": eligible[cursor]["units_sold"]})
        cursor -= timedelta(days=1)
    run.reverse()
    age = (today - end).days if end else None
    if not rows:
        reason = "No confirmed " + source + " daily totals. Import or save full-day records first."
        if source == "actual" and any(r["source"] == "demo" for r in all_rows):
            reason += " For the imported sample CSV, choose Demo / synthetic."
    elif not eligible:
        reason = "All selected days have stockout flags. Confirm full days without stockouts before training."
    elif age > MAX_AGE_DAYS:
        reason = "Latest usable day is too old. Add recent full-day totals, then train again."
    elif len(run) < MIN_DAYS:
        reason = f"Need {MIN_DAYS} consecutive full days without stockouts from this source; the latest uninterrupted run has {len(run)}. Missing or other-source dates break the run."
    else:
        reason = f"Ready: {len(run)} consecutive {source} days. Zero-sales days are included."
    span = (date.fromisoformat(rows[-1]["sale_date"]) - date.fromisoformat(rows[0]["sale_date"])).days + 1 if rows else 0
    return {"product": dict(product), "source": source, "shop_date": today.isoformat(),
        "fingerprint": fingerprint, "run": run,
        "ready": bool(end and age <= MAX_AGE_DAYS and len(run) >= MIN_DAYS), "reason": reason,
        "coverage": {"full_days": len(rows), "eligible_days": len(eligible),
            "stockout_days": sum(bool(r["stockout"]) for r in rows), "missing_source_days": span - len(rows),
            "consecutive_days": len(run), "first_day": run[0]["date"].isoformat() if run else None,
            "last_day": end.isoformat() if end else None, "age_days": age,
            "other_source_days": len(all_rows) - len(rows), "minimum_days": MIN_DAYS}}


def feature_row(values, target_date):
    """Every feature is known before the target day; never use that day's label."""
    return [values[-1], values[-7], sum(values[-7:]) / 7, sum(values[-14:]) / 14] + [
        float(target_date.weekday() == day) for day in range(7)]


def training_rows(run):
    values = [r["units"] for r in run]
    return ([feature_row(values[:i], run[i]["date"]) for i in range(LOOKBACK, len(run))], values[LOOKBACK:])


def new_model():
    # Lazy import: an uninstalled ML dependency does not break the existing shop.
    try:
        from sklearn.ensemble import RandomForestRegressor
    except ImportError:
        raise HTTPException(503, "ML package is missing. In backend run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt, then restart the server.") from None
    return RandomForestRegressor(n_estimators=80, max_depth=7, min_samples_leaf=2,
                                 random_state=42, n_jobs=1)


def recursive_predictions(model, run, length):
    values = [float(r["units"]) for r in run]
    last = run[-1]["date"]
    result = []
    for offset in range(1, length + 1):
        target = last + timedelta(days=offset)
        value = float(model.predict([feature_row(values, target)])[0])
        if not isfinite(value):
            raise HTTPException(503, "Model could not produce a finite forecast. Review daily totals and retrain.")
        value = max(0.0, min(1_000_000.0, value))
        result.append({"date": target.isoformat(), "units": value})
        # Forecasts bridge unobserved future dates; they are never stored as sales.
        values.append(value)
    return result


def train_report(snapshot):
    run = snapshot["run"]
    bridge_days = snapshot["coverage"]["age_days"]
    horizon = bridge_days + FORECAST_DAYS
    fold_count = min(3, (len(run) - LOOKBACK - MIN_TRAIN_SAMPLES) // horizon)
    if fold_count < 1:
        raise HTTPException(422, "Not enough consecutive history for a chronological forecast comparison.")
    tested = []
    folds = []
    for fold in range(fold_count):
        cut = len(run) - (fold_count - fold) * horizon
        past = run[:cut]
        X, y = training_rows(past)
        candidate = new_model().fit(X, y)
        predictions = recursive_predictions(candidate, past, horizon)
        baseline = sum(r["units"] for r in past[-7:]) / 7
        score_rows = []
        for step in range(bridge_days, horizon):
            observed = run[cut + step]
            assert predictions[step]["date"] == observed["date"].isoformat()
            score_rows.append({"date": observed["date"].isoformat(), "observed_units": observed["units"],
                "model_units": round(predictions[step]["units"], 4), "baseline_units": round(baseline, 4), "fold": fold + 1})
        tested.extend(score_rows)
        folds.append({"fold": fold + 1, "training_end": past[-1]["date"].isoformat(), "training_samples": len(y),
                      "test_start": score_rows[0]["date"], "test_end": score_rows[-1]["date"], "test_days": FORECAST_DAYS})
    model_mae = sum(abs(r["model_units"] - r["observed_units"]) for r in tested) / len(tested)
    baseline_mae = sum(abs(r["baseline_units"] - r["observed_units"]) for r in tested) / len(tested)
    improvement = 100 * (baseline_mae - model_mae) / baseline_mae if baseline_mae > 0 else None
    use_model = baseline_mae > 0 and model_mae <= baseline_mae * 0.95
    selected = "random_forest" if use_model else "seven_day_mean"
    # Refit only after evaluating the fixed candidate on earlier -> later splits.
    X, y = training_rows(run)
    candidate = new_model().fit(X, y)
    estimates = recursive_predictions(candidate, run, bridge_days + 74)
    mean = sum(r["units"] for r in run[-7:]) / 7
    future = [{"date": row["date"], "model_units": round(row["units"], 2), "baseline_units": round(mean, 2),
               "selected_units": round(row["units"] if use_model else mean, 2)} for row in estimates[bridge_days:bridge_days+FORECAST_DAYS]]
    planning_items = [{"date":row['date'],"selected_units":format(row['units'],'.6f') if use_model else str(Fraction(sum(day['units'] for day in run[-7:]),7))}
                      for row in estimates[bridge_days-1:]]
    import sklearn
    return {"algorithm_version": ALGORITHM_VERSION, "model_name": "Random Forest", "sklearn_version": sklearn.__version__,
        "source": snapshot["source"], "demo": snapshot["source"] == "demo", "shop_date": snapshot["shop_date"],
        "data_start": run[0]["date"].isoformat(), "data_end": run[-1]["date"].isoformat(),
        "training_days": len(run), "training_units":sum(day['units'] for day in run), "training_samples": len(y), "features": FEATURES,
        "planning_items":planning_items,
        "planning_limitations":"Today's remaining demand plus up to 74 future days. The historical comparison validates 7-day horizons only; longer projections need owner review.",
        "bridge_days": bridge_days, "bridge_estimates": [{"date":r["date"], "model_units":round(r["units"], 2)} for r in estimates[:bridge_days]],
        "selected_method": selected, "selection_reason": "ML error was at least 5% lower than the 7-day mean on the tested dates." if use_model else
            "ML did not improve the tested error by at least 5%. The 7-day mean is used for this forecast.",
        "evaluation": {"metric": "MAE", "model_mae": round(model_mae, 4), "baseline_mae": round(baseline_mae, 4),
            "improvement_percent": round(improvement, 2) if improvement is not None else None,
            "test_days": len(tested), "folds": folds, "items": tested,
            "method": "Expanding chronological backtests. Each forecast recursively predicts the entire horizon without observing any test-day sales; the same gap and 7-day target horizon are used as for the current forecast."},
        "items": future, "selected_total_units": round(sum(r["units"] for r in estimates[bridge_days:bridge_days+FORECAST_DAYS]) if use_model else mean * FORECAST_DAYS, 2),
        "model_total_units": round(sum(r["units"] for r in estimates[bridge_days:bridge_days+FORECAST_DAYS]), 2), "baseline_total_units": round(mean * FORECAST_DAYS, 2),
        "limitations": "Candidate comparison on a small historical sample, not a guaranteed accuracy score. Promotions, weather, holidays and lost stockout demand are not modelled. Demo results only describe synthetic data."}


def response_view(connection, snapshot, saved=None, replayed=False):
    from forecast_purchasing import review_status
    report = json.loads(saved["report"]) if saved else None
    current = bool(saved and saved["data_fingerprint"] == snapshot["fingerprint"] and
        saved["shop_date"] == snapshot["shop_date"] and report["algorithm_version"] == ALGORITHM_VERSION)
    advice = None
    if current and snapshot["source"] == "actual":
        demand = ceil(report["selected_total_units"])
        advice = {"stock_now": snapshot["product"]["stock"], "forecast_units_rounded_up": demand,
                  "seven_day_gap": max(0, demand - snapshot["product"]["stock"]),
                  "message": "Tomorrow's 7-day demand versus stock now. Preview and review purchasing below to include today's remaining demand, supplier delivery, coverage, buffer and incoming orders."}
    return {"product": snapshot["product"], "source": snapshot["source"], "shop_date": snapshot["shop_date"],
        "ready": snapshot["ready"], "reason": snapshot["reason"], "coverage": snapshot["coverage"],
        "report": report, "report_current": current, "run_id": saved["id"] if saved else None,
        "trained_at": saved["created_at"] if saved else None, "advice": advice, "replayed": replayed,
        "planning":review_status(connection,snapshot['product']['id'],snapshot['source'],saved,date.fromisoformat(snapshot['shop_date'])),
        "message": "Saved forecast is outdated. History, shop date or model definition changed; train again." if saved and not current else
            "Demo shop forecast: synthetic data only. Review it before using it for this isolated shop's purchasing." if is_demo_shop() else
            "Demo forecast: synthetic data only. No real purchasing suggestion." if snapshot["source"] == "demo" else
            "Forecast is advisory. Orders still require your review and approval."}


def forecast_router(database, shop_today):
    router = APIRouter(prefix="/api/forecast", tags=["ML demand forecast"])

    @router.get("")
    def get_forecast(product_id: int = Query(gt=0, le=9_223_372_036_854_775_807), source: Literal["actual", "demo"] = "actual"):
        with database() as connection:
            connection.execute("BEGIN")
            snapshot = history_snapshot(connection, product_id, source, shop_today())
            saved = connection.execute("SELECT * FROM demand_forecast_runs WHERE product_id=? AND source=? ORDER BY id DESC LIMIT 1", (product_id, source)).fetchone()
            return response_view(connection, snapshot, saved)

    @router.get("/requests/{request_id}")
    def get_request(request_id: UUID):
        with database() as connection:
            connection.execute("BEGIN")
            saved = connection.execute("SELECT * FROM demand_forecast_runs WHERE request_id=?", (str(request_id),)).fetchone()
            if not saved:
                raise HTTPException(404, "This training request has not saved a result yet.")
            snapshot = history_snapshot(connection, saved["product_id"], saved["source"], shop_today())
            return response_view(connection, snapshot, saved, replayed=True)

    @router.post("/train")
    def train_forecast(data: TrainForecast):
        if is_demo_shop() and data.source != 'demo':
            raise HTTPException(422, 'Demo shop trains synthetic history only. Choose Demo / synthetic.')
        payload = json.dumps(data.model_dump(exclude={"request_id"}), sort_keys=True)
        today = shop_today()
        with database() as connection:
            connection.execute("BEGIN")
            saved = connection.execute("SELECT * FROM demand_forecast_runs WHERE request_id=?", (str(data.request_id),)).fetchone()
            if saved and saved["request_payload"] != payload:
                raise HTTPException(409, "This training request ID belongs to another product or source.")
            snapshot = history_snapshot(connection, data.product_id, data.source, today)
            if saved:
                return response_view(connection, snapshot, saved, replayed=True)
        if not snapshot["ready"]:
            raise HTTPException(422, snapshot["reason"])
        # Fit outside a database transaction so sales and payments can continue.
        report = train_report(snapshot)
        with database() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = history_snapshot(connection, data.product_id, data.source, shop_today())
            saved = connection.execute("SELECT * FROM demand_forecast_runs WHERE request_id=?", (str(data.request_id),)).fetchone()
            if saved:
                if saved["request_payload"] != payload:
                    raise HTTPException(409, "This training request ID belongs to another product or source.")
                return response_view(connection, current, saved, replayed=True)
            if current["fingerprint"] != snapshot["fingerprint"] or current["shop_date"] != snapshot["shop_date"]:
                raise HTTPException(409, "Daily history or shop date changed during training. Refresh and train again.")
            stamp = datetime.now(timezone.utc).isoformat()
            connection.execute("""INSERT INTO demand_forecast_runs(request_id,request_payload,product_id,source,data_fingerprint,shop_date,report,created_at)
                VALUES(?,?,?,?,?,?,?,?)""", (str(data.request_id), payload, data.product_id, data.source, snapshot["fingerprint"], snapshot["shop_date"], json.dumps(report, allow_nan=False), stamp))
            saved = connection.execute("SELECT * FROM demand_forecast_runs WHERE request_id=?", (str(data.request_id),)).fetchone()
            return response_view(connection, current, saved)

    return router
