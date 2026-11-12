# ReSupply AI — ML Demo Ready

## Video ke liye bas ye karo

1. ZIP ko **naye `ReSupply-AI-ML-Demo` folder** mein extract karo. Purani app ke upar paste mat karo.
2. **START-ML-DEMO.bat** double-click karo. Python 3.12/3.13 installed hona chahiye. Pehli baar packages install honge.
3. Terminal actual models train karega. Browser automatically **`http://127.0.0.1:8001/demo/`** kholega; port busy ho toh actual URL terminal mein dikhega.
4. Home par **90 days**, **3 current trained reports**, aur Random Forest use karne wale products ka count dekho.
5. **Show working ML forecast** dabao. Blue Pen ka actual 7-day forecast, chart, model error aur average error dikh jayega.
6. Live training record karni ho toh isi page par **Train & forecast** dabao. Data ready hai; CSV/manual history bharne ki zarurat nahi.
7. **My shop · Start here** par wapas aao. Blue Pen select karke **1 sold → Save stock & prepare next step** karo. Current stock 12 se 11 hoga on a fresh copy; purchase quantities automatic update hongi.
8. Amount dekhkar **Pay with PayPal** karo. Apni Sandbox keys aur Personal buyer chahiye. Goods arrival ko manually confirm karke stock receiving dikhao.

## Pehle se kya ready hai?

- 3 products: Blue Pen, A5 Notebook, Rice 1 kg.
- 90 completed synthetic sales days per product — fresh launch par **270 daily totals**.
- 2 suppliers, 6 quotes, selected supplier per product.
- Actual RandomForestRegressor training and chronological testing; metrics hardcoded nahi hain.
- 7-day forecasts, model-vs-average MAE, current reports applied to demo purchasing.
- Demo auto-restock enabled, $100 total limit, $0 shipping/tax, 7-day coverage, 2-day buffer. Settings visible/editable hain.
- Rice par average selected reh sakta hai: jab ML better nahi hai, average use karna correct behaviour hai.

## Database aur dates

Demo data **`backend/resupply-ml-demo.db`** mein first launch par automatically save hota hai. Database binary ZIP mein include nahi hai; bootstrap usko banata hai aur actual model train karta hai.
Main shop **`backend/resupply-easy.db`** mein alag rahegi. Usmein sample data nahi bharta. Purane project ki databases read/import nahi hoti.
Har launch latest completed dates extend karta hai. Existing stock, corrections, orders aur payment holds reset nahi hote. Rehearsal ke baad fresh recording chahiye toh ZIP ko ek aur naye folder mein extract karo; payment databases delete mat karo.

## PayPal setup

Launcher `backend/.env` create karega agar missing ho. Usmein apni existing working Sandbox app ki values paste karo:

```dotenv
PAYPAL_SANDBOX_CLIENT_ID=your_sandbox_client_id
PAYPAL_SANDBOX_CLIENT_SECRET=your_sandbox_client_secret
```

Terminal Ctrl+C se band karke **START-ML-DEMO.bat** dobara chalao. US Sandbox Personal buyer se checkout approve karo. App explicit Pay action ke baad authorize/capture karta hai; startup ya training se payment nahi hoti.
Keys video/GitHub mein show mat karo. This edition's automated payment checks use mocked PayPal; verify one actual Sandbox checkout locally before recording.

## Video mein ML ke liye English line

“This demo uses ninety days of synthetic sales per product. A real Random Forest predicts the next seven days. We test on later dates and compare its error with a seven-day average. The selected forecasts are used automatically in the purchase plan.”

MAE ko units/day mein explain karo. Isko accuracy percentage ya real-shop savings mat bolo. Screen par jo current values hain, wahi bolo.

Full video walkthrough: **docs/ML-DEMO-VIDEO-STEPS.md**.

## VS Code se manually

`backend` terminal mein environment/dependencies ready hone ke baad:

```powershell
.\.venv\Scripts\python.exe run_easy.py --ml-demo
```

Sirf sample data/training prepare karna ho:

```powershell
.\.venv\Scripts\python.exe prepare_ml_demo.py
```

Phir normal server start karke `/demo/` kholo. Existing virtual environment na ho toh neeche manual setup instructions hain.

---

# Optional: empty real shop and advanced manual workflow

**START-RESUPPLY.bat** empty main shop kholta hai. Ye demo launcher se alag entry point hai. Neeche ka original setup empty shop ke liye hai; video demo ke liye upar wale steps follow karo.

# ReSupply AI — Easy Start / Stock Autopilot

## 1. Alag folder mein extract karo

Is ZIP ko **ReSupply-AI-ML-Demo** naam ke naye folder mein extract karo. Purane project ke upar paste mat karo.
Is ZIP mein synthetic sample-data generator aur example CSV hai. Purana user data, saved payments, `.env`, database files aur virtual environment included nahi hain.

- Naya actual database: `backend/resupply-easy.db`
- Naya optional demo database: `backend/resupply-ml-demo.db`
- Ye pehli baar server chalne par bante hain. Purane `resupply.db` / `resupply-demo.db` ko app read ya import nahi karta.
- Har naye database ki alag payment identity banti hai, isliye purane order numbers se invoice collision nahi hoga.

## 2. App start karo

