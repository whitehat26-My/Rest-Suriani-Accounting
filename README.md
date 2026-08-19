# Restoran Suriani — Restaurant Accounting System

An accounting system built for two people who want opposite things from it.

**The owner** is 70, runs the restaurant, and has no interest in bookkeeping. Her
screen has three buttons: **Money In**, **Money Out**, **Count Stock**. She can
also just say what happened — *"Bought RM50 of chicken"* — and photograph the
receipt. She never sees the word "debit".

**The accountant** needs a real ledger. Every one of those taps posts a complete,
balanced double entry, and the system generates a trial balance and the three
primary financial statements from it.

The bridge between them is an event-driven posting engine: the owner records
*what happened in the business*, and one rule per business event turns that into
the correct debits and credits.

---

## Quick start

Two terminals. Python 3.11+ and Node 18+.

### 1. Backend

```bash
cd backend

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Create the tables, load the chart of accounts, and generate 90 days of
# realistic trading so both dashboards have something to show.
python -m app.seed

uvicorn app.main:app --reload --port 8000
```

API on <http://127.0.0.1:8000> · interactive docs on <http://127.0.0.1:8000/docs>

### 2. Frontend

```bash
cd frontend

npm install
npm run dev
```

App on <http://localhost:3000>

- `/` — choose an interface
- `/owner` — Grandma Mode (open it at phone width)
- `/accountant` — Financial Management dashboard

`next.config.mjs` proxies `/api/*` to the backend, so the browser talks to a
single origin and there is no CORS preflight in development.

### Tests

```bash
cd backend && source .venv/bin/activate
pytest                              # 249 tests
```

```bash
cd frontend
npm run build                       # type-checks the whole app
```

### Starting from an empty set of books

`python -m app.seed` refuses to run twice, so to start clean:

```bash
cd backend
rm -f restaurant.db
python -c "from app.seed import ensure_chart_of_accounts; ensure_chart_of_accounts()"
```

That creates the tables and the chart of accounts with no transactions. The
chart of accounts is also created automatically on first startup.

---

## Project structure

```
Rest-Suriani-Accounting/
├── backend/
│   ├── app/
│   │   ├── main.py                  FastAPI app, CORS, router wiring
│   │   ├── config.py                Environment-driven settings
│   │   ├── database.py              Engine, session factory, schema bootstrap
│   │   ├── models.py                ── STEP 1: the database schema
│   │   ├── chart_of_accounts.py     Default accounts + friendly spend categories
│   │   ├── schemas.py               Pydantic request/response models
│   │   ├── serializers.py           ORM → API, incl. the plain-language layer
│   │   ├── seed.py                  Chart bootstrap + 90 days of demo trading
│   │   ├── utils.py                 Reporting-period helpers
│   │   ├── security.py              PIN hashing and signed session tokens
│   │   ├── dependencies.py          The access gates
│   │   ├── services/
│   │   │   ├── ledger.py            ── STEP 2a: the smart posting engine
│   │   │   ├── statements.py        ── STEP 2b: the three statements
│   │   │   ├── inventory.py         Weighted-average costing, COGS, stock counts
│   │   │   ├── payroll.py           Runs, payslips, accrual and payment
│   │   │   ├── payroll_rules.py     EPF, SOCSO and EIS rates in one place
│   │   │   ├── auth.py              Google sign-in, roles, the PIN gate
│   │   │   ├── analysis.py          Ratios, benchmarks, plain-language advice
│   │   │   └── nlp.py               Voice/text sentence parser (EN + Malay)
│   │   └── routers/
│   │       ├── transactions.py      Quick entry, full entry, preview, reverse
│   │       ├── inventory.py         Items, purchases, stock counts, stock card
│   │       ├── payroll.py           Employees, runs, approval, remittances
│   │       ├── auth.py              Sign-in, PIN, roles
│   │       ├── reports.py           P&L, financial position, cash flows, TB
│   │       ├── insights.py          Daily summary, evaluation, dashboard
│   │       ├── accounts.py          Chart of accounts, general ledger
│   │       └── uploads.py           Receipt photos
│   ├── tests/                       149 tests across 5 files
│   ├── requirements.txt
│   └── .env.example
│
└── frontend/
    ├── app/
    │   ├── layout.tsx               Root layout
    │   ├── globals.css              Both themes as CSS custom properties
    │   ├── page.tsx                 Role chooser
    │   ├── owner/page.tsx           ── STEP 3: Grandma Mode
    │   ├── accountant/page.tsx      ── STEP 4: Accountant Mode
    │   └── signin/page.tsx          Google sign-in
    ├── components/
    │   ├── owner/
    │   │   ├── TodayCard.tsx        Today at a glance, traffic-light verdict
    │   │   ├── BigButton.tsx        The oversized primary controls
    │   │   ├── MoneyFlow.tsx        Amount → category → method → confirm
    │   │   ├── NumberPad.tsx        Calculator keypad, not a phone keyboard
    │   │   ├── VoiceInput.tsx       Speech capture + read-back confirmation
    │   │   ├── ReceiptCapture.tsx   Rear-camera photo upload
    │   │   ├── StockSheet.tsx       "Count Stock" with depletion bars
    │   │   ├── WeekChart.tsx        7-day money in/out
    │   │   └── RecentList.tsx       Today's entries, with undo
    │   ├── accountant/
    │   │   ├── charts.tsx           Cash movement, cash position, expenses
    │   │   ├── panels.tsx           Health, ratios, advice, statements, trail
    │   │   └── payroll.tsx          Runs, payslips, statutory remittances
    │   └── auth/
    │       └── PinGate.tsx          The Accountant Mode PIN keypad
    ├── lib/{api,types,format}.ts    Typed client, response types, formatting
    ├── tailwind.config.ts
    └── next.config.mjs
```

