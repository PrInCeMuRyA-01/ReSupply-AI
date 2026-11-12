# English submission copy

Use the sections below for Devpost's matching description fields. Read them before submitting and revise any statement that differs from the final recorded build. Fill links only after publishing; do not submit placeholder URLs.

## Project name

ReSupply AI

## Tagline

A smart purchasing assistant that connects sales forecasts, reviewed budgets, PayPal Sandbox payments and stock receiving for small shops.

## Inspiration

Small shop owners often restock by looking at shelves and estimating what will sell next. Limited cash and supplier delivery delays make it difficult to decide what to buy and when. We wanted to connect daily sales, demand estimates, purchasing and payment in a workflow that a shop owner can understand and control.

## What it does

ReSupply AI records products, stock and sales; accepts confirmed daily history through manual entries or CSV preview/import; and forecasts the next seven days per product.

The app compares a trained Random Forest with a seven-day sales mean through chronological backtests. It uses the forest only when its tested MAE is at least 5% lower; otherwise it retains the mean. A forecast affects purchasing only after explicit owner review.

The planner combines demand, current stock, selected supplier lead times, coverage, buffer and eligible dated incoming stock. It allocates a product budget by urgency and saves an order for review. Shipping, tax and a spending limit are explicit.

After owner approval, the buyer can authorize a PayPal Sandbox hold. The owner separately confirms capture, or voids an uncaptured hold to cancel. When goods are simulated as arriving, full receiving creates a receipt and updates inventory once.

Focused pages provide a coherent shop workflow. Supported Hindi/Hinglish/English voice or typed queries preview stock, forecasts and budgets without approving orders or making payments.

## How we built it

The application uses Python, FastAPI, Pydantic and SQLite. HTML, CSS and vanilla JavaScript provide separate pages served by the same backend.

AI is implemented with scikit-learn's RandomForestRegressor. Features include recent sales lags, rolling means and weekday indicators. Training uses at least 56 consecutive confirmed same-source days without stockout flags. Earlier dates train the model; later dates test its forecast.

PayPal integration uses the official Python Server SDK for Sandbox order creation, authorization, capture, void and status checks. Exact cents and Decimal arithmetic handle money. Persisted request IDs, payment-action records and remote reconciliation support uncertain-result recovery. Stock receiving commits a unique receipt and inventory ledger atomically.

An isolated demo shop creates three products, two suppliers, six quotes and 60 synthetic daily records per product. Its database and PayPal invoice namespace remain separate from the existing shop.

ChatGPT/Codex assisted with coding, debugging and documentation. The running application does not call an LLM API; its demand forecasting uses scikit-learn.

## Challenges

The main challenges were keeping synthetic and actual data separate, testing a time-series forecast without using future labels, connecting reviewed forecasts to date-wise purchasing, and handling the difference between an order approval, a payment hold, a capture and stock receipt.

We also had to preserve request identity across retries and navigation, make uncertain payment results visible, and prevent repeated stock receiving.

## Accomplishments

The prototype connects model training, explicit review, budget planning, an approved order, PayPal Sandbox authorization/capture and a persisted stock receipt.

Its tests fit real models, exercise separate temporary shop databases, and verify payment recovery with mocked PayPal responses. The interface supports separate workflow pages, typed input and editable voice transcripts.

The demonstration is reproducible through source setup instructions and synthetic sample preparation. It does not depend on a hidden production dataset.

## What we learned

A model should earn its place by outperforming a simple baseline on later data. Missing history is different from zero sales, and stockout-limited sales are not full demand.

Financial actions also need clear boundaries. A hold is not a captured payment, payment is not stock receipt, and recommendations should remain reviewable by the owner.

## What's next

Collect actual shop histories and evaluate later unseen dates. Add authentication and roles, partial deliveries, refunds, verified payment events and real supplier integrations. Evaluate business outcomes in a pilot before making savings or stockout-reduction claims.

## Scope and disclosure

- Functional local web prototype; setup is documented for judges.
- USD, PayPal Sandbox and one test merchant.
- Suppliers are quote metadata; no split payouts or production supplier settlement.
- Synthetic demo history and simulated goods arrival; no measured real-shop accuracy or savings claims.
- Manual supplier selection and urgency-based budget allocation.
- Full-order receiving; no partial receipts or refunds.
- Supported intent-based voice/text, not an autonomous purchasing or LLM chat agent.

## Tools used

Python; FastAPI; Pydantic; SQLite; scikit-learn RandomForestRegressor; PayPal Python Server SDK; HTML; CSS; JavaScript; browser speech recognition; ChatGPT/Codex for development assistance.

Optional recording tools should be listed only if actually used: Snipping Tool, OBS or Clipchamp.

## Links to complete after publication

| Submission field | Your final value |
| --- | --- |
| Public source repository | Paste the actual public GitHub URL. |
| Demonstration video | Paste the actual public YouTube URL; under three minutes. |
| Hosted demo | Leave out if not hosted; use README setup and run instructions. |
| Testing instructions | Link to the repository README and `docs/JUDGE-TESTING.md`. |

Suggested category positioning: a reviewed AI purchasing workflow using PayPal. Do not claim a sponsor-specific tool or autonomous-commerce integration that the build does not contain.

Official requirements: [overview](https://paypalaihackathon.devpost.com/) and [rules](https://paypalaihackathon.devpost.com/rules), checked 14 October 2026.
