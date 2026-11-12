"""PayPal official Server SDK adapter. Sandbox fixed hai; secret server par rahega."""

from hashlib import sha256
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from paypalserversdk.api_helper import APIHelper
from paypalserversdk.configuration import Environment
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.models.order_authorize_request import OrderAuthorizeRequest
from paypalserversdk.models.capture_request import CaptureRequest
from paypalserversdk.models.order_request import OrderRequest
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient


load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)


class PayPalFailure(Exception):
    def __init__(self, message, confirmed=False):
        super().__init__(message)
        self.confirmed = confirmed


def public_config():
    client_id = os.getenv("PAYPAL_SANDBOX_CLIENT_ID", "").strip()
    secret = os.getenv("PAYPAL_SANDBOX_CLIENT_SECRET", "").strip()
    ready = bool(client_id and secret and not client_id.startswith("PASTE_") and not secret.startswith("PASTE_"))
    return {"configured": ready, "client_id": client_id if ready else None,
            "currency": "USD", "intent": "authorize", "environment": "sandbox", "buyer_country": "US"}


def safe_diagnostics(issue, status):
    """Only documented-style issue codes and a hex correlation ID; no raw bodies."""
    parts = [f"PayPal HTTP {status}"] if isinstance(status, int) and 100 <= status <= 599 else []
    values = [getattr(issue, "name", None)]
    details = getattr(issue, "details", None)
    for detail in (details[:5] if isinstance(details, (list, tuple)) else []):
        values.append(detail.get("issue") if isinstance(detail, dict) else getattr(detail, "issue", None))
    for value in values:
        if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", value) and value not in parts:
            parts.append(value)
    debug_id = getattr(issue, "debug_id", None)
    if isinstance(debug_id, str) and re.fullmatch(r"[a-fA-F0-9]{6,32}", debug_id):
        parts.append("Debug ID: " + debug_id)
    return " | ".join(parts)


class SandboxPayPal:
    def __init__(self):
        config = public_config()
        if not config["configured"]:
            raise PayPalFailure("PayPal sandbox setup pending. Fill backend/.env and restart the server.", confirmed=True)
        client_id = config["client_id"]
        self.account_key = sha256(client_id.encode()).hexdigest()
        self.client = PaypalServersdkClient(
            client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
                o_auth_client_id=client_id,
                o_auth_client_secret=os.environ["PAYPAL_SANDBOX_CLIENT_SECRET"].strip(),
            ),
            environment=Environment.SANDBOX,
            timeout=20,
            max_retries=0,
            # Default SDK logging is disabled. Credentials/bodies are never logged here.
        )

    def _call(self, operation, options, allow_empty=False):
        try:
            response = operation(options)
            if allow_empty and response.body is None:
                return {}  # Void normally succeeds with HTTP 204 and no JSON body.
            # Official SDK returns typed models in ApiResponse.body.
            payload = json.loads(APIHelper.json_serialize(response.body))
            if not isinstance(payload, dict):
                raise ValueError("PayPal response is not an object")
            return payload
        except Exception as issue:
            response = getattr(issue, "response", None) or getattr(issue, "http_response", None)
            status = getattr(response, "status_code", None)
            if status == 401:
                message = "PayPal sandbox credentials were rejected. Check Sandbox Client ID/Secret and restart."
            elif status == 403:
                message = "PayPal sandbox account/app does not have permission for this operation. Review the seller account and app settings."
            elif status in (400, 404, 422):
                message = "PayPal rejected this request. Refresh payment status and check the sandbox dashboard."
            else:
                message = "PayPal result could not be confirmed. Refresh payment status before trying again."
            diagnostics = safe_diagnostics(issue, status)
            if diagnostics:
                message += " " + diagnostics
            # Never forward raw exception text, API bodies, tokens or buyer information.
            raise PayPalFailure(message, confirmed=status in (400, 401, 403, 404, 422)) from None

    def create(self, body, request_id):
        return self._call(self.client.orders.create_order, {
            "body": OrderRequest.from_dictionary(body),
            "paypal_request_id": request_id,
            "prefer": "return=representation",
        })

    def get(self, paypal_order_id):
        return self._call(self.client.orders.get_order, {"id": paypal_order_id})

    def authorize(self, paypal_order_id, request_id):
        return self._call(self.client.orders.authorize_order, {
            "id": paypal_order_id,
            "body": OrderAuthorizeRequest(),
            "paypal_request_id": request_id,
            "prefer": "return=representation",
        })

    def get_authorization(self, authorization_id):
        return self._call(self.client.payments.get_authorized_payment, {"authorization_id": authorization_id})

    def capture(self, authorization_id, body, request_id):
        return self._call(self.client.payments.capture_authorized_payment, {
            "authorization_id": authorization_id, "body": CaptureRequest.from_dictionary(body),
            "paypal_request_id": request_id, "prefer": "return=representation",
        })

    def get_capture(self, capture_id):
        return self._call(self.client.payments.get_captured_payment, {"capture_id": capture_id})

    def void(self, authorization_id, request_id):
        return self._call(self.client.payments.void_payment, {
            "authorization_id": authorization_id, "paypal_request_id": request_id,
        }, allow_empty=True)
