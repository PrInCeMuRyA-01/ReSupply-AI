# ReSupply AI — Easy Start submission notes

**Project name:** ReSupply AI

**Elevator pitch:** Update stock, let AI prepare budget-aware restocking, then approve PayPal Sandbox payment — a simpler purchasing workflow for small shops.

## Inspiration

Small shop owners need a clear next action. Maintaining products, supplier quotes, sales history, forecasts and orders on separate screens can turn a purchasing assistant into more daily work. I wanted the main interaction to be as simple as recording what sold.

## What it does

The owner sets up products, the usual supplier and a spending limit once. A stock update records sales, refreshes demand checks and prepares an unpaid order when stock is low. Eligible historical data is used to train and compare Random Forest with a seven-day mean. The saved auto policy allows current forecast use without repeated training/review buttons. First-day planning uses clearly labelled owner estimates or available sales averages instead of invented training history.

The owner sees the total and explicitly starts PayPal Sandbox checkout. Buyer consent is followed by verified authorization and capture. Goods arrival is confirmed separately, updating inventory once. Existing history imports, supplier comparison, charts, voice queries, incoming dates, Capture/Void and receipt records remain accessible under More tools.

## How I built it

Python, FastAPI, SQLite, scikit-learn, the PayPal Python Server SDK, HTML, CSS and JavaScript. An optional OpenAI Responses API helper extracts a sentence into draft form fields using structured outputs. It is disabled by default and cannot execute writes or payments. ChatGPT/Codex assisted with coding, debugging and documentation.

## What I learned and the challenges

Simplifying a screen is not enough: retries, stale tabs, current order snapshots, incomplete sales data and uncertain payments still need careful handling. I separated estimates from training history, added explicit automation settings, maintained one current unpaid automatic draft, and retained payment reconciliation and atomic receiving. Chronological testing prevents future labels from entering training. Lower measured MAE is not a guaranteed accuracy or profit claim.

## Current scope

A local single-owner prototype. Demo data is synthetic, payments are USD Sandbox tests to one merchant, supplier names are local planning metadata, and full goods receiving is manually confirmed. Real supplier ordering, production payments and proven business savings are future work.
