# Judge testing and reproducible setup

## Prerequisites

- Python 3.12 and pip.
- A desktop browser.
- Internet access for dependency installation and actual PayPal Sandbox checkout.
- Your own Sandbox Business app and a separate Sandbox Personal buyer to test payments.
- Node is optional, used only for standalone JavaScript checks.

This source includes `.env.example` placeholders. No payment secrets, buyer passwords or shop databases are public.

## Start a fresh build

Follow [README quick start](../README.md#quick-start-windows--powershell). Run the server from `backend` so its environment file and local databases are in the documented location.

Without Sandbox credentials, inventory, history, real model training and purchasing previews work. Actual authorization/capture/void require the Sandbox configuration.

Health: `GET /health` should return `{"status":"ok"}`.
API docs: `/docs` or scoped `/demo/docs`.

## Complete functional path

1. Visit `/demo/` and open **Demo guide**.
2. **Prepare demo shop + forecasts** creates three sample products, two suppliers, six quotes and 60 complete synthetic days per product, then trains each product's candidate model.
3. For each product, **Review forecast → Preview purchase impact → Use this demo forecast**. Inspect next-seven-day values, historical MAEs, selected method and the synthetic label.
4. Open the $100 product-budget plan. Inspect stock, quantities, selected suppliers, lead times and costs.
5. **Save draft & review**. For the simple test keep shipping/tax `0.00`, set the spending limit to `100.00`, verify the grand total and approve.
6. With your Sandbox app configured, click PayPal and approve with the separate Sandbox Personal buyer.
7. Verify **Test funds held · not captured**. Confirm Capture; verify **Test payment captured · awaiting stock**. Inventory should not yet increase.
8. Simulate delivery and confirm full stock receiving. Inspect receipt before/after stock and then refresh. The same receipt must not add stock a second time.
9. Open the existing shop at `/`. Its records remain independent of demo activity.
10. Try a supported typed assistant query, such as `Blue Pen ka stock kitna hai?`. Voice recognition is optional and browser/service dependent.

Alternate payment path: a separate uncaptured authorized order can be voided and cancelled. Do not attempt to void a captured order.

Preparation preserves existing state. If recorded receives have eliminated restock need, use a separately extracted fresh source folder rather than deleting a database with unresolved payments.

## Offline checks

Run from `backend`:

```powershell
.\.venv\Scripts\python.exe ..\tests\check_paypal.py
.\.venv\Scripts\python.exe ..\tests\check_settlement.py
.\.venv\Scripts\python.exe ..\tests\check_sales_history.py
.\.venv\Scripts\python.exe ..\tests\check_forecast.py
.\.venv\Scripts\python.exe ..\tests\check_forecast_purchasing.py
.\.venv\Scripts\python.exe ..\tests\check_voice.py
.\.venv\Scripts\python.exe ..\tests\check_demo_shop.py
.\.venv\Scripts\python.exe ..\tests\check_pages.py
```

Optional Node UI checks:

```powershell
node ..\tests\check_app_ui.cjs
node ..\tests\check_history_ui.cjs
node ..\tests\check_forecast_ui.cjs
node ..\tests\check_purchasing_ui.cjs
node ..\tests\check_voice_ui.cjs
node ..\tests\check_demo_ui.cjs
node ..\tests\check_navigation_ui.cjs
```

On macOS/Linux, replace the Python executable with `.venv/bin/python` and use slash paths.

## What the checks establish

- Verified inventory/sales transactions, CSV review/import and request retries.
- Real model fitting, chronological validation and mean fallback.
- Forecast review, stale-report handling and purchase projections.
- Sandbox request/amount verification and mocked authorization/capture/void recovery.
- Atomic receiving and duplicate-receipt protection.
- Existing/demo database and invoice isolation, including restart persistence.
- Direct page routes, navigation state, dashboard error states and UI recovery behavior.

Payments are mocked in automated tests. A passing offline suite is not proof of a live Sandbox transaction. Browser layout, actual checkout and microphone recognition should be checked separately on the target machine.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Import/module error | Install all packages from `backend/requirements.txt` into the same Python environment used to launch the server. |
| Forecast not ready | Ensure 56 consecutive confirmed same-source dates without stockout flags; in the demo use Prepare. |
| Forecast not affecting plan | Preview and use the current report; training alone does not activate it. |
| Demo has no purchase quantity | Existing receives may have increased stock. Use a fresh separate extraction for first-run evaluation. |
| PayPal button/config failure | Check Sandbox Client ID/Secret locally and restart. |
| Checkout briefly shows buyer then errors | Use a Sandbox Personal buyer distinct from the merchant; inspect the actual payment status rather than inferring approval from a flashed screen. |
| Result of capture unclear | Refresh payment status first. Do not start a replacement payment while status is unresolved. |
| Microphone unavailable | Type the supported command; voice is optional. |

The app has no user authentication and is designed for a local single-owner prototype. A hosted multi-user deployment would require additional work.
