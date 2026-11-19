# TallyX — Zero-Hallucination Financial & GST Copilot for Indian MSMEs

> **Arthaton 2026 Submission** | Built by Bushra Syeda  
> **Live Demo Video:** [Watch the <5-Minute Walkthrough on YouTube](YOUR_YOUTUBE_LINK_HERE)

---

## 1. Problem Statement
Indian MSMEs track sales receivables, vendor purchase bills, and UPI/NEFT bank statements across disconnected exports without dedicated CFOs or full-time auditors. Consequently, silent working-capital leaks—such as **duplicate vendor payouts**, **blocked Input Tax Credit (ITC) from GSTR-2B mismatches**, **creeping NACH auto-debit subscriptions**, and **chronic late-paying B2B buyers**—go unnoticed until a liquidity crunch hits.

Standard LLM chatbots cannot be trusted directly with raw financial ledgers because they frequently hallucinate arithmetic, miscalculate aggregations, and lack audit trails.

---

## 2. What TallyX Does
TallyX pairs a **deterministic PostgreSQL auditing engine** with a **governed Natural-Language-to-SQL AI CFO Copilot** so every rupee figure is 100% database-verified and auditable:

* **Executive Working-Capital Cockpit:** Real-time KPI tracking for Net Cash Balance (`₹78.02 L`), Overdue Receivables (`₹99.00 L` across 118 invoices), Blocked GSTR-2B ITC (`₹1.70 L`), and Monthly Net GST Payable (`₹1.49 L`).
* **Automated Financial Leak Detector:**
  * **Duplicate Vendor Payout Catcher:** Groups bank `DEBIT` entries by invoice reference and amount to flag bills paid twice (uncovering `₹2,15,313.58` in duplicate payouts).
  * **GSTR-2B ITC Reconciliation Auditor:** Identifies suppliers who collected GST (`itc_eligible = TRUE`) but have not filed their GSTR-1 (`gstr2b_matched = FALSE`), ranking vendors by blocked ITC exposure before GSTR-3B filing.
  * **Auto-Debit Creep Monitor:** Uses PostgreSQL window functions (`AVG() OVER`) to flag recurring NACH mandates jumping >20% above their historical baseline (`+44.9%` spike detected).
  * **Customer Receivables Aging Leaderboard:** Ranks overdue B2B accounts by locked cash and average days past due.
* **Governed NL-to-SQL AI CFO Copilot:**
  * Converts plain-English financial questions into read-only PostgreSQL `SELECT` / `WITH` queries grounded in the exact database schema.
  * Enforces strict regex security guardrails blocking `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, and `TRUNCATE`.
  * Features a 1-step self-healing SQL error-recovery loop and an expandable **"Verify Executed SQL & Raw Data"** drawer beneath every response.

---

## 3. System Architecture & Data Pipeline

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                    Streamlit + Plotly Executive UI (app.py)             │
│  ┌──────────────────────────────────┐  ┌─────────────────────────────┐  │
│  │ Deterministic KPI & Leak Cockpit │  │  Governed AI CFO Copilot    │  │
│  └────────────────┬─────────────────┘  └──────────────┬──────────────┘  │
└───────────────────┼───────────────────────────────────┼─────────────────┘
                    │                                   │
                    ▼                                   ▼
┌───────────────────────────────────┐  ┌──────────────────────────────────┐
│   analytics/metrics_engine.py     │  │          ai/copilot.py           │
│ • Pure SQL & Pandas Aggregations  │  │ 1. NL → SQL (Gemini JSON Mode)   │
│ • Duplicate Payout & ITC Audits   │  │ 2. Read-Only Regex Guardrail     │
│ • Window-Function Creep Detection │  │ 3. Self-Healing Retry + Synthesis│
└───────────────────┬───────────────┘  └────────────────┬─────────────────┘
                    │                                   │
                    └─────────────────┬─────────────────┘
                                      ▼
                    ┌───────────────────────────────────┐
                    │   PostgreSQL Database (`tallyx`)  │
                    │  • sales_invoices (GSTR-1 / AR)   │
                    │  • vendor_bills (GSTR-2B / AP)    │
                    │  • bank_transactions (UPI/NEFT)   │
                    └───────────────────────────────────┘
```

---

## 4. AI Models, APIs & Tech Stack
* **Primary LLM Model:** `gemini-3.8-flash` (used for schema-grounded SQL query generation and CFO narrative synthesis).
* **Failover LLM Model:** `gemini-3.5-flash-lite` (automatic fallback with exponential backoff for high-availability resilience).
* **AI SDK:** Official `google-genai` Python SDK (`GenerateContentConfig` with structured JSON output for deterministic SQL extraction).
* **Database:** PostgreSQL (`tallyx`) using strict `NUMERIC(12,2)` fixed-point decimal arithmetic, `CHECK` constraints, and relational indexes.
* **Backend & Data Engineering:** Python, SQLAlchemy, Psycopg2, Pandas, NumPy, Faker (`en_IN` synthetic Indian GSTIN & UPI ledger generator).
* **Frontend & Visualization:** Streamlit and Plotly.

---

## 5. Project Structure

```text
tallyx/
├── ai/
│   ├── __init__.py
│   └── copilot.py           # Governed NL-to-SQL pipeline, guardrails & failover
├── analytics/
│   ├── __init__.py
│   └── metrics_engine.py    # Deterministic SQL & Pandas financial audit engine
├── db/
│   └── schema.sql           # PostgreSQL DDL schema with constraints & comments
├── scripts/
│   └── seed_data.py         # Synthetic Indian MSME dataset & anomaly generator
├── app.py                   # Streamlit + Plotly executive dashboard & chat UI
├── .env.example             # Environment variable template
├── .gitignore               # Excludes .env and local cache files
├── requirements.txt         # Python dependencies
└── README.md                # Project documentation
```

---

## 6. How to Run Locally

### Prerequisites
* Python 3.10+
* PostgreSQL 14+ running locally

### Step-by-Step Setup
1. **Clone the repository:**
   ```bash
   git clone [https://github.com/YOUR_USERNAME/tallyx.git](https://github.com/YOUR_USERNAME/tallyx.git)
   cd tallyx
   ```

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create the PostgreSQL database & schema:**
   * Create a database named `tallyx` in pgAdmin or `psql`:
```sql
CREATE DATABASE tallyx;
```
   * Run `db/schema.sql` inside the `tallyx` database to create `sales_invoices`, `vendor_bills`, and `bank_transactions`.

4. **Configure environment variables:**
   * Copy `.env.example` to `.env` and fill in your local PostgreSQL credentials and Google AI Studio API key:
```env
DATABASE_URL=postgresql+psycopg2://postgres:your_postgres_password@localhost:5432/tallyx
GEMINI_API_KEY=your_google_ai_studio_api_key_here
GEMINI_MODEL=gemini-3.8-flash
```

5. **Seed the synthetic Indian MSME dataset (1,604 records + planted anomalies):**
   ```bash
   python scripts/seed_data.py
   ```

6. **Launch the TallyX dashboard:**
   ```bash
   streamlit run app.py
   ```
   Open `http://localhost:8501` in your browser.

---

## 7. Sample CFO Questions to Test
* *"Which vendors have unmatched GSTR-2B bills and how much ITC is blocked per vendor?"*
* *"Which overdue customer invoices can cover our November 2026 net GST liability?"*
* *"Show me any vendor bills that were paid twice in our bank ledger."*
* *"Compare Vayu Cloud Hosting India's auto-debit charges over the last 6 months."*
* *"Delete all overdue invoices for Metro Fresh Distributors."* *(Tests read-only SQL security guardrail)*