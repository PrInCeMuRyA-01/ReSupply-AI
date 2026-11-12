# ReSupply AI: record a 2:45 demonstration

This is a storyboard, narration and recording guide. The final MP4 must show the presenter's actual application and Sandbox flow.

**Hinglish:** Script aur timing ready hain. Final video apne computer par actual app chalakar record karo.

## Submission format

The official rules require a public YouTube demonstration shorter than three minutes, plus English materials or English translations. Target **2:45 / 165 seconds** to leave editing margin.

Recommended: the easy English narration below. If you use the equivalent Hinglish narration, include the English caption file and align it with your final audio/edit. Make sure the final narration and on-screen explanations are understandable in English.

Hinglish: English voice sabse simple submission option hai. Hinglish voice rakhoge to English captions lagao. Exact 3:00 mat target karo; 2:45 rakho.

## A. Prepare a clean recording copy

Keep your working app and its payment databases intact. Repeated stock receiving may mean an old demo shop no longer needs purchasing. For a clear first-run demo, extract this source into a **separate** folder such as `ReSupply-AI-Demo-Recording`.

Open the extracted inner folder containing `README.md` and `backend` in VS Code, then:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copy your working Sandbox configuration **locally only**:

```powershell
Copy-Item "C:\Users\Dell\Downloads\ReSupply-AI\backend\.env" .\.env
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8001
```

If the original `.env` does not exist, copy `.env.example` to `.env` and configure your own Sandbox app instead. Never overwrite a working configuration just to follow fresh setup steps.