---

## How the automation works

### Smart account pairing

The owner sends one shape, whatever she does:

```json
{ "kind": "out", "amount": "50.00", "category": "ingredients", "method": "CASH" }
```

`quick_entry_to_transaction()` in `services/ledger.py` decides this is a
`PURCHASE_INVENTORY_CASH` event. Its posting rule returns:

| Account                      | Debit  | Credit |
| ---------------------------- | -----: | -----: |
| 1200 Inventory — Food & Bev. | 50.00  |        |
| 1000 Cash on Hand            |        | 50.00  |

Buying food debits an **asset**, not an expense — it only becomes Cost of Goods
Sold when the stock is actually used. That distinction is the single most common
error in small-business books, and the owner never has to know it exists.

Change one thing — `"method": "CREDIT"` — and the rule switches to
`PURCHASE_INVENTORY_CREDIT`, crediting Accounts Payable instead of cash. Change
the category to `"wages"` and it becomes `PAY_WAGES`, debiting Salaries & Wages.

Every event type has one rule, and every rule is validated before anything is
written: at least two legs, every amount strictly positive, and total debits
exactly equal to total credits. An unbalanced entry cannot reach the database.

`POST /api/transactions/preview` runs a rule *without saving*, which is how
Accountant Mode explains what the owner's tap did.

### Why the statements always balance

Reporting never asks "is this the chicken account?". It asks each account what
type it is, which statement group it belongs to, and which cash flow section it
feeds. Two consequences:

- **Retained earnings are derived**, not posted — they are the accumulated
  profit implied by every revenue and expense entry to date. The balance sheet
  therefore balances by construction, with no period-close routine.
- **Cash flows are generated generically.** For any balance sheet account other
  than cash, the cash effect of its movement is the negative of that movement
  measured debit-positive. Summing those by section and opening the operating
  section with profit for the period reproduces the standard indirect
  presentation exactly — and always reconciles to the real movement in cash.

Both checks are shown on the face of the dashboard rather than assumed.

### Inventory → Cost of Goods Sold

Stock is held at weighted-average cost. When the owner taps **Count Stock** and
types what she sees, the shortfall against the book figure is what was used:

| Account                      | Debit  | Credit |
| ---------------------------- | -----: | -----: |
| 5000 Cost of Goods Sold      | 60.00  |        |
| 1200 Inventory — Food & Bev. |        | 60.00  |

Spoilage posts to a separate wastage account, so a bad week shows up as waste
rather than quietly inflating food cost. A surplus credits COGS back.

### Voice input

`services/nlp.py` is a deterministic rule-based parser, not a language model. It
reads English and Malay mixed freely, which is how the phrase is actually spoken:

| Spoken | Understood as |
| --- | --- |
| "Bought RM50 of chicken" | out · RM50.00 · ingredients · links to the Chicken stock item |
| "Beli ayam 2 kg RM35 tunai" | out · RM35.00 · ingredients · 2 kg · cash |
| "Jual RM120 tunai" | in · RM120.00 · cash |
| "Bayar gaji pekerja RM800" | out · RM800.00 · wages |

It runs instantly on a cheap phone, costs nothing per use, and behaves
identically every time — which is what makes it trustworthy for someone who
cannot check its working. The parse is always read back as a sentence and
confirmed before anything posts.

### Financial evaluation

`services/analysis.py` grades thirteen ratios against published food-service
benchmarks and writes the conclusion in plain sentences:

| Metric | Healthy |
| --- | --- |
| Food cost / revenue | 28–35% |
| Labour cost / revenue | 25–35% |
| Prime cost (food + labour) | ≤ 65% |
| Rent / revenue | ≤ 10% |
| Current ratio | 1.5–3.0× |
| Net margin | ≥ 5% |
| Wastage / food cost | ≤ 5% |