Windows par extracted folder mein **START-RESUPPLY.bat** double-click karo.
Pehli baar internet se Python packages install honge. Python 3.12 ya 3.13 recommended hai.
Browser khud khulega; terminal khula rehne do. Default URL `http://127.0.0.1:8001` hai.
Agar 8001 busy hai toh launcher 8002–8011 mein available port choose karke terminal mein actual URL dikhayega.

VS Code / PowerShell se manually chalana ho, project ROOT se:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe run_easy.py
```

`Copy-Item` sirf tab karo jab `.env` abhi nahi bani. Existing `.env` ko overwrite mat karo.

## 3. Sirf pehli baar shop setup karo

Home page ke **One-time shop setup** mein:

1. Product name, current stock, purchase cost (USD), usual supplier, usually sold/day aur delivery days bharo.
2. **Save product & supplier** dabao. Product code khud banega; supplier, quote aur supplier selection ek saath save honge.
3. Saare products isi tarah add karo.
4. Maximum total/order, confirmed shipping/tax aur stock coverage/buffer set karo.
5. **Enable automatic…** checkbox tick karo aur **Save & turn on auto restock** dabao.

Daily estimate tumhara initial andaaza hai, ML result nahi. Actual confirmed sales milne par wo use hongi.
Daily history automatically save karani ho toh **I record all sales here…** tick karo.
Days without entries ko zero sirf tab count karna jab tum sab sales yahin log karte ho; uske liye separate zero-days checkbox hai.
App opt-in se pehle ki fake history nahi banata. Missing history ko bina permission zero nahi karta.

## 4. Roz sirf stock/sales update karo

Home par **What sold today?** mein product choose karo.

- **Units sold:** aaj kitne pieces bike, wo quantity likho.
- **Stock remaining after sales:** kitne pieces bache hain, wo count likho. Decrease ka difference sale mein record hoga.

**Save stock & prepare next step** dabao.
App khud stock save karega, eligible completed-day totals process karega, demand check karega aur low stock par supplier/budget ke hisaab se unpaid draft ready karega.
56 recent consecutive eligible confirmed days hone par model training, baseline comparison aur forecast use automatically hoga under your saved opt-in.
Usse pehle daily estimate / available sales average se planning chalegi. Train / Preview / Use / Build / Select supplier ko daily dabana zaroori nahi.

Stock sufficient ho toh payment button nahi aayega. Low-stock trigger delivery + buffer ki estimated demand hai; coverage refill size decide karti hai.
Existing approved/held/paid-but-not-received order ko app preserve karta hai. Uski payment clear kiye bina duplicate order prepare nahi karta.

Example: Blue Pen stock **50**, usually sold/day **5**, delivery **2**, coverage **7**, buffer **2**, price **$0.60**.
**35 sold** save karne par stock **15** hoga. Example default settings par **40 pens / $24** ka draft ready ho sakta hai.
Actual result current data, price, budget, incoming stock aur existing orders par depend karega.

## 5. Aakhir mein PayPal payment

`backend/.env` mein apne working Sandbox app ki values bharo:

```dotenv
PAYPAL_SANDBOX_CLIENT_ID=your_sandbox_client_id
PAYPAL_SANDBOX_CLIENT_SECRET=your_sandbox_client_secret
```

Server restart karo. Keys private rakho; browser/UI/GitHub mein paste mat karo.

Home par amount dekho aur **Pay $… with PayPal** dabao. Ye displayed total approve karta hai aur checkout kholta hai.
PayPal button se **US Sandbox Personal buyer** ka checkout approve karo.
Buyer approval ke baad app authorization aur capture complete karega; extra Capture button normal easy flow mein nahi dabana padega.
Koi background payment nahi hoti. Unknown/pending result aaye toh **View order / payment details → Refresh payment status** use karo; naya order bana kar bypass mat karo.

## 6. Maal milne par

Home par **Goods arrived — receive stock → Confirm received stock** karo.
Stock ek baar add hoga. Arrival physical event hai, isliye app usko automatically assume nahi karta.
Delivery ka stock `Stock remaining` field mein dobara add mat karo; receiving button use karo.

## Saare purane features bhi available hain

Sidebar ke **More tools · All features** mein Sales, Sales history/CSV, supplier comparison, detailed AI charts/manual review, purchase planner, voice assistant aur isolated demo guide milenge.
Inventory stock correction, manual order review, separate Capture/Void, incoming dates aur saved receipt ledger bhi available hain.
Auto restock ko pause karke manual workflow use kar sakte ho.

Optional sample data ke liye sidebar ka Demo guide → open isolated demo shop → Prepare use karo. Main shop blank hi rahegi.

## Optional LLM

Automatic restocking ke liye LLM key required nahi hai. Product/sale ka sentence dekar form fill karana ho toh `.env` mein:

```dotenv
OPENAI_ENABLED=true
OPENAI_API_KEY=your_own_openai_api_key
OPENAI_MODEL=gpt-4o-mini
```

Server restart karo. Home ke optional entry helper mein sentence likho, send checkbox tick karo, **Fill form with AI** dabao.
Sirf submitted sentence OpenAI ko jata hai. Form review karke Save tum karoge. LLM payment, SQL ya stock writes execute nahi karta.
Provider API charges apply. Key/error aaye toh normal forms aur automatic restocking phir bhi chalenge.

## Important scope

Local single-owner prototype; USD, one PayPal Sandbox merchant, full-order receiving. Supplier names are local planning metadata.
Automatic drafts are not sent to real suppliers. Real-world savings/accuracy are not established by demo data.
