# Easy Start — English demo, target 2:50

Use the isolated demo shop, not invented actual history. Prepare its sample data before recording, then enable its auto-restock policy. Use one order ID throughout. Keep synthetic/Sandbox labels visible. Use the current values shown on screen.

| Time | Screen/action | Spoken English |
|---|---|---|
| 0:00–0:18 | Home and problem | I am Prince Maurya. ReSupply AI helps small shops restock with less manual work. The owner sets up products, suppliers and spending limits once, then records what sold. |
| 0:18–0:42 | One-time setup, saved sample products | This separate demo shop uses labelled synthetic data. Product setup saves the usual supplier and quote together, and generates a product code. The owner authorizes automatic planning within a spending limit. |
| 0:42–1:05 | Home: record a sold quantity | I enter how many units sold. Stock decreases immediately. The app checks demand and delivery timing, then prepares a low-stock order automatically. I do not have to train a model or build a plan for every sale. |
| 1:05–1:32 | How did AI decide? / detailed forecast | Eligible history is tested chronologically. Random Forest is used only when its tested error is at least five percent lower than the seven-day average. The opted-in workflow trains and uses current forecasts automatically. New shops can start with labelled owner estimates. |
| 1:32–2:06 | Home amount → Pay → actual Sandbox buyer approval | Here is the planned quantity, supplier and total. My Pay action approves this amount. After Sandbox buyer consent, the app authorizes and captures the test payment. Background planning cannot move funds. |
| 2:06–2:28 | Same order: goods arrived, confirm receipt | For this demo, I simulate goods arriving and confirm full receipt. The inventory increases once, and the receipt preserves the before and after counts. |
| 2:28–2:43 | More tools / optional form helper / voice | Advanced supplier comparison, CSV history, forecasting charts, incoming dates, Void and voice queries are retained. An optional LLM can fill draft entry fields from a sentence; the normal workflow works without that key. |
| 2:43–2:50 | Home and real public source link | ReSupply connects stock updates to reviewed purchasing. This is a local prototype using synthetic demo data, USD and one Sandbox merchant. Thank you. |

Record actual working results. Cut password entry and waits, not result failures. Do not call a hold a completed payment. If a capture is uncertain, reconcile before continuing. Do not present mocked automated tests as a real Sandbox transaction.

Fresh real shop URL starts on port 8001; use the link shown by the launcher. Isolated demo is `/demo/`; setup is `/demo/demo-guide`. The old Step 18 storyboard/SRT is archived under legacy-step18 and describes the advanced manual flow.