This is a deterministic expert system, not an LLM. Every number and every
sentence traces to a rule you can read. It returns structured metrics alongside
the prose, so a language-model layer could sit on top later without touching any
of the arithmetic.

---

## Payroll

Payroll is its own section of Accountant Mode and posts into the same ledger as
everything else. A run has three states, and each one does a different job:

| State | What it means |
| --- | --- |
| **Draft** | Freely editable. Nothing has touched the ledger, so a mistake costs nothing and leaves no correcting entry behind. |
| **Approved** | Recognised in the books as one balanced accrual. |
| **Paid** | Take-home pay has left the bank. |

Approving posts a single entry that keeps three different things apart:

| Account | Debit | Credit |
| --- | ---: | ---: |
| 6000 Salaries & Wages | gross | |
| 6010 Employer Statutory Contributions | employer EPF + SOCSO + EIS | |
| 2300 Net Wages Payable | | net pay |
| 2310 / 2320 / 2330 EPF, SOCSO, EIS Payable | | employee + employer |
| 2340 PCB Payable | | tax withheld |

Gross pay is the wage cost. The employee's deductions are **not** a cost - they
are the employee's own money, held briefly before being forwarded. The
employer's contributions **are** an extra cost on top of gross, which is why
they get their own account instead of being buried in wages.

Paying settles only the net wages. Statutory money is remitted separately,
because KWSP, PERKESO and LHDN are each paid on their own schedule and usually
after the staff are. Splitting recognition from payment is what lets a month's
profit statement show that month's true labour cost even when the wages are
handed over in the first week of the next one.

### Statutory contributions

Rates live in `services/payroll_rules.py`, one file with every value named,
because they change. Age and nationality are stored per employee: the EPF rate
changes at 60, and EIS does not cover foreign workers, so neither can be
assumed.

**These are an approximation, deliberately and visibly.** EPF, SOCSO and EIS are
published as banded schedules. This system applies the headline rates against
the wage ceilings and rounds EPF up to the next ringgit, which tracks the
schedules closely but is not identical band for band. That is accurate enough to
run the books and see the true cost of labour; check the figures against the
official schedule before filing a statutory return. The payroll screen says so
too.

### Two things worth knowing

- A monthly salary **prorates** over a partial period. The same calculation
  covers a mid-month run, someone joining and someone leaving.
- If a cash wage was recorded through Grandma Mode's "Worker Pay" button inside
  a run's period, the run **flags it**. That is the one way this module could
  silently count the same wage twice.

---

## Signing in

Identity comes from Google, so there is no password in this system to store,
reset or leak. What is stored is the Google subject id, which survives someone
changing their email address - the address itself does not.

**Roles** decide what you may reach:

| Role | Reaches |
| --- | --- |
| `STAFF` | The daily screen only - record money, count stock |
| `OWNER` | Everything, and can change other people's roles |
| `ACCOUNTANT` | Everything financial |

The first person to sign in becomes the owner, which bootstraps the system
without a default admin password. Everyone after that starts as `STAFF` and has
to be promoted deliberately, so an unexpected sign-in reaches the daily screen
at most - never the books.

**The PIN** is separate from identity, and it is the boundary that actually
matters day to day. The tablet sits unlocked beside the till for a whole shift,
so a valid session says nothing about who is holding it. Opening Accountant Mode
asks for a PIN, and it is mandatory rather than optional: an owner who has never
set one is made to choose one on the way through. An optional gate that defaults
to off is not a gate.

The session lasts 90 days so the owner never meets a login screen; the unlock
lasts 8 hours and can be closed instantly with **Lock**, which leaves the daily
screen signed in.

A four to six digit PIN has at most a million possibilities, so no hash makes it
safe against someone with the database and time. It is stored with PBKDF2 at
600,000 iterations, but the protection that does the real work is the attempt
counter and lockout. Both are used; neither is sufficient alone.

### Setting up Google sign-in