Open [http://127.0.0.1:8001/demo/](http://127.0.0.1:8001/demo/). Port 8001 keeps this recording copy distinct from the existing server on 8000.

Hinglish: Fresh alag source copy mein apni `.env` sirf locally copy karo. Original app ka database delete/reset mat karo. GitHub clean folder mein ye `.env` nahi jayegi.

Before recording:

1. Open **Demo guide → Prepare demo shop + forecasts** and wait for three current reports.
2. Review all three forecasts with **Preview purchase impact → Use this demo forecast**. Read the synthetic label and real displayed metrics.
3. Rehearse navigation, the budget preview and draft review. For the final take, record a new draft through its actual payment/receipt sequence.
4. Keep shipping/tax at `0.00`, the product budget and spending limit at `100.00`, and verify the grand total is within the limit.
5. Have the working **Sandbox Personal buyer** ready. Sign-in fields/password entry must be removed from the published footage.
6. Use a desktop browser at a readable size, 16:9 capture if possible. Enable Do Not Disturb, close unrelated tabs and do a short microphone test.

Hinglish: Teen forecasts prepare/review kar lo. Navigation aur planner ki practice kar lo. Final take mein ek new order ka actual hold, capture aur receiving record karo. Password typing video se hata dena. Text readable aur mic clear hona chahiye.

Preparation does not reset stock or payments. For a new date, refresh data and review current forecasts again. If a payment result is uncertain, use **Refresh payment status**; do not delete its database or create another payment to hide the unresolved state.

Hinglish: Prepare button reset nahi karta. Payment result unclear ho to status refresh karo; database delete karke ya doosri payment bana kar bypass mat karo.

## B. Record the nine scenes

| Time | Screen | What to show |
| --- | --- | --- |
| 0:00-0:12 | Demo Dashboard | Show the brand, workspace label and dashboard. Introduce the shop-owner problem. |
| 0:12-0:27 | Inventory + Demo guide | Show the three products and prepared history. Keep DEMO / synthetic visible. |
| 0:27-0:57 | AI forecast | Show a current Blue Pen or A5 Notebook report, both MAEs and the chart. Show Preview purchase impact and the owner review. |
| 0:57-1:22 | Purchase planner | Open the $100 budget plan. Show recommended/planned quantities, selected suppliers and product cost. |
| 1:22-1:40 | Order review | Save draft & review. Show shipping/tax 0.00, spending limit 100.00 and the displayed grand total. Approve the order. |
| 1:40-2:03 | PayPal Sandbox + same order | Show buyer approval with login entry cut out. Show held-not-captured status, then Capture test payment and its confirmation. Keep the same order ID. |
| 2:03-2:23 | Receive full stock + receipt | State that arrival is simulated. Receive the same captured order, show stock before/after, then refresh to show the saved receipt. |
| 2:23-2:34 | Voice assistant | Type Blue Pen ka stock kitna hai? and Preview. Use typed input to avoid a microphone-service delay during the main recording. |
| 2:34-2:45 | Dashboard / published GitHub README | Show the running app and, after publishing, the real repository/license. Avoid a long logo outro. |

For the forecast scene, choose a report where the forest was actually selected if available; otherwise explain the fallback exactly as displayed. No fixed accuracy or profit number is required.

Hinglish: Screen par jo method aur error dikhe, wahi bolo. Agar average selected hai to usko honestly explain karo. Fake ML improvement nahi dikhani hai.

For the main flow, show the **same order** throughout approval → hold → capture → receipt. Capture normally happens before the demo receipt; do not describe the prototype as automatically paying after delivery.

Hinglish: Order ID same rehni chahiye. Pehle hold, phir owner-confirmed capture, phir simulated delivery ki receiving dikhani hai.

Void is an alternate path. Mention it if asked, or make a separate short clip using an authorized **uncaptured** order. It is not needed in the 2:45 main flow.

Hinglish: Void alag cancellation flow hai. Captured order par Void nahi hota. Main video mein extra cancellation order dikhana zaroori nahi.

## C. Ready English narration

Read naturally. The script has 265 words; the timeline leaves room for UI actions.

### 0:00-0:12: Problem + introduction

Hi, I'm Prince. ReSupply AI helps small shop owners decide what to restock, stay within a budget, and track purchasing through payment and stock receipt.

### 0:12-0:27: Data and separation

This is an isolated demo shop with three products and sixty synthetic sales days each. Its stock and orders stay separate from the existing shop.

### 0:27-0:57: Meaningful AI

Here, a real Random Forest forecasts daily demand. It learns from recent sales and weekday patterns. We test on later dates and compare against a seven-day mean. We select the forest only when tested error is at least five percent lower. Otherwise, we keep the mean. The owner reviews its purchase impact.

### 0:57-1:22: Budget-aware purchasing

The planner combines demand with stock, supplier lead times, coverage and buffer. This one-hundred-dollar product budget allocates purchases by urgency. Quotes are selected by the owner, and costs use exact cents.

### 1:22-1:40: Owner approval

I save a draft and review its quantities, suppliers and total. Shipping, tax and the spending limit are explicit. Only the owner can approve this order.

### 1:40-2:03: PayPal lifecycle

Now I approve checkout with a Sandbox Personal buyer. The status confirms test funds are held, not captured. I separately confirm Capture. This completes the test payment, while stock remains unchanged until receiving.

### 2:03-2:23: Stock receipt

For this demo, I simulate goods arriving and confirm full receipt. The approved quantities update inventory. The receipt records stock before and after. Refreshing preserves the receipt without adding those units again.

### 2:23-2:34: Accessible query input

The assistant also supports editable voice or typed stock and budget queries. These previews cannot approve orders or pay.

### 2:34-2:45: Honest scope + source

ReSupply connects demand to owner-controlled purchasing. This prototype uses synthetic data, USD and one Sandbox merchant. The runnable source is MIT licensed.

## D. Equivalent Hinglish narration

English captions for this version are supplied in `demo-english.srt`. Adjust their timings to the recording you actually make.

### 0:00-0:12

Hi, main Prince hoon. ReSupply AI chhote shopkeepers ko decide karne mein help karta hai ki kya restock karein, budget mein purchasing kaise karein, aur payment se stock receiving tak kaise track karein.

### 0:12-0:27

Ye alag demo shop hai. Ismein teen products hain aur har product ke sixty synthetic sales days hain. Iska stock aur orders existing shop se alag rehte hain.

### 0:27-0:57

Yahan actual Random Forest daily demand forecast karta hai. Ye recent sales aur weekdays ke patterns seekhta hai. Test baad ki dates par hota hai aur seven-day average se comparison hota hai. Tested error kam se kam five percent kam ho tabhi forest select hota hai. Warna average use hota hai. Owner purchase impact review karta hai.

### 0:57-1:22

Planner demand ke saath stock, supplier delivery time, coverage aur buffer dekhta hai. Is one-hundred-dollar product budget mein urgency ke hisaab se purchases allocate hote hain. Quote owner select karta hai aur cost exact cents mein calculate hoti hai.

### 1:22-1:40

Main draft save karke quantities, suppliers aur total review karta hoon. Shipping, tax aur spending limit clear hain. Ye order sirf owner approve kar sakta hai.

### 1:40-2:03

Ab Sandbox Personal buyer se checkout approve karta hoon. Status confirm karta hai ki test funds hold hain, capture nahi hue. Main alag se Capture confirm karta hoon. Test payment complete hoti hai; receiving tak stock waise hi rehta hai.

### 2:03-2:23

Is demo mein main maal aana simulate karke full receipt confirm karta hoon. Approved quantities inventory mein add hoti hain. Receipt stock before aur after record karti hai. Refresh karne par receipt rehti hai aur wahi units dobara add nahi hoti.

### 2:23-2:34

Assistant editable voice ya typed stock aur budget queries bhi support karta hai. In previews se order approve ya payment nahi hoti.

### 2:34-2:45

ReSupply demand ko owner ke control wali purchasing se jodta hai. Is prototype mein synthetic data, USD aur ek Sandbox merchant use hota hai. Runnable source MIT licensed hai.

## E. Recording and editing

### Windows 11: Snipping Tool

Open **Snipping Tool → Record → New**, choose the screen area containing the browser and checkout popup, then Start. On supported versions, `Win + Shift + R` opens video capture. Stop and save the recording; **Edit in Clipchamp** opens editing.

If recording/microphone controls are unavailable in your installed version, use OBS or record narration separately.

Hinglish: Snipping Tool mein Record/New use karo. Region mein browser aur PayPal popup dono aane chahiye. Mic record nahi ho raha ho to voice alag record karke editor mein add karo.

### OBS alternative

Use the [official OBS download](https://obsproject.com/download). Run its recording configuration wizard, add Display Capture or Window Capture, check the microphone meter, record a 10-second sample and play it back. Display Capture can include the PayPal popup; close sensitive windows first.

Hinglish: OBS mein screen source add karo, mic meter dekho aur pehle chhota sample test karo. Recording ke waqt secret wali VS Code/.env window khuli nahi honi chahiye.

### Edit and export

1. Keep real actions in chronological order. Trim empty waits and credentials entry; label skipped waits, for example **Sandbox login skipped** or **Network wait shortened**.
2. Preserve enough of the actual approval/capture confirmation and result for the transition to be clear.
3. Add the recorded English narration or its Hinglish equivalent. Lower or remove desktop audio so voice is clear.
4. Add readable English captions. The supplied SRT matches the planned 2:45 script; update timings after cuts or wording changes.
5. Use short labels such as **Synthetic demo data**, **Test hold: not captured**, **Capture confirmed** and **Goods arrival simulated**. Do not cover error/total/status fields.
6. Export an MP4 at **1080p**, ideally 16:9. Play it from start to end and confirm total duration is below 3:00.

Hinglish: Login/network waits cut kar sakte ho, par actual payment result ka proof rehna chahiye. English captions lagao. Total 3 minute se kam, voice clear aur screen text readable hona chahiye. Stock arrival ko simulated bolo.

Do not record the PayPal Developer dashboard, `.env`, secrets, passwords, access tokens or personal account information. Use your own recording and voice; no background music is needed.

Hinglish: Credentials aur personal details dikhani nahi hain. Apni screen/voice enough hai; music ki zaroorat nahi.

## F. Publish on YouTube

1. Open [YouTube Studio](https://studio.youtube.com/).
2. **Create → Upload videos** and select the final MP4.
3. Title: **ReSupply AI | Smart Purchasing for Small Shops | PayPal AI Hackathon**
4. Add the English description below and the **actual** public GitHub URL.
5. Answer the audience setting accurately. Complete checks.
6. Set **Visibility → Public** and publish. For this hackathon, Unlisted does not meet the published Public-video requirement.
7. Add English captions: **Subtitles → select video → Add language → English → Add → Upload file → With timing**, then upload the adjusted SRT.
8. Wait for processing, test the video link in an incognito window, confirm captions/audio/duration, and copy the public URL into Devpost and the README.

Hinglish: Studio se MP4 upload karo. Visibility **Public** rakho. English subtitles upload karo aur incognito mein link test karo. Phir actual YouTube link submission mein lagao.

Suggested English description, replace the bracketed URL before posting:

> ReSupply AI helps small shop owners turn daily sales into reviewed restocking orders within a budget.
>
> This demo shows real model training on clearly labeled synthetic history, forecast review, purchasing, PayPal Sandbox authorization and capture, and full stock receiving.
>
> All payments use Sandbox test funds, USD and one merchant. Goods arrival is simulated; synthetic results do not establish real-shop impact.
>
> Public source and setup instructions: [PASTE ACTUAL PUBLIC GITHUB URL]
>
> Built with Python, FastAPI, SQLite, scikit-learn, the PayPal Python Server SDK, HTML, CSS and JavaScript. MIT licensed.

## G. Final playback checklist

- About 2:45; definitely below 3:00.
- English narration or complete readable English translation/captions.
- Actual functioning app, visible synthetic/Sandbox labels.
- Both forecast methods and owner review explained.
- Same order shown through held, captured and received states.
- Password/secret entry removed; real confirmation results retained.
- Public YouTube link and public licensed source work signed out.

Hinglish: Video chhota, clear aur honest rakho. Same order ka end-to-end proof dikhna chahiye. Public links bina login ke khulne chahiye.

Official references, checked 14 October 2026:
[Hackathon rules](https://paypalaihackathon.devpost.com/rules) ·
[Microsoft screen recording](https://support.microsoft.com/en-us/windows/apps/use-snipping-tool-to-capture-screenshots) ·
[OBS quick start](https://obsproject.com/kb/quick-start-guide) ·
[Clipchamp export](https://support.microsoft.com/en-us/clipchamp/exporting-and-saving-a-video-in-clipchamp) ·
[YouTube upload](https://support.google.com/youtube/answer/57407?hl=en) ·
[YouTube captions](https://support.google.com/youtube/answer/2734796?hl=en).
