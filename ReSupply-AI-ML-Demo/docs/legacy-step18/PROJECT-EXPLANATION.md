# Explain ReSupply AI: English + simple Hinglish

## One-line explanation

**English:** ReSupply AI helps small shop owners turn daily sales into reviewed, budget-aware restocking orders, with PayPal Sandbox payments and recorded stock receipt.

**Hinglish:** ReSupply AI shopkeeper ko batata hai ki kis product ka kitna stock mangwana chahiye, budget mein plan banata hai, aur owner ke review ke baad PayPal Sandbox payment aur stock receiving track karta hai.

## A 30-second pitch

**English:**
Small shops often decide what to buy by checking shelves and guessing tomorrow's sales. ReSupply AI uses recorded sales to estimate demand, combines that estimate with available stock and supplier delivery times, and creates a plan within a budget. The owner reviews the recommendation, approves the order and confirms PayPal Sandbox payment. When goods arrive, receiving updates stock once. Our demo uses clearly labeled synthetic data.

**Hinglish:**
Chhoti shops mein aksar shelf dekhkar aur andaaze se maal mangwaya jata hai. ReSupply AI past sales se demand ka estimate banata hai. Phir current stock, supplier ka delivery time aur budget dekhkar purchasing plan deta hai. Shopkeeper khud plan review aur order approve karta hai. PayPal Sandbox mein test payment hoti hai, aur maal aane par stock ek baar update hota hai. Demo ka data synthetic hai.

## Explain the complete flow

| Stage | English | Hinglish |
| --- | --- | --- |
| Inventory | Add products and current stock. Record sales to reduce stock. | Products aur stock add karo; sale record karoge to stock ghatega. |
| History | Save complete daily totals or preview and import CSV. | Har din ki total sales save karo, ya CSV pehle preview karke import karo. |
| Forecast | Train a product's model; compare RF and average errors. | Model ko past sales se train karo; ML aur average ka error compare hota hai. |
| Owner review | Preview purchase impact and explicitly activate a current forecast. | Dekho forecast se kitna maal mangwana padega; phir khud Use forecast karo. |
| Supplier and budget | Choose a quote, then plan quantities within a product budget. | Supplier quote select karo; budget mein quantities ka plan banao. |
| Draft and approval | Review frozen items, shipping, tax and spending limit. | Draft mein items, total, shipping/tax aur limit check karke approve karo. |
| PayPal | Authorize a test hold, then separately capture or void it. | Pehle test funds hold honge; owner alag se Capture ya Void karega. |
| Receive | Confirm the full goods arrival; inventory increases once. | Maal aane par full receiving confirm karo; stock ek hi baar badhega. |

## Which part is actually AI?

**English:** The demand forecast uses a real Random Forest model. It learns from previous sales and weekday patterns. Stock calculations, supplier prices, money arithmetic, owner approval and payment are coded rules. Browser speech-to-text and a defined intent parser provide voice input. There is no runtime LLM API.

**Hinglish:** Demand predict karne mein actual ML hai: Random Forest. Ye purani sales aur week ke din ka pattern seekhta hai. Stock minus/plus, price, budget calculation, approval aur payment normal code rules se hote hain. Voice mein browser speech ko text banata hai, phir supported command parse hoti hai. App ke andar LLM API call nahi hoti.

## Random Forest in everyday language

**English:** Imagine several small decision trees looking at sales patterns. Their combined estimate is the forecast. Features include yesterday's sales, the same weekday last week and recent averages. The model is tested on later dates it did not train on.

**Hinglish:** Socho kai chhote decision trees sales ka pattern dekh rahe hain. Unke combined estimates se demand forecast banta hai. Model kal ki sales, pichhle hafte isi din ki sales aur recent averages dekhta hai. Test aage ki un dates par hota hai jo training mein nahi thi.

## Why compare with an average?

**English:** A complex model can perform worse than a simple rule on a small dataset. ReSupply selects RF only if its tested MAE is at least 5% lower than the seven-day mean's MAE. Otherwise it uses the mean.

**Hinglish:** Har product par ML better ho, zaroori nahi. Isliye simple 7-day average se comparison hai. Tested MAE kam se kam 5% kam ho tabhi RF select hota hai; warna average select hota hai.

**Illustrative example, not a measured result / Sirf samjhane ka example:**
Actual daily sales are `10, 12, 8` and predictions are `9, 14, 8`.
Absolute errors are `1, 2, 0`; MAE is `(1 + 2 + 0) / 3 = 1 unit/day`.
A baseline MAE of `2` and RF MAE of `1.8` mean a 10% reduction in measured error.
This is not “90% accuracy,” and says nothing by itself about future profit.

Hinglish: Error kitna kam hua, ye bata sakte ho. Usko seedha accuracy percentage ya profit improvement mat bolo.

## Why 56 complete days?

**English:** Several weeks provide repeated weekday patterns plus earlier training and later testing periods. The implementation requires 56 consecutive confirmed same-source days without stockouts. A missing record means unknown sales, not zero.

