# Easy Autopilot implementation notes

- `easy_shop.py`: one atomic product/supplier/quote selection; generated SKU; idempotent request receipts; initial owner estimates; optional batch day correction API.
- `easy_autopilot.py`: one-time opt-in policy, stock-delta recording with expected-stock concurrency checks, daily completion since tracking start, eligible model refresh/use, one current auto draft, approval only after the owner presses the amount-labelled payment action.
- `easy_shop_ui.js` and `easy_shop.css`: normal daily workflow is on Home. Original tools are under More tools. `easy_home.html` is the source fragment already embedded in index.html; editing it alone does not alter the running page.
- `easy_llm.py`: optional read-only form extraction via `https://api.openai.com/v1/responses`, `store=false`, strict JSON schema and local Pydantic checks. Only user-submitted text is sent. Provider responses never execute actions. Model access, availability, costs and output correctness depend on the user's API account.
- `main.py`: old inventory/order/payment checks retained. New filenames and per-database payment namespace isolate this edition. The easy Pay action approves the current displayed amount using existing snapshot validation, then enables authorize/capture after buyer consent. The advanced flow remains a separate held-funds path with explicit Capture or Void.
- A stock increase is not evidence of goods receipt. Existing receiving reconciliation remains required and transactional.
- Financial uncertainty is never auto-cleared. Captured/authorized/unknown orders are kept and block duplicate automatic drafting.
- This single-process local prototype serializes easy-mode operations with per-workspace locks. SQLite transactions and core stale checks also reject overlaps with advanced operations. Multiple production workers and external supplier integrations need a separate job/lease architecture.

Official reference used for optional form extraction: https://developers.openai.com/api/docs/guides/structured-outputs
