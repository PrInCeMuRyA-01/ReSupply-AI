# ReSupply AI — ML Demo Ready

**For the video: double-click `START-ML-DEMO.bat`.** It builds the environment, prepares 90 recent synthetic sales days for each of three products, trains the real scikit-learn models, enables the isolated demo auto policy and opens `/demo/`.

No manual CSV import, data entry, supplier selection or model activation is required for this demo path. Home shows measured model readiness and links directly to the working forecast/chart. The owner still explicitly pays through PayPal Sandbox and confirms receiving.

- Fresh sample dataset: 270 full-day totals, all labelled synthetic/demo.
- Blue Pen/Notebook: weekday demand with reproducible daily variation.
- Rice: constant demand, demonstrating average fallback when ML has no advantage.
- 90-day sample history, chronological backtests and actual MAE calculations; no invented metrics.
- Restart safely extends dates and preserves existing demo progress.
- Main shop stays separate and empty; `START-RESUPPLY.bat` opens it.

See [START-HERE.md](START-HERE.md) and [ML demo video steps](docs/ML-DEMO-VIDEO-STEPS.md).

# ReSupply AI — Easy Start

A local purchasing assistant for small shops. Set products, the usual supplier and a spending limit once. Record sold units or a remaining-stock count; the app checks demand and prepares an unpaid low-stock order. The owner pays explicitly with PayPal Sandbox, then confirms goods receipt.

**Fresh copy:** no existing user records, credentials, payment records or database binaries are included. Labelled synthetic demo data is supplied as a generator and example CSV. This edition creates `backend/resupply-easy.db` and `backend/resupply-ml-demo.db`, separately from the earlier edition. Each database has a durable unique payment namespace.

## Run on Windows

Extract into a **new folder**, then double-click `START-RESUPPLY.bat`. Python 3.12/3.13 is recommended. The launcher builds the local virtual environment, installs dependencies, creates `.env` from the placeholders if absent, and opens the app on an available port starting at 8001.

Full English/Hinglish instructions: [START-HERE.md](START-HERE.md).

Manual development startup, from `backend` after installing `requirements.txt`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8001
```

## Daily workflow

1. Set up products and supplier quotes together. SKU generation is automatic. An owner-entered daily-sales estimate enables first-day planning without invented history.
2. Set the order spending limit, fixed shipping/tax, coverage and safety buffer; explicitly enable automatic preparation and eligible forecast use.
3. Enter sold quantity or remaining stock after sales. Stock decreases are recorded as sales; increases are corrections, not receiving receipts.
4. The app checks recorded demand, delivery, dated incoming supply and budget. It prepares one unpaid draft when stock is low. Fresh unapproved auto drafts can be replaced as quantities change; approved/uncertain/held/captured orders are preserved.
5. Click the amount-labelled PayPal button. That action approves the total. Buyer approval is followed by authorization and capture for this explicit easy payment only. No background payment is made.
6. Confirm full goods arrival to update inventory once.

Automatic checks run when the shop opens, a stock update is saved, or suggestions are refreshed. The local app is not a hosted background service.

## AI and data

Random Forest and chronological comparison with a 7-day mean are retained. At least 56 consecutive confirmed same-source days without stockout flags are required; the latest usable day must be within 7 days. RF is selected only if tested MAE is at least 5% lower. The opt-in auto policy allows training and activating current reports automatically. Manual forecast review remains available after pausing auto mode.

Confirmed full-day records and live sales are separate. Optional automatic daily completion aggregates logged sales from tracking start; no past history is invented. Zero-entry days require separate explicit consent. Pausing/re-enabling tracking or opting into zero days starts a new tracking window so untracked gaps are not backfilled as zero.

The optional OpenAI helper uses the Responses API and strict structured output to fill draft form fields from one submitted sentence. It has no tools, no SQL, no catalog/secret transmission and no write/payment capability. Keys stay in `.env`. It is off by default; automatic restocking works without it.

## Preserved features

All ten page routes remain: dashboard, inventory, sales, sales history with CSV preview/import/export, detailed ML forecasts, suppliers and quotes, manual purchase planner, orders/incoming, voice assistant and demo guide. Advanced Capture/Void, payment reconciliation, full receipts, one-time stock ledger and isolated synthetic demo are retained. Expand **More tools** for these pages. The original Step 18 guides describe that advanced manual workflow; use START-HERE.md for this edition's main flow.

## Setup

- `backend/.env.example`: local Sandbox keys and optional OpenAI configuration.
- FastAPI + SQLite + scikit-learn + PayPal Python Server SDK; HTML/CSS/JavaScript.
- No Node build is needed to run the application.
- Single local owner, USD Sandbox test payments, one merchant, full-order receiving. Supplier quote metadata is not a real supplier integration or split payout.

## Verification

`tests/check_easy_workflow.py` checks fresh databases, quick setup, stock-only automation, stale/duplicate requests, current drafts, mocked payment/receipt, daily totals, auto ML and mocked LLM validation. Existing tests cover chronology, CSV, payment reconciliation, concurrency, Void, rollback, isolation and navigation. Browser smoke testing uses actual Chromium with mocked PayPal; it is not proof of a live Sandbox transaction. Optional LLM network calls are mocked in the automated tests.

Run Python test scripts with project dependencies installed. Node is only needed for optional `.cjs` UI checks. Browser tests additionally require Playwright and an installed Chromium. Never run payment mocks against an actual merchant.

MIT License — Prince Maurya.
