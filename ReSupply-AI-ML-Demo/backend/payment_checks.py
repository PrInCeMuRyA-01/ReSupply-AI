"""Validate server-fetched PayPal resources against one frozen purchase order."""
from datetime import datetime
from decimal import Decimal
import re
from urllib.parse import urlsplit

PAYPAL_ID = re.compile(r"^[A-Z0-9]{1,36}$")


def inspect_order(remote, order, remote_id, version, now, authorization=None, capture=None):
    try:
        def identifier(value):
            if not isinstance(value, str) or not PAYPAL_ID.fullmatch(value):
                raise ValueError()
            return value

        def exact_amount(value):
            number = Decimal(value["value"])
            return value["currency_code"] == "USD" and number.is_finite() and number * 100 == int(order.grand_total * 100)

        def timestamp(value):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError()
            return parsed

        if remote.get("id") != remote_id or remote.get("intent") != "AUTHORIZE":
            raise ValueError()
        units = remote["purchase_units"]
        if len(units) != 1:
            raise ValueError()
        unit = units[0]
        if (unit.get("reference_id") != order.number or unit.get("custom_id") != f"{order.number}-v{version}"
                or not exact_amount(unit["amount"])):
            raise ValueError()
        status = remote.get("status")
        payments = unit.get("payments") or {}
        holds = payments.get("authorizations") or []
        captures = payments.get("captures") or []
        if len(holds) > 1 or len(captures) > 1:
            raise ValueError()  # This milestone makes one full, final capture only.
        hold = holds[0] if holds else None
        cap = captures[0] if captures else None
        if hold:
            identifier(hold["id"])
            if not exact_amount(hold["amount"]):
                raise ValueError()
        if authorization is not None:
            identifier(authorization["id"])
            if hold and authorization["id"] != hold["id"]:
                raise ValueError()
            if not exact_amount(authorization["amount"]):
                raise ValueError()
            hold = authorization
        if cap:
            identifier(cap["id"])
            if not exact_amount(cap["amount"]):
                raise ValueError()
        if capture is not None:
            identifier(capture["id"])
            if cap and capture["id"] != cap["id"]:
                raise ValueError()
            if not exact_amount(capture["amount"]) or capture.get("final_capture") is not True:
                raise ValueError()
            if capture.get("invoice_id") != f"{order.number}-v{version}":
                raise ValueError()
            related = (capture.get("supplementary_data") or {}).get("related_ids") or {}
            if related.get("order_id") and related["order_id"] != remote_id:
                raise ValueError()
            if related.get("authorization_id") and (not hold or related["authorization_id"] != hold["id"]):
                raise ValueError()
            associated = bool(cap and cap["id"] == capture["id"])
            if hold and related.get("authorization_id") == hold["id"]:
                associated = True
            for link in capture.get("links") or []:
                if link.get("rel") == "up":
                    url = urlsplit(link.get("href", ""))
                    # Validate link metadata only. The gateway never follows these
                    # URLs; all actual requests use the fixed Sandbox environment.
                    if (url.scheme != "https" or url.hostname not in ("api-m.sandbox.paypal.com", "api.sandbox.paypal.com", "api-m.paypal.com", "api.paypal.com")
                            or not hold or url.path != f"/v2/payments/authorizations/{hold['id']}"):
                        raise ValueError()
                    associated = True
            if not associated:
                raise ValueError()
            cap = capture
        result = {"paypal_status": status,
                  "message": "Sandbox checkout ready. Approve it in the PayPal window to place a test hold."}
        if hold:
            result["authorization_id"] = hold["id"]
            expires = hold.get("expiration_time")
            result["expires_at"] = expires
            if expires:
                timestamp(expires)
        if cap:
            result.update(capture_id=cap["id"], capture_status=cap.get("status"))
            if cap.get("status") == "COMPLETED":
                if hold and hold.get("status") in ("VOIDED", "EXPIRED", "DENIED"):
                    raise ValueError()
                captured_at = cap.get("create_time") or now.isoformat()
                timestamp(captured_at)
                result.update(state="captured", captured_at=captured_at,
                              message="Sandbox payment captured. Confirm full delivery with Receive full stock; inventory has not changed yet.")
            elif cap.get("status") == "PENDING":
                result.update(state="capture_pending", message="PayPal capture is pending. Refresh payment status; stock receiving and another payment are blocked.")
            elif cap.get("status") in ("DECLINED", "FAILED"):
                result.update(state="capture_denied", message="PayPal declined this capture. Check the sandbox dashboard before taking any further payment action.")
            else:
                raise ValueError()  # Refund/partial-capture processing is not part of this milestone.
        elif hold:
            hold_status = hold.get("status")
            if hold_status == "VOIDED":
                result.update(state="voided", message="PayPal verified that the sandbox authorization hold was released.")
            elif hold_status == "EXPIRED" or (hold_status == "CREATED" and hold.get("expiration_time")
                                              and timestamp(hold["expiration_time"]) <= now):
                result.update(state="expired", message="PayPal authorization has expired. The local order can be cancelled.")
            elif hold_status == "CREATED" and status == "COMPLETED":
                authorized_at = hold.get("create_time") or now.isoformat()
                timestamp(authorized_at)
                result.update(state="authorized", authorized_at=authorized_at,
                              message="Test funds authorized (held). Payment has not been captured; stock is unchanged.")
            elif hold_status == "PENDING":
                result.update(state="authorize_unknown", message="PayPal authorization is pending. Refresh payment status; do not create another payment.")
            elif hold_status == "CAPTURED":
                result.update(state="capture_unknown", message="PayPal reports capture but its capture details are not visible yet. Refresh payment status; do not start another payment.")
            else:
                raise ValueError()
        elif status in ("CREATED", "SAVED", "PAYER_ACTION_REQUIRED", "APPROVED"):
            result["state"] = "ready"
            if status == "APPROVED":
                result["message"] = "Buyer approval received. Retry authorization to confirm the test hold."
        elif status == "VOIDED":
            result.update(state="voided", message="PayPal reports that this checkout was voided. The local order can be cancelled.")
        else:
            raise ValueError()
        return result
    except (ValueError, TypeError, KeyError, ArithmeticError, AttributeError):
        raise ValueError("PayPal details do not match the approved order or contain an unsupported payment state. Check the sandbox dashboard.") from None
