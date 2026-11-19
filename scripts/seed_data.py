import os
import random
from datetime import date, timedelta
import numpy as np
import pandas as pd
from faker import Faker
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))

fake = Faker("en_IN")
Faker.seed(42)
np.random.seed(42)
random.seed(42)

END_DATE = date(2026, 11, 15)
START_DATE = END_DATE - timedelta(days=180)


def random_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(delta, 0)))


def generate_dataset():
    # 1. Fixed roster of realistic Indian B2B customers & vendors
    customers = [
        ("Apex Retail Pvt Ltd", fake.gstin()[:15], True),        # Chronic late payer
        ("Metro Fresh Distributors", fake.gstin()[:15], True),   # Chronic late payer
        ("Deccan Mart Supermarket", fake.gstin()[:15], False),
        ("Nandi Agro Foods", fake.gstin()[:15], False),
        ("Kaveri Packaging Solutions", fake.gstin()[:15], False),
        ("UrbanBasket Grocers", fake.gstin()[:15], False),
        ("Sri Venkateshwara Traders", fake.gstin()[:15], False),
        ("Malnad Coffee Roasters", fake.gstin()[:15], False),
    ]

    vendors = [
        ("Chandra Logistics & Freight", fake.gstin()[:15], "logistics@okicici"),
        ("Bharath Corrugated Boxes", fake.gstin()[:15], "bharathpack@okaxis"),
        ("Vayu Cloud Hosting India", fake.gstin()[:15], "vayucloud@okhdfcbank"),
        ("Karnataka Industrial Power", fake.gstin()[:15], "bescom-biz@oksbi"),
        ("Shree Krishna Raw Materials", fake.gstin()[:15], "skrawmat@okicici"),
        ("Zoho / SaaS Ops India", fake.gstin()[:15], "saasops@okicici"),
        ("Prime Cold-Chain Services", fake.gstin()[:15], "primecold@okaxis"),
    ]

    sales_rows = []
    bill_rows = []
    txn_rows = []

    # 2. Generate 500 Sales Invoices + matching CREDIT transactions
    for i in range(1, 501):
        inv_id = f"INV-2026-{i:04d}"
        cust_name, cust_gstin, is_late_payer = random.choice(customers)
        inv_date = random_date(START_DATE, END_DATE)
        due_date = inv_date + timedelta(days=30)

        taxable = round(float(np.random.uniform(12000, 145000)), 2)
        gst_rate = random.choice([5.00, 12.00, 18.00])
        gst_amt = round(taxable * (gst_rate / 100.0), 2)
        total_amt = round(taxable + gst_amt, 2)

        if is_late_payer and inv_date >= END_DATE - timedelta(days=75):
            status = "OVERDUE"
            paid_date = None
        elif due_date < END_DATE and random.random() < 0.82:
            status = "PAID"
            paid_date = min(END_DATE, due_date + timedelta(days=random.randint(-5, 12)))
        elif due_date < END_DATE:
            status = "OVERDUE"
            paid_date = None
        else:
            status = "UNPAID"
            paid_date = None

        sales_rows.append({
            "invoice_id": inv_id,
            "customer_name": cust_name,
            "customer_gstin": cust_gstin,
            "invoice_date": inv_date,
            "due_date": due_date,
            "taxable_amount": taxable,
            "gst_rate": gst_rate,
            "gst_amount": gst_amt,
            "total_amount": total_amt,
            "payment_status": status,
            "paid_date": paid_date,
        })

        if status == "PAID" and paid_date is not None:
            mode = random.choice(["NEFT", "RTGS", "UPI", "IMPS"])
            vpa = f"{cust_name.split()[0].lower()}@okicici" if mode == "UPI" else None
            txn_rows.append({
                "txn_date": paid_date,
                "txn_type": "CREDIT",
                "payment_mode": mode,
                "counterparty": cust_name,
                "upi_vpa": vpa,
                "narration": f"{mode}/RCVD/{cust_name.upper()}/REF-{inv_id}",
                "amount": total_amt,
                "linked_ref_id": inv_id,
            })

    # 3. Generate 450 Vendor Bills + matching DEBIT transactions
    paid_bills_for_duplication = []

    for j in range(1, 451):
        bill_id = f"BILL-2026-{j:04d}"
        vend_name, vend_gstin, vend_vpa = random.choice(vendors)
        bill_date = random_date(START_DATE, END_DATE)
        due_date = bill_date + timedelta(days=21)

        taxable = round(float(np.random.uniform(8000, 95000)), 2)
        gst_amt = round(taxable * 0.18, 2)
        total_amt = round(taxable + gst_amt, 2)

        # Plant 15 GSTR-2B mismatches (ITC at risk)
        itc_eligible = True
        gstr2b_matched = False if j <= 15 else True

        if due_date < END_DATE and random.random() < 0.85:
            status = "PAID"
            pay_date = min(END_DATE, due_date + timedelta(days=random.randint(-4, 5)))
        elif due_date < END_DATE:
            status = "OVERDUE"
            pay_date = None
        else:
            status = "UNPAID"
            pay_date = None

        bill_record = {
            "bill_id": bill_id,
            "vendor_name": vend_name,
            "vendor_gstin": vend_gstin,
            "vendor_invoice_no": f"VND-{random.randint(10000, 99999)}",
            "bill_date": bill_date,
            "due_date": due_date,
            "taxable_amount": taxable,
            "gst_amount": gst_amt,
            "total_amount": total_amt,
            "itc_eligible": itc_eligible,
            "gstr2b_matched": gstr2b_matched,
            "payment_status": status,
        }
        bill_rows.append(bill_record)

        if status == "PAID" and pay_date is not None:
            mode = random.choice(["UPI", "NEFT", "IMPS"])
            txn_entry = {
                "txn_date": pay_date,
                "txn_type": "DEBIT",
                "payment_mode": mode,
                "counterparty": vend_name,
                "upi_vpa": vend_vpa if mode == "UPI" else None,
                "narration": f"{mode}/PAID/{vend_name.upper()}/{bill_record['vendor_invoice_no']}",
                "amount": total_amt,
                "linked_ref_id": bill_id,
            }
            txn_rows.append(txn_entry)
            if total_amt > 35000 and len(paid_bills_for_duplication) < 3:
                paid_bills_for_duplication.append(txn_entry)

    # 4. Plant Anomaly A: 3 Duplicate Vendor Payouts (paid twice within 3 days)
    for dup in paid_bills_for_duplication:
        dup_txn = dup.copy()
        dup_txn["txn_date"] = min(END_DATE, dup["txn_date"] + timedelta(days=3))
        dup_txn["narration"] = dup["narration"] + "-RETRY"
        txn_rows.append(dup_txn)

    # 5. Plant Anomaly B: Silent Auto-Debit SaaS Creep over 6 months
    for m in range(6):
        debit_date = START_DATE + timedelta(days=30 * m + 5)
        if debit_date <= END_DATE:
            amount = 26800.00 if m == 5 else 18500.00  # 45% jump in final month
            txn_rows.append({
                "txn_date": debit_date,
                "txn_type": "DEBIT",
                "payment_mode": "AUTO_DEBIT",
                "counterparty": "Vayu Cloud Hosting India",
                "upi_vpa": None,
                "narration": "NACH-AUTO-DEBIT/VAYU-CLOUD-ENTERPRISE",
                "amount": amount,
                "linked_ref_id": None,
            })

    # 6. Sort bank transactions chronologically & compute running_balance
    df_sales = pd.DataFrame(sales_rows)
    df_bills = pd.DataFrame(bill_rows)
    df_txns = pd.DataFrame(txn_rows).sort_values(by=["txn_date", "txn_type"]).reset_index(drop=True)

    df_txns["txn_id"] = [f"TXN-2026-{idx + 1:05d}" for idx in range(len(df_txns))]

    balance = 1250000.00  # ₹12.50 Lakh opening balance
    balances = []
    for _, row in df_txns.iterrows():
        if row["txn_type"] == "CREDIT":
            balance = round(balance + row["amount"], 2)
        else:
            balance = round(balance - row["amount"], 2)
        balances.append(balance)

    df_txns["running_balance"] = balances

    # Reorder columns to match PostgreSQL table definition
    df_txns = df_txns[
        [
            "txn_id", "txn_date", "txn_type", "payment_mode",
            "counterparty", "upi_vpa", "narration", "amount",
            "running_balance", "linked_ref_id",
        ]
    ]

    return df_sales, df_bills, df_txns


def seed_database():
    df_sales, df_bills, df_txns = generate_dataset()

    with engine.begin() as conn:
        # Clear existing rows so the script is safely re-runnable
        conn.execute(text("TRUNCATE TABLE bank_transactions, sales_invoices, vendor_bills;"))
        df_sales.to_sql("sales_invoices", con=conn, if_exists="append", index=False)
        df_bills.to_sql("vendor_bills", con=conn, if_exists="append", index=False)
        df_txns.to_sql("bank_transactions", con=conn, if_exists="append", index=False)

    print(f"Seeded tallyx: {len(df_sales)} sales, {len(df_bills)} bills, {len(df_txns)} bank txns.")


if __name__ == "__main__":
    seed_database()