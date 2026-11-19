import os
import re
import time
import json
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

engine = create_engine(os.getenv("DATABASE_URL"))
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

PRIMARY_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODELS = [PRIMARY_MODEL, "gemini-3.5-flash-lite"]

# In-memory cache storing only successful responses (never caches errors)
_RESPONSE_CACHE: dict[str, dict] = {}

SCHEMA_CONTEXT = """
PostgreSQL Database: tallyx
Current Reference Date (Today): '2026-11-15'

Table 1: sales_invoices (Accounts Receivable / GSTR-1)
- invoice_id (VARCHAR PRIMARY KEY, e.g., 'INV-2026-0001')
- customer_name (VARCHAR)
- customer_gstin (VARCHAR)
- invoice_date (DATE)
- due_date (DATE)
- taxable_amount (NUMERIC(12,2))
- gst_rate (NUMERIC(4,2) — values: 5.00, 12.00, 18.00)
- gst_amount (NUMERIC(12,2))
- total_amount (NUMERIC(12,2))
- payment_status (VARCHAR — exact values: 'PAID', 'PARTIAL', 'UNPAID', 'OVERDUE')
- paid_date (DATE, NULL if unpaid)

Table 2: vendor_bills (Accounts Payable & Input Tax Credit / GSTR-2B)
- bill_id (VARCHAR PRIMARY KEY, e.g., 'BILL-2026-0001')
- vendor_name (VARCHAR)
- vendor_gstin (VARCHAR)
- vendor_invoice_no (VARCHAR)
- bill_date (DATE)
- due_date (DATE)
- taxable_amount (NUMERIC(12,2))
- gst_amount (NUMERIC(12,2))
- total_amount (NUMERIC(12,2))
- itc_eligible (BOOLEAN — TRUE if business can claim Input Tax Credit)
- gstr2b_matched (BOOLEAN — FALSE means vendor failed to file GSTR-1, blocking ITC)
- payment_status (VARCHAR — exact values: 'PAID', 'UNPAID', 'OVERDUE')

Table 3: bank_transactions (Actual Cash Inflows & Outflows)
- txn_id (VARCHAR PRIMARY KEY, e.g., 'TXN-2026-00001')
- txn_date (DATE)
- txn_type (VARCHAR — exact values: 'CREDIT', 'DEBIT')
- payment_mode (VARCHAR — exact values: 'UPI', 'NEFT', 'RTGS', 'IMPS', 'AUTO_DEBIT')
- counterparty (VARCHAR)
- upi_vpa (VARCHAR, nullable)
- narration (TEXT)
- amount (NUMERIC(12,2))
- running_balance (NUMERIC(14,2))
- linked_ref_id (VARCHAR — matches invoice_id for CREDIT or bill_id for DEBIT; NULL for unlinked auto-debits)
"""

SQL_SYSTEM_PROMPT = f"""
You are a senior PostgreSQL Financial Data Engineer for TallyX, an Indian MSME financial copilot.
Translate the user's question into a single, accurate, read-only PostgreSQL query using ONLY the schema below.

{SCHEMA_CONTEXT}

Strict Rules:
1. Output ONLY valid JSON with keys: "sql" (string) and "reasoning" (1-sentence explanation of the query logic).
2. Use ONLY SELECT or WITH (CTE) statements. Never modify data.
3. Always use PostgreSQL syntax (e.g., DATE_TRUNC('month', col), ILIKE for fuzzy name matching, ROUND(..., 2)).
4. Treat '2026-11-15' as CURRENT_DATE whenever the user says "today", "this month", "last month", or "past 30 days".
5. Include clear column aliases and LIMIT 50 unless aggregating.
6. For duplicate payout questions, group bank_transactions WHERE txn_type = 'DEBIT' AND linked_ref_id IS NOT NULL by linked_ref_id, counterparty, amount HAVING COUNT(*) > 1.
"""

