import os
from datetime import date
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))

# Anchor date matching our synthetic dataset's current date
AS_OF_DATE = date(2026, 11, 15)


def get_executive_kpis() -> dict:
    """Computes core cash position, receivables, payables, and net GST exposure."""
    with engine.connect() as conn:
        # 1. Latest Cash Balance
        cash_bal = conn.execute(text("""
            SELECT running_balance
            FROM bank_transactions
            ORDER BY txn_date DESC, txn_id DESC
            LIMIT 1;
        """)).scalar() or 0.0

        # 2. Accounts Receivable (Unpaid + Overdue)
        ar_row = conn.execute(text("""
            SELECT
                COALESCE(SUM(total_amount), 0) AS total_ar,
                COALESCE(SUM(CASE WHEN payment_status = 'OVERDUE' THEN total_amount ELSE 0 END), 0) AS overdue_ar,
                COUNT(CASE WHEN payment_status = 'OVERDUE' THEN 1 END) AS overdue_inv_count
            FROM sales_invoices
            WHERE payment_status IN ('UNPAID', 'OVERDUE', 'PARTIAL');
        """)).mappings().first()

        # 3. Accounts Payable & At-Risk ITC
        ap_row = conn.execute(text("""
            SELECT
                COALESCE(SUM(CASE WHEN payment_status IN ('UNPAID', 'OVERDUE') THEN total_amount ELSE 0 END), 0) AS total_ap,
                COALESCE(SUM(CASE WHEN itc_eligible = TRUE AND gstr2b_matched = FALSE THEN gst_amount ELSE 0 END), 0) AS blocked_itc
            FROM vendor_bills;
        """)).mappings().first()

        # 4. Current Month GST Liability (Output GST collected/billed vs Valid GSTR-2B ITC)
        gst_row = conn.execute(text("""
            SELECT
                (SELECT COALESCE(SUM(gst_amount), 0) FROM sales_invoices
                 WHERE DATE_TRUNC('month', invoice_date) = DATE_TRUNC('month', CAST(:as_of AS DATE))) AS output_gst,
                (SELECT COALESCE(SUM(gst_amount), 0) FROM vendor_bills
                 WHERE DATE_TRUNC('month', bill_date) = DATE_TRUNC('month', CAST(:as_of AS DATE))
                   AND itc_eligible = TRUE AND gstr2b_matched = TRUE) AS valid_itc
        """), {"as_of": AS_OF_DATE}).mappings().first()

        # 5. 30-Day Cash Runway Estimation (Avg daily net burn over last 90 days)
        burn_row = conn.execute(text("""
            SELECT
                COALESCE(SUM(CASE WHEN txn_type = 'DEBIT' THEN amount ELSE 0 END), 0) AS total_outflow,
                COALESCE(SUM(CASE WHEN txn_type = 'CREDIT' THEN amount ELSE 0 END), 0) AS total_inflow
            FROM bank_transactions
            WHERE txn_date >= CAST(:as_of AS DATE) - INTERVAL '90 days';
        """), {"as_of": AS_OF_DATE}).mappings().first()

    net_90d = float(burn_row["total_inflow"]) - float(burn_row["total_outflow"])
    daily_net = net_90d / 90.0
    runway_days = "Cash-Flow Positive" if daily_net >= 0 else f"{int(float(cash_bal) / abs(daily_net))} days"

    net_gst_payable = max(0.0, float(gst_row["output_gst"]) - float(gst_row["valid_itc"]))

    return {
        "current_cash_balance": round(float(cash_bal), 2),
        "total_receivables": round(float(ar_row["total_ar"]), 2),
        "overdue_receivables": round(float(ar_row["overdue_ar"]), 2),
        "overdue_invoice_count": int(ar_row["overdue_inv_count"]),
        "total_payables": round(float(ap_row["total_ap"]), 2),
        "blocked_itc_risk": round(float(ap_row["blocked_itc"]), 2),
        "current_month_net_gst": round(net_gst_payable, 2),
        "runway_status": runway_days,
    }


