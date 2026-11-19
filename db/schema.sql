-- Drop tables in reverse dependency order if resetting
DROP TABLE IF EXISTS bank_transactions;
DROP TABLE IF EXISTS sales_invoices;
DROP TABLE IF EXISTS vendor_bills;

-- 1. Sales Invoices (Accounts Receivable / GSTR-1)
CREATE TABLE sales_invoices (
    invoice_id       VARCHAR(20) PRIMARY KEY,
    customer_name    VARCHAR(120) NOT NULL,
    customer_gstin   VARCHAR(15),
    invoice_date     DATE NOT NULL,
    due_date         DATE NOT NULL,
    taxable_amount   NUMERIC(12, 2) NOT NULL CHECK (taxable_amount >= 0),
    gst_rate         NUMERIC(4, 2) NOT NULL DEFAULT 18.00,
    gst_amount       NUMERIC(12, 2) NOT NULL,
    total_amount     NUMERIC(12, 2) NOT NULL,
    payment_status   VARCHAR(20) NOT NULL CHECK (payment_status IN ('PAID', 'PARTIAL', 'UNPAID', 'OVERDUE')),
    paid_date        DATE
);

-- 2. Vendor Bills (Accounts Payable & Input Tax Credit / GSTR-2B)
CREATE TABLE vendor_bills (
    bill_id          VARCHAR(20) PRIMARY KEY,
    vendor_name      VARCHAR(120) NOT NULL,
    vendor_gstin     VARCHAR(15),
    vendor_invoice_no VARCHAR(40) NOT NULL,
    bill_date        DATE NOT NULL,
    due_date         DATE NOT NULL,
    taxable_amount   NUMERIC(12, 2) NOT NULL CHECK (taxable_amount >= 0),
    gst_amount       NUMERIC(12, 2) NOT NULL,
    total_amount     NUMERIC(12, 2) NOT NULL,
    itc_eligible     BOOLEAN NOT NULL DEFAULT TRUE,
    gstr2b_matched   BOOLEAN NOT NULL DEFAULT TRUE,
    payment_status   VARCHAR(20) NOT NULL CHECK (payment_status IN ('PAID', 'UNPAID', 'OVERDUE'))
);

-- 3. Bank & UPI Ledger (Actual Cash Inflows & Outflows)
CREATE TABLE bank_transactions (
    txn_id           VARCHAR(25) PRIMARY KEY,
    txn_date         DATE NOT NULL,
    txn_type         VARCHAR(10) NOT NULL CHECK (txn_type IN ('CREDIT', 'DEBIT')),
    payment_mode     VARCHAR(20) NOT NULL CHECK (payment_mode IN ('UPI', 'NEFT', 'RTGS', 'IMPS', 'AUTO_DEBIT')),
    counterparty     VARCHAR(120) NOT NULL,
    upi_vpa          VARCHAR(100),
    narration        TEXT NOT NULL,
    amount           NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    running_balance  NUMERIC(14, 2) NOT NULL,
    linked_ref_id    VARCHAR(20) -- Maps to invoice_id or bill_id where applicable
);

-- Indexes for fast date-range and status queries
CREATE INDEX idx_sales_status_due ON sales_invoices(payment_status, due_date);
CREATE INDEX idx_vendor_status_due ON vendor_bills(payment_status, due_date);
CREATE INDEX idx_bank_txn_date ON bank_transactions(txn_date);

-- Metadata comments (directly helps your LLM write accurate SQL later)
COMMENT ON COLUMN vendor_bills.gstr2b_matched IS 'FALSE indicates vendor has not filed GSTR-1, putting Input Tax Credit (ITC) at risk.';
COMMENT ON COLUMN bank_transactions.linked_ref_id IS 'Matches invoice_id for CREDIT or bill_id for DEBIT; NULL if uncategorized expense.';