SYNTHESIS_SYSTEM_PROMPT = """
You are TallyX AI, a sharp CFO copilot for Indian MSME owners.
Answer the user's question using ONLY the verified SQL query results provided below.

Rules:
1. Never invent, estimate, or extrapolate numbers not present in the query output. If the result is empty, state that clearly.
2. Format currency in Indian Rupees using the ₹ symbol and comma separators (e.g., ₹1,70,206.85 or ₹30.21 Lakh).
3. Lead directly with the key answer in sentence 1, followed by concise bullet points and 1 actionable financial recommendation.
4. Keep the tone crisp, analytical, and free of filler.
"""


def call_gemini_resilient(contents: str, config: types.GenerateContentConfig):
    """Retries transient 503/429 spikes with backoff and fails over across Flash models."""
    last_err = None
    for model_name in FALLBACK_MODELS:
        for attempt in range(3):
            try:
                return client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config,
                )
            except Exception as exc:
                last_err = exc
                err_str = str(exc)
                if "503" in err_str or "429" in err_str or "UNAVAILABLE" in err_str:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                break
    raise last_err


def validate_read_only_sql(sql: str) -> str:
    """Blocks any non-SELECT statements or dangerous SQL keywords."""
    cleaned = sql.strip().rstrip(";")
    upper_sql = cleaned.upper()

    if not (upper_sql.startswith("SELECT") or upper_sql.startswith("WITH")):
        raise ValueError("Security Block: Only SELECT or WITH queries are permitted.")

    forbidden = r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|EXECUTE|COPY)\b"
    if re.search(forbidden, upper_sql):
        raise ValueError("Security Block: Destructive SQL keyword detected.")

    return cleaned


def generate_sql(user_question: str, error_feedback: str = "") -> dict:
    """Calls Gemini (with thinking disabled for low latency) to generate PostgreSQL."""
    prompt = f"User Question: {user_question}"
    if error_feedback:
        prompt += f"\n\nPrevious SQL failed with PostgreSQL error: {error_feedback}. Fix the SQL and return valid JSON."

    response = call_gemini_resilient(
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SQL_SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )
    return json.loads(response.text)


def ask_tallyx(user_question: str) -> dict:
    """
    End-to-end governed NL-to-SQL pipeline with automatic self-healing retry
    and success-only response caching.
    """
    cache_key = user_question.strip().lower()
    if cache_key in _RESPONSE_CACHE:
        return _RESPONSE_CACHE[cache_key]

    error_feedback = ""
    sql_query = ""
    reasoning = ""
    df_result = pd.DataFrame()

    # Step 1 & 2: Generate, validate, and execute SQL (with 1 self-correction retry)
    for attempt in range(2):
        try:
            plan = generate_sql(user_question, error_feedback)
            sql_query = validate_read_only_sql(plan["sql"])
            reasoning = plan.get("reasoning", "")

            with engine.connect() as conn:
                df_result = pd.read_sql(text(sql_query), conn)
            error_feedback = ""
            break
        except Exception as exc:
            error_feedback = str(exc)
            if attempt == 1:
                return {
                    "answer": f"I couldn't safely execute a query for that question. ({error_feedback})",
                    "sql": sql_query,
                    "reasoning": reasoning,
                    "data": pd.DataFrame(),
                    "error": error_feedback,
                }

    # Step 3: Synthesize grounded CFO response from exact SQL rows
    records_preview = df_result.head(25).to_dict(orient="records")
    synthesis_prompt = (
        f"User Question: {user_question}\n\n"
        f"Executed SQL:\n{sql_query}\n\n"
        f"Exact Query Results ({len(df_result)} rows):\n"
        f"{json.dumps(records_preview, default=str, indent=2)}"
    )

    try:
        final_resp = call_gemini_resilient(
            contents=synthesis_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYNTHESIS_SYSTEM_PROMPT,
                temperature=0.2,
            ),
        )
        answer_text = final_resp.text
    except Exception as exc:
        # Fallback if synthesis API spikes: still deliver verified SQL rows cleanly
        answer_text = (
            f"Query executed successfully ({len(df_result)} rows returned), "
            f"though narrative synthesis is temporarily busy ({exc}). Inspect the verified table below."
        )

    result_payload = {
        "answer": answer_text,
        "sql": sql_query,
        "reasoning": reasoning,
        "data": df_result,
        "error": None,
    }

    _RESPONSE_CACHE[cache_key] = result_payload
    return result_payload