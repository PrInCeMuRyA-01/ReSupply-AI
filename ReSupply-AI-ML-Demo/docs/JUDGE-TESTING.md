# Test the Easy Start flow

1. Start the new source with START-RESUPPLY.bat, or run backend/run_easy.py from an installed environment.
2. Main shop begins empty. Add a product with stock 50, USD cost 0.60, usual demand 5/day, supplier delivery 2 days. Save product/supplier.
3. Enable auto restock with a $100 total limit, shipping/tax zero, coverage 7, buffer 2.
4. Record 35 sold. Verify stock 15, a ready unpaid draft, selected supplier and a budgeted quantity. No manual Train/Build/Approve navigation is required.
5. Configure local Sandbox credentials, restart, then press the amount-labelled Pay button and use a US Sandbox Personal buyer. Verify captured/awaiting stock and unchanged inventory.
6. Confirm full goods receipt. Verify stock increases once and remains stable on refresh.
7. Optionally use the separate demo guide to prepare synthetic data; enable its auto policy to demonstrate automatic eligible training/use and detailed charts. The main shop stays separate.

Financial/network errors must be reconciled through View order/payment details; do not reset databases. Existing advanced checks remain available in the tests directory. Browser tests use mocked PayPal only. All fixture data lives in temporary test databases.
