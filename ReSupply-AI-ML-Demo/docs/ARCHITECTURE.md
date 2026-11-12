# Easy Start architecture

Browser Home → stock update API → durable sale/count transaction → opted-in daily completion → demand check → eligible model train/use → budgeted unpaid draft.

Owner Pay action → existing snapshot/limit approval → Sandbox buyer consent → verified authorization → capture → awaiting stock.

Owner confirms full delivery → existing payment reconciliation → atomic receipt and inventory ledger.

`easy_autopilot.py` coordinates the normal flow. `main.py`, `payment_checks.py`, `paypal_gateway.py`, `sales_history.py`, `demand_forecast.py` and `forecast_purchasing.py` retain the original validated operations. See EASY-AUTOPILOT.md for implementation notes.

The real and demo databases are `resupply-easy.db` and `resupply-ml-demo.db`, relative to backend/main.py. Neither old database filename is opened. There is no automatic data migration or sample seed in the main shop.

The optional OpenAI endpoint receives only a consented sentence. It returns validated form fields. API keys, payment identifiers and the shop catalog are not sent to the model.

The local process is single-owner. Auto checks run on opening or updates; no hosted scheduler or production supplier integration is claimed.
