# Synthetic demo sales

`synthetic_sales_example.csv` contains 270 full-day totals: 90 days for each of Blue Pen, A5 Notebook and Rice 1 kg, ending 26 October 2026. All rows are labelled `demo` and are not actual shop/customer records.

The dedicated launcher does not require CSV import. It generates the latest 90 completed dates automatically in `resupply-ml-demo.db`, using the same reproducible weekday profiles and bounded daily variation as this example. The example CSV is included for inspection; its dates are a snapshot.

Blue Pen and Notebook have weekday patterns plus reproducible variation of -1/0/+1 units. Rice is constant to demonstrate honest average fallback when ML has no measured advantage. No model scores are inserted into this CSV. The actual scikit-learn model is trained and evaluated at launch; stored errors and method choice come from those computations.

Existing demo stock, corrected rows, orders, settings, payment records and namespace survive restarts. New completed dates are appended without overwriting saved totals. Main-shop tables are never seeded by this launcher.
