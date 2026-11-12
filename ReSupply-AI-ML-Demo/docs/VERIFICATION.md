# ML Demo Ready — current verification

- Prepared 90 recent completed days for each of 3 products: 270 labelled synthetic daily totals.
- Fit actual Random Forest regressors and recomputed stored MAE from the chronological test rows. Each model compares predictions on 21 later dates across 3 time splits.
- Blue Pen and A5 Notebook selected Random Forest; Rice selected the 7-day mean because the mean already matched its constant demand.
- Verified that automatic purchase lines reference the current reviewed ML run, rather than an owner estimate.
- Verified safe repeated setup, extension to the next completed date, preserved stock/authorization holds, zero payment calls during preparation, and unchanged main-shop tables.
- Chromium verified the visible 90-day/3-report proof, the actual Train POST with a new saved run ID, the 7-day chart and 21 test rows, stock-to-ML purchase drafting, and mocked PayPal capture. Main shop remained blank. Mobile at 390px had no horizontal overflow or page errors.
- Normal demo, empty-install, page-route, easy-autopilot, forecast and relevant Node navigation/forecast checks passed.

All tests use temporary databases. Payment actions are mocked; no live Sandbox transaction or LLM request was made for this edition. Windows launcher scripts are provided, while the automated checks ran on Linux/Python 3.12. Test your configured Sandbox buyer before recording.

The release includes code, docs, tests and labelled synthetic sample data. It excludes existing user records, credentials, database binaries, recordings, screenshots, bytecode and environments.

---

The previous Easy Start validation is retained below for reference.

# Verification of this edition

- Existing Python checks passed for CSV history, chronological forecasting, forecast purchasing/incoming, page routes, Sandbox SDK adapter/mocked authorization, settlement/receipt rollback, demo isolation and voice parsing.
- New easy workflow checks passed for atomic one-form setup, supplier reuse, owner-estimate planning, stock-only automatic drafts, stale/duplicate requests, preserved paid orders, explicit payment, one receipt, automatic daily totals, current model training/use and mocked LLM output validation.
- Tracking pause/restart checks passed: no zero backfill across untracked dates.
- A fresh backend with an old resupply.db sentinel created two separate empty Easy Start shops and left the old file byte-for-byte unchanged.
- Seven existing Node UI checks passed.
- Actual Chromium desktop/mobile integration passed: setup, stock save, automatic draft, explicit PayPal consent with automatic capture, receiving, refresh persistence, empty separate demo and no JavaScript page errors. No horizontal overflow at 1366px and 390px. Layout screenshots were inspected.

All payment/browser payment checks used a fake PayPal adapter and fake buyer UI. Optional OpenAI responses were mocked. No live Sandbox transaction or live LLM request was made for this edition. Test your own Sandbox buyer/merchant configuration before recording. Windows launcher scripts are provided; the automated checks ran on Linux/Python 3.12.

The ZIP contains source/docs/tests only. It excludes .env, .venv, databases, browser snapshots, logs and bytecode. No existing user records are included.