1. In the [Google Cloud console](https://console.cloud.google.com/apis/credentials),
   create an **OAuth 2.0 Client ID** of type *Web application*.
2. Add `http://127.0.0.1:8000/api/auth/google/callback` as an authorised
   redirect URI (and your production URL when you deploy).
3. Put the client ID and secret in `backend/.env`, along with a `SECRET_KEY`.

Until both Google values are set, **the app runs with no accounts and every
endpoint is open**. That is a deliberate trade: an unconfigured install that
refused every request would be unusable rather than secure. It is fine on a
laptop, and the backend logs a warning at startup. Set the credentials before
putting it anywhere other people can reach.

---

## Accessibility

Grandma Mode was built to a specific brief: zero cognitive load for a 70-year-old
in a bright kitchen, often one-handed behind a counter.

- Primary buttons are **128px tall** — far beyond the 44px minimum.
- Nothing below `text-lg`; the headline figure is up to 64px.
- A **calculator keypad** replaces the phone keyboard: twelve targets instead of
  dozens of irrelevant symbols.
- **No accounting vocabulary anywhere.** "Money In", "Money Out", "Count Stock",
  "Food in the store room", "Undo this".
- Colour is never the only signal — every status carries a **glyph and a word**.
- Purely mechanical postings (opening stock, COGS, depreciation) are kept off her
  daily list. She did not trigger them and cannot act on them.
- Every destructive action confirms first; every entry can be undone.
- Zoom is not disabled, focus rings are 3px, and `prefers-reduced-motion` removes
  all animation.

Chart colours were **measured, not chosen**: series hues were validated for
colour-vision-deficiency separation (OKLab ΔE) and contrast against each surface.
Daily flows and the cash balance are separate charts because they share no scale
— a second y-axis would invite a false comparison. Expenses are sorted bars
rather than a donut, because the question is "how much bigger", and length
answers that better than angle. Every chart offers the same numbers as a table.

---

## API reference

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/transactions/quick` | The only write Grandma Mode uses |
| `POST` | `/api/transactions` | Full-control entry (Accountant Mode) |
| `POST` | `/api/transactions/preview` | Show the double entry without saving |
| `POST` | `/api/transactions/parse` | Interpret a spoken sentence |
| `POST` | `/api/transactions/{id}/reverse` | Undo by posting the mirror image |
| `GET` | `/api/transactions` | Paginated history |
| `GET` | `/api/inventory` | Stock with colour bands and days of cover |
| `POST` | `/api/inventory/purchase` | Buy stock, update weighted-average cost |
| `POST` | `/api/inventory/count` | Stock count → COGS or wastage |
| `GET` | `/api/reports/income-statement` | Statement of Profit or Loss |
| `GET` | `/api/reports/balance-sheet` | Statement of Financial Position |
| `GET` | `/api/reports/cash-flow` | Statement of Cash Flows |
| `GET` | `/api/reports/trial-balance` | Proof the ledger is intact |
| `GET` | `/api/insights/daily` | The owner's one-glance summary |
| `GET` | `/api/insights/evaluation` | Ratios, grades and advice |
| `GET` | `/api/insights/dashboard` | Everything Accountant Mode needs |
| `GET` | `/api/accounts/{code}/ledger` | General ledger with running balance |
| `POST` | `/api/uploads` | Receipt photo |
| `GET` | `/api/payroll/overview` | Everything the payroll panel needs |
| `POST` | `/api/payroll/runs` | Open a draft run for every active employee |
| `PATCH` | `/api/payroll/payslips/{id}` | Edit one payslip, recompute the run |
| `POST` | `/api/payroll/runs/{id}/approve` | Post the accrual to the ledger |
| `POST` | `/api/payroll/runs/{id}/pay` | Settle the net wages |
| `POST` | `/api/payroll/remit` | Forward EPF, SOCSO, EIS or PCB |
| `GET` | `/api/auth/status` | Who is signed in, and is the device unlocked |
| `GET` | `/api/auth/google/login` | Start Google sign-in |
| `POST` | `/api/auth/pin/verify` | Unlock Accountant Mode on this device |
| `POST` | `/api/auth/lock` | Close Accountant Mode, stay signed in |

Reporting endpoints accept either explicit `start`/`end` dates or
`period=today|week|month|quarter|year|all`.

---

## Switching to PostgreSQL

SQLite is the default so the prototype needs no setup. Nothing in the code is
SQLite-specific — money is `NUMERIC(14,2)` throughout, never a float.

```bash
# backend/.env
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/restaurant
```

Then `python -m app.seed` as before. For production, put a migration tool
(Alembic) in front of `Base.metadata.create_all`.

---

## Testing

249 tests, covering the things that must never break:

| File | Covers |
| --- | --- |
| `test_ledger.py` | Every event type balances; smart pairing picks the right accounts; reversals restore balances without deleting history |
| `test_statements.py` | Assets = Liabilities + Equity; cash flows reconcile; drawings stay out of profit; interest sits below operating profit |
| `test_inventory.py` | Weighted-average costing; stock counts post to COGS or wastage; depletion bands |
| `test_nlp.py` | Parsing across both languages; a quantity is never mistaken for a price |
| `test_payroll.py` | Contribution rules across age and nationality, proration, the run lifecycle, and the ledger entries it produces |
| `test_auth.py` | Every gate, role assignment, the PIN and its lockout, and token forgery |
| `test_api.py` | The complete owner journey and accountant journey over HTTP |