def detect_duplicate_payouts() -> pd.DataFrame:
    """Flags vendor bills paid more than once in the bank ledger."""
    query = """
        SELECT
            linked_ref_id AS bill_id,
            counterparty AS vendor_name,
            amount AS duplicate_amount,
            COUNT(*) AS times_paid,
            MIN(txn_date) AS first_paid_date,
            MAX(txn_date) AS duplicate_paid_date,
            STRING_AGG(txn_id, ', ' ORDER BY txn_date) AS txn_ids
        FROM bank_transactions
        WHERE txn_type = 'DEBIT'
          AND linked_ref_id IS NOT NULL
        GROUP BY linked_ref_id, counterparty, amount
        HAVING COUNT(*) > 1
        ORDER BY duplicate_amount DESC;
    """
    return pd.read_sql(query, engine)


def detect_itc_mismatches() -> pd.DataFrame:
    """Groups GSTR-2B unmatched bills by vendor so MSMEs know whom to chase before filing GSTR-3B."""
    query = """
        SELECT
            vendor_name,
            vendor_gstin,
            COUNT(*) AS unmatched_bills,
            SUM(taxable_amount) AS total_taxable_value,
            SUM(gst_amount) AS itc_at_risk
        FROM vendor_bills
        WHERE itc_eligible = TRUE
          AND gstr2b_matched = FALSE
        GROUP BY vendor_name, vendor_gstin
        ORDER BY itc_at_risk DESC;
    """
    return pd.read_sql(query, engine)


def detect_auto_debit_creep() -> pd.DataFrame:
    """Detects recurring NACH/AUTO_DEBIT mandates that jumped >20% compared to historical average."""
    query = """
        WITH mandate_history AS (
            SELECT
                counterparty,
                narration,
                txn_date,
                amount,
                AVG(amount) OVER (
                    PARTITION BY counterparty, narration
                    ORDER BY txn_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) AS prev_avg_amount
            FROM bank_transactions
            WHERE payment_mode = 'AUTO_DEBIT'
        )
        SELECT
            counterparty,
            narration,
            txn_date AS spike_date,
            ROUND(prev_avg_amount, 2) AS historical_avg,
            amount AS latest_amount,
            ROUND(((amount - prev_avg_amount) / prev_avg_amount) * 100, 1) AS pct_increase
        FROM mandate_history
        WHERE prev_avg_amount IS NOT NULL
          AND amount > prev_avg_amount * 1.20
        ORDER BY txn_date DESC;
    """
    return pd.read_sql(query, engine)


def get_customer_aging_risk() -> pd.DataFrame:
    """Ranks customers by overdue receivables and average days past due."""
    query = text("""
        SELECT
            customer_name,
            COUNT(*) AS overdue_invoices,
            SUM(total_amount) AS overdue_amount,
            ROUND(AVG(CAST(:as_of AS DATE) - due_date), 0) AS avg_days_overdue
        FROM sales_invoices
        WHERE payment_status = 'OVERDUE'
        GROUP BY customer_name
        ORDER BY overdue_amount DESC;
    """)
    return pd.read_sql(query, engine, params={"as_of": AS_OF_DATE})


def get_monthly_cashflow_series() -> pd.DataFrame:
    """Returns monthly inflows, outflows, and net cash flow for time-series charting."""
    query = """
        SELECT
            TO_CHAR(DATE_TRUNC('month', txn_date), 'YYYY-MM') AS month,
            SUM(CASE WHEN txn_type = 'CREDIT' THEN amount ELSE 0 END) AS cash_inflow,
            SUM(CASE WHEN txn_type = 'DEBIT' THEN amount ELSE 0 END) AS cash_outflow,
            SUM(CASE WHEN txn_type = 'CREDIT' THEN amount ELSE -amount END) AS net_cashflow
        FROM bank_transactions
        GROUP BY DATE_TRUNC('month', txn_date)
        ORDER BY month;
    """
    return pd.read_sql(query, engine)


if __name__ == "__main__":
    print("=== EXECUTIVE KPIs ===")
    for k, v in get_executive_kpis().items():
        print(f"  {k}: {v}")

    print("\n=== DUPLICATE PAYOUTS ===")
    print(detect_duplicate_payouts().to_string(index=False))

    print("\n=== AUTO-DEBIT CREEP ===")
    print(detect_auto_debit_creep().to_string(index=False))

    print("\n=== TOP ITC MISMATCH VENDORS ===")
    print(detect_itc_mismatches().head(5).to_string(index=False))

    print("\n=== OVERDUE CUSTOMER RISK ===")
    print(get_customer_aging_risk().head(5).to_string(index=False))