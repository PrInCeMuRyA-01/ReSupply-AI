# Show the real ML model in the 3-minute video

Prepare the dedicated demo by running START-ML-DEMO.bat. The generated dataset is synthetic and clearly labelled; the training and test computations are real. Keep a quiet screen and use the same order ID through payment and receiving.

| Time | What to show | Simple English narration |
|---|---|---|
| 0:00–0:15 | Demo Home / app name | I am Prince Maurya. ReSupply AI helps shopkeepers restock by updating sales and approving a payment, with less manual planning. |
| 0:15–0:35 | Inventory and Sales history | This isolated demo has three products and ninety completed synthetic sales days per product. Suppliers and prices are already configured. |
| 0:35–0:50 | Home model proof card | These counters come from saved training reports. This is a real model running on labelled sample data. |
| 0:50–1:18 | Show working ML forecast → Blue Pen → Train & forecast | A Random Forest learns from past sales and weekday patterns. I can retrain it here. The chart shows the next seven days; the table compares predictions against later unseen dates. |
| 1:18–1:35 | Both measured errors, selected method; optionally Rice | We compare MAE in units per day with a seven-day mean. Random Forest is selected only when tested error is at least five percent lower. An average can be the better choice for constant demand. |
| 1:35–1:55 | Home → Blue Pen → 1 sold → Save | One stock update triggers demand and budget checks. The draft uses the current reviewed model automatically; I do not manually calculate purchase quantities. |
| 1:55–2:23 | Amount → PayPal buyer checkout → captured status | I check the total and start PayPal Sandbox payment. Buyer consent is followed by verified authorization and capture. Planning cannot pay by itself. |
| 2:23–2:42 | Same order → Goods arrived → Confirm | I simulate goods arriving and confirm the full receipt. Inventory increases once and remains correct after refreshing. |
| 2:42–2:52 | Home / actual public source if ready | ReSupply connects sales, forecasting, purchasing and payment. This prototype uses synthetic demo history, USD and one Sandbox merchant. Thank you. |

Target about 2:50 after editing. Cut password entry and long waits while preserving actual results. Training can be completed before recording; the retrain click is optional if it does not fit the time limit. Do not claim the displayed synthetic-data errors prove real-world accuracy or savings.

## Exact clicks for the ML segment

1. On Home click **Show working ML forecast**. It selects a current Random Forest sample report automatically.
2. Show **ML forecast selected**, the forecast chart and the two MAE values.
3. Optionally click **Train & forecast** to show a real retrain. Wait for results.
4. Expand **Check model quality** to show the chronological test rows.
5. For the average fallback choose **Rice 1 kg**; a zero-error mean is valid and should not be forced to ML.
6. Return to **My shop · Start here** before updating stock. Automatic checking applies the latest current report to the next draft.

Fresh sample stock is Blue Pen 12, Notebook 10 and Rice 24. Reopening never resets received stock or payment history. If repeated rehearsals have raised stock, use a separately extracted fresh source folder for the recording.

## What is actually used?

RandomForestRegressor is the numerical demand model. The optional LLM is only an entry helper and is not required for training, charts, purchasing or this demo. Product prices and exact money arithmetic stay controlled by the application.
