# Explain ReSupply AI — Easy Start

## English pitch

Small shop owners should not have to move through several screens to restock. ReSupply AI starts with products, a usual supplier and an order spending limit. After that, the owner records sold units or remaining stock. The app estimates demand, checks delivery timing and budget, and prepares an unpaid order when stock is low. The owner sees the amount and pays through PayPal Sandbox. Goods receipt is confirmed separately and updates stock once.

## Hinglish explanation

Pehli baar product, stock, price, usual supplier aur spending limit save karo. Uske baad sirf batao kitna maal bika ya kitna bacha. App khud demand aur low stock check karega, eligible data par ML train/use karega aur budget mein draft order ready karega. Tum amount dekhkar PayPal payment karoge. Maal milne par Receive confirm karoge; inventory ek baar update hogi.

## Which part is AI?

- Random Forest estimates product demand using previous sales, weekday and recent averages.
- It is tested on later dates and compared with a 7-day mean. RF is selected only when tested MAE is at least 5% lower.
- It requires 56 consecutive eligible same-source days, without stockout flags and ending recently. The app never invents those days.
- Until then an explicitly labelled owner estimate or recorded sales average enables planning.
- Money, supplier selection, budget allocation, draft replacement and payment checks use business rules.
- The optional OpenAI helper extracts one sentence into draft form fields. It never executes stock or payment actions. Existing voice queries still use the defined intent parser.

## Why is the workflow simpler?

Product, supplier, quote and supplier selection are saved together. SKU is generated. Stock reductions are recorded as sales. Daily completion can be authorized once, including a separate opt-in for zero-entry days. Eligible model training and use happen under the saved auto policy. One unpaid draft is maintained; pressing Pay approves the displayed amount and starts the Sandbox checkout. Advanced pages remain available.

## Judge questions

| Question | Answer |
|---|---|
| Does AI spend money by itself? | No. The owner explicitly presses the amount-labelled Pay button and approves buyer checkout. |
| Are all calculations LLM-generated? | No. Exact money, inventory and payment state are controlled by code. The optional LLM fills a draft form. |
| Does it need months of data before it is useful? | Initial owner estimates enable immediate planning. Real ML training has stricter history requirements. |
| Are orders sent to real suppliers? | No. This prototype prepares local order records and pays one Sandbox merchant. |
| Why confirm goods arrival? | A payment does not prove physical delivery. Receiving must update stock once. |
| Have you proved accuracy or savings? | No. Demo data is synthetic; actual shop evaluation is still needed. |
| Is this the previous database? | No. This ZIP creates new files and unique payment namespaces. |
