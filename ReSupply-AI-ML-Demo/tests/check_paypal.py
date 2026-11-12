"""Offline checks: mocked PayPal, real SQLite/FastAPI/SDK models. No payments sent."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import main as code
from paypal_gateway import PayPalFailure, SandboxPayPal, safe_diagnostics
from paypalserversdk.api_helper import APIHelper
from paypalserversdk.models.order import Order
from paypalserversdk.models.order_authorize_response import OrderAuthorizeResponse


async def request(url, method="GET", body=None):
    messages, delivered = [], False
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": b"" if body is None else json.dumps(body).encode(), "more_body": False}
        return {"type": "http.disconnect"}
    async def send(message):
        messages.append(message)
    parts = urlsplit(url)
    await code.app({
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1", "method": method, "scheme": "http", "path": parts.path,
        "raw_path": parts.path.encode(), "query_string": parts.query.encode(),
        "headers": [(b"content-type", b"application/json")], "client": ("127.0.0.1", 123), "server": ("test", 80),
    }, receive, send)
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    raw = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return status, json.loads(raw)


async def ok(url, method="GET", body=None, status=200):
    received, data = await request(url, method, body)
    assert received == status, (url, received, data)
    return data


class FakePayPal:
    account_key = "sandbox-test-app"
    def __init__(self):
        self.remotes, self.keys = {}, {}
        self.creates, self.authorizations, self.gets = [], [], []
        self.lose_create = self.lose_authorize = self.fail_get = self.reject_create = self.unsettled_authorize = False
        self.pending = False
        self.started = self.release = None
        self.get_started = self.get_release = None
    def create(self, body, request_id):
        self.creates.append((deepcopy(body), request_id))
        if self.started:
            self.started.set()
            assert self.release.wait(5), "Test release timeout"
            self.started = None
        if self.reject_create:
            self.reject_create = False
            raise PayPalFailure("Sandbox credentials rejected.", confirmed=True)
        remote_id = self.keys.setdefault(request_id, f"P{len(self.keys)+1:016d}")
        self.remotes.setdefault(remote_id, {**deepcopy(body), "id": remote_id, "status": "CREATED"})
        if self.lose_create:
            self.lose_create = False
            raise PayPalFailure("Create response lost.")
        return {"id": remote_id, "status": "CREATED"}
    def get(self, remote_id):
        self.gets.append(remote_id)
        if self.get_started:
            self.get_started.set()
            assert self.get_release.wait(5), "Test GET release timeout"
            self.get_started = None
        if self.fail_get:
            self.fail_get = False
            raise PayPalFailure("Status response lost.")
        return deepcopy(self.remotes[remote_id])
    def authorize(self, remote_id, request_id):
        self.authorizations.append((remote_id, request_id))
        if self.unsettled_authorize:
            self.unsettled_authorize = False
            raise PayPalFailure("Authorization timed out before its result was visible.")
        remote = self.remotes[remote_id]
        if not remote["purchase_units"][0].get("payments"):
            remote["status"] = "COMPLETED"
            remote["purchase_units"][0]["payments"] = {"authorizations": [{
                "id": "A1234567890123456", "status": "PENDING" if self.pending else "CREATED",
                "amount": deepcopy(remote["purchase_units"][0]["amount"]),
                "create_time": datetime.now(timezone.utc).isoformat(),
                "expiration_time": (datetime.now(timezone.utc) + timedelta(days=29)).isoformat(),
            }]}
        if self.lose_authorize:
            self.lose_authorize = False
            raise PayPalFailure("Authorization response lost.")
        return {"id": remote_id, "status": "COMPLETED"}

    def get_authorization(self, authorization_id):
        for remote in self.remotes.values():
            for hold in remote["purchase_units"][0].get("payments", {}).get("authorizations", []):
                if hold["id"] == authorization_id:
                    return deepcopy(hold)
        raise PayPalFailure("Authorization was not found.", confirmed=True)


async def seed(fake):
    code.SandboxPayPal = lambda: fake
    code.initialize_database()
    await ok("/api/products", "POST", {"sku": "PEN", "name": "Pen", "stock": 20, "unit_cost": "0.90"}, status=201)
    await ok("/api/sales", "POST", {"product_id": 1, "quantity": 3, "request_id": str(uuid4())}, status=201)
    await ok("/api/suppliers", "POST", {"name": "Demo Supplier"}, status=201)
    quote = await ok("/api/products/1/quotes", "PUT", {"supplier_id": 1, "unit_cost": "0.95", "lead_time_days": 2}, status=201)
    await ok("/api/products/1/supplier-selection", "PUT", {"quote_id": quote["id"]})
    receipt = await ok("/api/orders", "POST", {"request_id": str(uuid4()), "budget": "10.00"}, status=201)
    return receipt["order"]


async def approve(order):
    receipt = await ok(f"/api/orders/{order['id']}/approve", "POST", {
        "request_id": str(uuid4()), "expected_version": order["version"],
        "shipping_cost": "0.30", "tax_cost": "0.20", "spending_limit": "10.00",
    })
    return receipt["order"]


def urls(order):
    base = f"/api/orders/{order['id']}"
    return base, base + "/paypal/create", base + "/paypal/authorize", base + "/paypal/sync"


async def scenario(check):
    with tempfile.TemporaryDirectory(prefix="resupply-paypal-") as folder:
        code.DB_PATH = Path(folder) / "resupply.db"
        fake = FakePayPal()
        draft = await seed(fake)
        await check(fake, draft)


async def normal(fake, draft):
    base, create, authorize_url, sync = urls(draft)
    assert (await request(create, "POST", {"expected_version": 1}))[0] == 409
    order = await approve(draft)
    assert order["payment"] is None and order["can_cancel"]
    assert (await request(create, "POST", {"expected_version": 1}))[0] == 409
    assert (await request(create, "POST", {"expected_version": 2, "amount": "0.01"}))[0] == 422
    assert (await request(create, "POST", {"expected_version": True}))[0] == 422
    stock, sales = await ok("/api/products"), await ok("/api/sales")
    await ok("/api/products/1/quotes", "PUT", {"supplier_id": 1, "unit_cost": "1.50", "lead_time_days": 3})
    receipt = await ok(create, "POST", {"expected_version": 2})
    remote_id = receipt["paypal_order_id"]
    body = fake.creates[0][0]
    assert body["intent"] == "AUTHORIZE" and len(body["purchase_units"]) == 1
    unit = body["purchase_units"][0]
    assert unit["amount"]["value"] == "10.00" and unit["amount"]["currency_code"] == "USD"
    assert unit["amount"]["breakdown"] == {
        "item_total": {"currency_code": "USD", "value": "9.50"},
        "shipping": {"currency_code": "USD", "value": "0.30"},
        "tax_total": {"currency_code": "USD", "value": "0.20"},
    }
    assert unit["items"][0]["unit_amount"]["value"] == "0.95"
    await ok(create, "POST", {"expected_version": 2})
    assert len(fake.creates) == 1
    assert (await ok(base))["can_cancel"]  # This button verifies no hold before cancellation.
    assert (await request(authorize_url, "POST", {"paypal_order_id": "FOREIGN123"}))[0] == 409
    assert (await request(authorize_url, "POST", {"paypal_order_id": remote_id}))[0] == 409
    assert not fake.authorizations
    fake.remotes[remote_id]["status"] = "APPROVED"
    paid = await ok(authorize_url, "POST", {"paypal_order_id": remote_id})
    assert paid["status"] == "approved" and paid["payment"]["state"] == "authorized"
    assert paid["payment"]["authorization_id"] and paid["payment"]["amount"] == "10.00"
    assert not paid["can_cancel"]
    assert (await request(base + "/cancel", "POST", {"expected_version": 2}))[0] == 409
    assert "not been captured" in paid["payment"]["message"]
    await ok(authorize_url, "POST", {"paypal_order_id": remote_id})
    assert len(fake.authorizations) == 1
    assert fake.creates[0][1] != fake.authorizations[0][1]
    code.initialize_database()
    assert (await ok(base))["payment"] == paid["payment"]
    assert (await ok("/api/orders"))[0]["payment"] == paid["payment"]
    assert await ok("/api/products") == stock and await ok("/api/sales") == sales
    assert (await request(create, "POST", {"expected_version": 2}))[0] == 409
    authorization = fake.remotes[remote_id]["purchase_units"][0]["payments"]["authorizations"][0]
    authorization["status"] = "VOIDED"
    voided = await ok(sync, "POST")
    assert voided["payment"]["state"] == "voided" and voided["can_cancel"]
    assert (await ok(base + "/cancel", "POST", {"expected_version": 2}))["status"] == "cancelled"
    assert (await request(authorize_url, "POST", {"paypal_order_id": remote_id}))[0] == 409


async def lost_create(fake, draft):
    order = await approve(draft)
    base, create, authorize_url, sync = urls(order)
    fake.lose_create = True
    assert (await request(create, "POST", {"expected_version": 2}))[0] == 502
    assert (await ok(base))["payment"]["state"] == "create_unknown"
    await ok(sync, "POST")  # Status read does not create another checkout.
    assert len(fake.creates) == 1
    receipt = await ok(create, "POST", {"expected_version": 2})
    assert fake.creates[0][1] == fake.creates[1][1] and len(fake.remotes) == 1
    fake.remotes[receipt["paypal_order_id"]]["status"] = "APPROVED"
    fake.lose_authorize = True
    assert (await request(authorize_url, "POST", {"paypal_order_id": receipt["paypal_order_id"]}))[0] == 502
    assert (await ok(base))["payment"]["state"] == "authorize_unknown"
    recovered = await ok(authorize_url, "POST", {"paypal_order_id": receipt["paypal_order_id"]})
    assert recovered["payment"]["state"] == "authorized" and len(fake.authorizations) == 1


async def saved_id(fake, draft):
    order = await approve(draft)
    base, create, _, sync = urls(order)
    fake.fail_get = True
    assert (await request(create, "POST", {"expected_version": 2}))[0] == 502
    assert (await ok(base))["payment"]["paypal_order_id"]
    await ok(create, "POST", {"expected_version": 2})
    assert len(fake.creates) == 1
    fake.account_key = "different-app"
    assert (await request(sync, "POST"))[0] == 409


async def concurrency(fake, draft):
    order = await approve(draft)
    base, create, _, sync = urls(order)
    started, release = threading.Event(), threading.Event()
    fake.started, fake.release = started, release
    pending = asyncio.create_task(request(create, "POST", {"expected_version": 2}))
    assert await asyncio.to_thread(started.wait, 3)
    try:
        assert (await request(create, "POST", {"expected_version": 2}))[0] == 409
        assert (await request(sync, "POST"))[0] == 409
        assert (await request(base + "/cancel", "POST", {"expected_version": 2}))[0] == 409
        # Inventory reads/writes can finish while the remote call is blocked.
        await ok("/api/products/1/stock", "PATCH", {"stock": 18})
    finally:
        release.set()
    assert (await pending)[0] == 200 and len(fake.creates) == 1


async def failed_create(fake, draft):
    order = await approve(draft)
    base, create, _, _ = urls(order)
    fake.reject_create = True
    assert (await request(create, "POST", {"expected_version": 2}))[0] == 502
    assert (await ok(base))["payment"]["state"] == "create_failed"
    assert (await ok(base))["can_cancel"]
    await ok(create, "POST", {"expected_version": 2})
    assert fake.creates[0][1] != fake.creates[1][1]


async def old_unknown(fake, draft):
    order = await approve(draft)
    base, create, _, _ = urls(order)
    fake.lose_create = True
    assert (await request(create, "POST", {"expected_version": 2}))[0] == 502
    with code.database() as connection:
        connection.execute("UPDATE paypal_checkouts SET created_at=?", ((datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat(),))
    assert (await request(create, "POST", {"expected_version": 2}))[0] == 409
    assert len(fake.creates) == 1
    assert (await request(base + "/cancel", "POST", {"expected_version": 2}))[0] == 409


async def pending_authorization(fake, draft):
    order = await approve(draft)
    base, create, authorize_url, sync = urls(order)
    receipt = await ok(create, "POST", {"expected_version": 2})
    remote_id = receipt["paypal_order_id"]
    fake.remotes[remote_id]["status"] = "APPROVED"
    fake.pending = True
    first = await ok(authorize_url, "POST", {"paypal_order_id": remote_id})
    assert first["payment"]["state"] == "authorize_unknown"
    await ok(authorize_url, "POST", {"paypal_order_id": remote_id})
    assert len(fake.authorizations) == 1
    authorization = fake.remotes[remote_id]["purchase_units"][0]["payments"]["authorizations"][0]
    authorization["status"] = "CREATED"
    assert (await ok(sync, "POST"))["payment"]["state"] == "authorized"
    authorization["expiration_time"] = (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    assert (await ok(sync, "POST"))["payment"]["state"] == "expired"
    assert (await ok(base))["can_cancel"]


async def mismatches(fake, draft):
    order = await approve(draft)
    base, create, authorize_url, sync = urls(order)
    receipt = await ok(create, "POST", {"expected_version": 2})
    remote_id = receipt["paypal_order_id"]
    original = deepcopy(fake.remotes[remote_id])
    changes = [
        lambda x: x.update(intent="CAPTURE"),
        lambda x: x["purchase_units"][0]["amount"].update(value="0.01"),
        lambda x: x["purchase_units"][0]["amount"].update(currency_code="EUR"),
        lambda x: x["purchase_units"][0].update(reference_id="RS-999999"),
        lambda x: x["purchase_units"][0].update(custom_id="wrong-version"),
        lambda x: x["purchase_units"][0].update(payments={"captures": [{"status": "COMPLETED"}]}),
    ]
    for change in changes:
        remote = deepcopy(original); change(remote); fake.remotes[remote_id] = remote
        assert (await request(sync, "POST"))[0] == 409
        assert (await ok(base))["payment"]["state"] == "review_required"
        assert not (await ok(base))["can_cancel"]
        assert (await request(base + "/cancel", "POST", {"expected_version": 2}))[0] == 409
        assert (await ok(base))["status"] == "approved"
    assert not fake.authorizations
    fake.remotes[remote_id] = original
    await ok(sync, "POST")
    fake.remotes[remote_id]["status"] = "APPROVED"
    fake.authorize(remote_id, "test-only")
    fake.remotes[remote_id]["purchase_units"][0]["payments"]["authorizations"][0]["amount"]["value"] = "0.01"
    assert (await request(sync, "POST"))[0] == 409
    assert (await ok(base))["payment"]["authorization_id"] is None


async def cancel_unpaid(fake, draft):
    order = await approve(draft)
    base, create, authorization, _ = urls(order)
    before_products, before_sales = await ok("/api/products"), await ok("/api/sales")
    remote_id = (await ok(create, "POST", {"expected_version": 2}))["paypal_order_id"]
    gets = len(fake.gets)
    assert (await request(base + "/cancel", "POST", {"expected_version": 1}))[0] == 409
    assert len(fake.gets) == gets
    saved = await ok(base + "/cancel", "POST", {"expected_version": 2})
    assert saved["status"] == "cancelled" and saved["version"] == 3
    assert saved["payment"]["state"] == "cancelled_unpaid" and not saved["can_cancel"]
    assert fake.remotes[remote_id]["status"] == "CREATED" and not fake.authorizations
    gets = len(fake.gets)
    assert await ok(base + "/cancel", "POST", {"expected_version": 2}) == saved
    assert len(fake.gets) == gets  # Cancellation receipt retry is local/idempotent.
    assert (await request(authorization, "POST", {"paypal_order_id": remote_id}))[0] == 409
    assert len(fake.gets) == gets and not fake.authorizations
    fresh = (await ok("/api/orders", "POST", {"request_id": str(uuid4()), "budget": "10.00"}, status=201))["order"]
    assert fresh["id"] != order["id"] and fresh["number"] != order["number"] and fresh["status"] == "draft"
    assert fresh["items"] == order["items"]
    assert fresh["payment"] is None
    assert await ok("/api/products") == before_products and await ok("/api/sales") == before_sales
    assert len(await ok("/api/orders")) == 2


async def cancel_approved_buyer(fake, draft):
    order = await approve(draft)
    base, create, _, _ = urls(order)
    remote_id = (await ok(create, "POST", {"expected_version": 2}))["paypal_order_id"]
    fake.remotes[remote_id]["status"] = "APPROVED"
    saved = await ok(base + "/cancel", "POST", {"expected_version": 2})
    assert saved["status"] == "cancelled" and saved["payment"]["state"] == "cancelled_unpaid"
    assert fake.remotes[remote_id]["status"] == "APPROVED" and not fake.authorizations


async def cancel_discovers_hold(fake, draft):
    order = await approve(draft)
    base, create, _, sync = urls(order)
    remote_id = (await ok(create, "POST", {"expected_version": 2}))["paypal_order_id"]
    fake.remotes[remote_id]["status"] = "APPROVED"
    fake.authorize(remote_id, "previous-lost-response")
    assert (await ok(base))["payment"]["state"] == "ready"  # Local cache is stale.
    assert (await request(base + "/cancel", "POST", {"expected_version": 2}))[0] == 409
    current = await ok(base)
    assert current["status"] == "approved" and current["version"] == 2
    assert current["payment"]["state"] == "authorized" and not current["can_cancel"]
    assert current["payment"]["authorization_id"] and len(fake.authorizations) == 1
    assert (await request("/api/orders", "POST", {"request_id": str(uuid4()), "budget": "10.00"}))[0] == 409


async def cancel_pending(fake, draft):
    order = await approve(draft)
    base, create, _, _ = urls(order)
    remote_id = (await ok(create, "POST", {"expected_version": 2}))["paypal_order_id"]
    fake.remotes[remote_id]["status"] = "APPROVED"; fake.pending = True
    fake.authorize(remote_id, "previous-pending-response")
    assert (await request(base + "/cancel", "POST", {"expected_version": 2}))[0] == 409
    current = await ok(base)
    assert current["status"] == "approved" and current["payment"]["state"] == "authorize_unknown"
    assert current["payment"]["authorization_id"] and not current["can_cancel"]
    gets = len(fake.gets)
    assert (await request(base + "/cancel", "POST", {"expected_version": 2}))[0] == 409
    assert len(fake.gets) == gets and len(fake.authorizations) == 1


async def cancel_uncertain(fake, draft):
    order = await approve(draft)
    base, create, _, _ = urls(order)
    await ok(create, "POST", {"expected_version": 2})
    fake.fail_get = True
    assert (await request(base + "/cancel", "POST", {"expected_version": 2}))[0] == 502
    current = await ok(base)
    assert current["status"] == "approved" and current["version"] == 2
    with code.database() as connection:
        assert code.checkout_row(connection, order["id"])["operation_token"] is None
    assert (await ok(base + "/cancel", "POST", {"expected_version": 2}))["status"] == "cancelled"


async def cancel_race(fake, draft):
    order = await approve(draft)
    base, create, authorization, _ = urls(order)
    remote_id = (await ok(create, "POST", {"expected_version": 2}))["paypal_order_id"]
    fake.remotes[remote_id]["status"] = "APPROVED"
    started, release = threading.Event(), threading.Event()
    fake.get_started, fake.get_release = started, release
    pending = asyncio.create_task(request(base + "/cancel", "POST", {"expected_version": 2}))
    assert await asyncio.to_thread(started.wait, 3)
    try:
        assert (await request(authorization, "POST", {"paypal_order_id": remote_id}))[0] == 409
        assert (await request(base + "/cancel", "POST", {"expected_version": 2}))[0] == 409
        await ok("/api/products/1/stock", "PATCH", {"stock": 18})  # No DB lock during GET.
    finally:
        release.set()
    assert (await pending)[0] == 200 and not fake.authorizations
    assert (await request(authorization, "POST", {"paypal_order_id": remote_id}))[0] == 409


async def authorization_race(fake, draft):
    order = await approve(draft)
    base, create, authorization, _ = urls(order)
    remote_id = (await ok(create, "POST", {"expected_version": 2}))["paypal_order_id"]
    fake.remotes[remote_id]["status"] = "APPROVED"
    started, release = threading.Event(), threading.Event()
    fake.get_started, fake.get_release = started, release
    pending = asyncio.create_task(request(authorization, "POST", {"paypal_order_id": remote_id}))
    assert await asyncio.to_thread(started.wait, 3)
    try:
        assert (await request(base + "/cancel", "POST", {"expected_version": 2}))[0] == 409
    finally:
        release.set()
    assert (await pending)[0] == 200
    assert (await ok(base))["payment"]["state"] == "authorized"
    assert (await request(base + "/cancel", "POST", {"expected_version": 2}))[0] == 409
    assert len(fake.authorizations) == 1


async def unresolved_authorization(fake, draft):
    order = await approve(draft)
    base, create, authorization, sync = urls(order)
    remote_id = (await ok(create, "POST", {"expected_version": 2}))["paypal_order_id"]
    fake.remotes[remote_id]["status"] = "APPROVED"
    fake.unsettled_authorize = True
    assert (await request(authorization, "POST", {"paypal_order_id": remote_id}))[0] == 502
    # A GET can show APPROVED/no authorization while a previous POST is unresolved.
    current = await ok(sync, "POST")
    assert current["payment"]["state"] == "ready" and current["payment"]["authorization_id"] is None
    assert not current["can_cancel"]
    gets = len(fake.gets)
    assert (await request(base + "/cancel", "POST", {"expected_version": 2}))[0] == 409
    assert len(fake.gets) == gets and (await ok(base))["status"] == "approved"


async def expired_worker_lease(fake, draft):
    order = await approve(draft)
    base, create, authorization, _ = urls(order)
    remote_id = (await ok(create, "POST", {"expected_version": 2}))["paypal_order_id"]
    fake.remotes[remote_id]["status"] = "APPROVED"
    started, release = threading.Event(), threading.Event()
    fake.get_started, fake.get_release = started, release
    pending = asyncio.create_task(request(authorization, "POST", {"paypal_order_id": remote_id}))
    assert await asyncio.to_thread(started.wait, 3)
    try:
        with code.database() as connection:
            connection.execute("UPDATE paypal_checkouts SET operation_started_at=? WHERE order_id=?",
                ((datetime.now(timezone.utc)-timedelta(minutes=4)).isoformat(), order["id"]))
        fake.get_started = None
        cancelled = await ok(base + "/cancel", "POST", {"expected_version": 2})
        assert cancelled["status"] == "cancelled"
    finally:
        release.set()
    assert (await pending)[0] == 409  # Stale worker cannot send its authorization POST.
    assert not fake.authorizations


def sdk_checks():
    with patch.dict(os.environ, {"PAYPAL_SANDBOX_CLIENT_ID": "dummy-sandbox-id", "PAYPAL_SANDBOX_CLIENT_SECRET": "test-secret"}):
        gateway = SandboxPayPal()
        assert gateway.client.config.get_base_uri() == "https://api-m.sandbox.paypal.com"
        assert gateway.client.config.max_retries == 0
        body = {"intent": "AUTHORIZE", "purchase_units": [{"reference_id": "RS-000001", "custom_id": "RS-000001-v2",
            "amount": {"currency_code": "USD", "value": "10.00"}}]}
        options_seen = []
        class Controller:
            def create_order(self, options):
                options_seen.append(options)
                assert json.loads(APIHelper.json_serialize(options["body"])) == body
                return SimpleNamespace(body=Order.from_dictionary({**body, "id": "P123", "status": "CREATED"}))
            def get_order(self, options):
                return SimpleNamespace(body=Order.from_dictionary({**body, "id": options["id"], "status": "APPROVED"}))
            def authorize_order(self, options):
                options_seen.append(options)
                assert json.loads(APIHelper.json_serialize(options["body"])) == {}
                return SimpleNamespace(body=OrderAuthorizeResponse.from_dictionary({"id": options["id"], "status": "COMPLETED"}))
        gateway.client = SimpleNamespace(orders=Controller())
        assert gateway.create(body, "create-key")["id"] == "P123"
        assert gateway.get("P123")["status"] == "APPROVED"
        assert gateway.authorize("P123", "authorize-key")["status"] == "COMPLETED"
        assert options_seen[0]["paypal_request_id"] == "create-key"
        assert options_seen[1]["paypal_request_id"] == "authorize-key"
        def rejected(_):
            issue = Exception("SECRET MUST NOT BE EXPOSED")
            issue.response = SimpleNamespace(status_code=401)
            raise issue
        try:
            gateway._call(rejected, {})
        except PayPalFailure as issue:
            assert issue.confirmed and "credentials" in str(issue) and "SECRET" not in str(issue)
        else:
            raise AssertionError("SDK failure should be sanitized")


async def run():
    real_gateway = code.SandboxPayPal
    sdk_checks()
    with patch.dict(os.environ, {"PAYPAL_SANDBOX_CLIENT_ID": "", "PAYPAL_SANDBOX_CLIENT_SECRET": ""}):
        config = await ok("/api/paypal/config")
        assert not config["configured"] and config["client_id"] is None
        assert config["buyer_country"] == "US" and config["environment"] == "sandbox"
        assert "secret" not in json.dumps(config).lower()
    diagnostics = safe_diagnostics(SimpleNamespace(name="UNPROCESSABLE_ENTITY", debug_id="abc123def4567", details=[
        SimpleNamespace(issue="PAYER_CANNOT_PAY", description="SECRET_TOKEN buyer@example.com"),
        {"issue": "buyer@example.com", "description": "PRIVATE_PASSWORD"},
    ]), 422)
    assert "HTTP 422" in diagnostics and "PAYER_CANNOT_PAY" in diagnostics and "abc123def4567" in diagnostics
    assert not any(value in diagnostics for value in ("SECRET_TOKEN", "buyer@example.com", "PRIVATE_PASSWORD"))
    assert not safe_diagnostics(SimpleNamespace(name="", debug_id="Bearer SECRET_TOKEN", details="SECRET_TOKEN"), None)
    for check in (normal, lost_create, saved_id, concurrency, failed_create, old_unknown, pending_authorization, mismatches,
                  cancel_unpaid, cancel_approved_buyer, cancel_discovers_hold, cancel_pending, cancel_uncertain,
                  cancel_race, authorization_race, unresolved_authorization, expired_worker_lease):
        await scenario(check)
    code.SandboxPayPal = real_gateway
    with patch.dict(os.environ, {"PAYPAL_SANDBOX_CLIENT_ID": "", "PAYPAL_SANDBOX_CLIENT_SECRET": ""}):
        assert (await request("/api/orders/1/paypal/create", "POST", {"expected_version": 2}))[0] == 503
    print("PASS: payment checks, verified unpaid cancellation, hold/pending protection, callback races, fresh saved draft, history and unchanged inventory.")


if __name__ == "__main__":
    asyncio.run(run())