**Hinglish:** Kai weeks chahiye taki weekday patterns repeat hon aur train/test ke liye dates milein. Is implementation mein 56 continuous confirmed days chahiye. Missing record ka matlab sales pata nahi; usko zero nahi maanenge.

## Demo and actual shop

**English:** `/demo/` uses a different database from the existing shop. It prepares 60 synthetic days per sample product. Its model training is real, but its metrics are only a synthetic-data demonstration. Real-shop performance needs actual history and later unseen evaluation.

**Hinglish:** `/demo/` ka database alag hai. Har sample product ke liye 60 synthetic days milte hain. Training actual ML ki hai, lekin numbers demo data ke hain. Real shop ka performance jaanne ke liye actual sales aur baad ki unseen dates par test chahiye.

## Explain PayPal clearly

| Term | English | Hinglish |
| --- | --- | --- |
| Order approved | The owner agreed to the displayed order. | Shopkeeper ne app mein order aur total approve kiya. |
| PayPal buyer approval | The test buyer approved checkout in PayPal. | Sandbox Personal buyer ne PayPal window mein consent diya. |
| Authorized / held | Test funds are reserved; not yet captured. | Test funds reserve hain; payment abhi capture nahi hui. |
| Captured | The owner confirmed completing the test payment. | Owner ne alag se Capture confirm karke test payment complete ki. |
| Void | Release/cancel an uncaptured test hold. | Capture se pehle hold ko cancel/release karo. |
| Received | The owner confirmed goods arrived; stock was added once. | Owner ne maal aana confirm kiya; stock ek baar add hua. |

**English:** This is a one-merchant USD Sandbox checkout. The named suppliers are local quote metadata. It is not an escrow, split-payment system or production supplier payout service.

**Hinglish:** USD Sandbox payment ek test merchant ko jati hai. Supplier ke naam/quotes app ka local data hain. Ye escrow ya suppliers ko split payout wala production system nahi hai.

## Judge Q&A

| Question | English answer | Hinglish answer |
| --- | --- | --- |
| Who is the user? | Small retailers who manage purchasing and inventory themselves. | Jo chhote shopkeepers apna stock aur purchasing khud manage karte hain. |
| What is innovative here? | The connected sales-to-forecast-to-reviewed-order-to-payment-to-receipt workflow, with explicit uncertainty and source labels. | Sales se forecast, budget, reviewed order, payment aur receiving ek flow mein hain; uncertainty aur demo labels clear hain. |
| Is all of it ML? | No. Demand prediction is ML; purchasing, money and lifecycle controls are rules. | Demand ML se hai; budget aur payment controls coded rules hain. |
| Why no LLM? | Numeric demand forecasting fits a supervised model; a chat model is not required for this task. | Is kaam mein sales numbers ka forecast chahiye, isliye supervised model use kiya. Chat model zaroori nahi. |
| What if RF performs worse? | The mean remains selected and both errors are visible. | Average use hota hai aur dono errors dikhte hain. |
| Can it buy by itself? | No. The owner reviews forecasts, approves orders and confirms payment actions. | Khud se payment nahi karta; owner review, approval aur confirmation zaroori hai. |
| Why PayPal? | It supplies a real Sandbox authorization/capture/void lifecycle for the approved purchase total. | Approved amount ke liye actual Sandbox hold, capture aur void lifecycle milti hai. |
| How do you avoid double receiving? | An atomic stock transaction and unique receipt per order. | Ek transaction mein receipt aur stock update hote hain; same order ki unique receipt dobara stock nahi badhati. |
| Is voice a chatbot? | It supports defined stock, forecast and budget intents, with typed fallback. | Supported stock/forecast/budget commands hain; typed input bhi hai. |
| Did you prove savings? | No. The current demo is synthetic; a real-shop pilot is needed. | Nahi. Abhi demo synthetic hai; savings prove karne ke liye actual shop pilot chahiye. |
| What are the limits? | Local single owner, USD, one merchant, full receiving, no refunds or supplier integration. | Local single owner, USD, ek merchant, full receiving; refunds aur actual supplier integration abhi nahi. |
| What comes next? | Real sales evaluation, authentication, partial delivery and verified payment events. | Real sales test, login/roles, partial delivery aur verified payment events. |

## How to present it

**English:** Start with the user problem. Show one live forecast and its errors. Show the budget and owner review. Show the same order's held, captured and received states. Finish with honest scope and public source. Use the values on your screen rather than memorized invented metrics.

**Hinglish:** Pehle shopkeeper ki problem bolo. Ek live forecast aur errors dikhao. Budget aur owner review dikhao. Same order ka hold, capture aur received state dikhao. Last mein honest scope aur public code batao. Screen ke actual values bolo; numbers invent mat karo.

The [video guide](DEMO-VIDEO-GUIDE.md) supplies the complete timed narration.
