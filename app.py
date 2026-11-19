import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from analytics.metrics_engine import (
    get_executive_kpis,
    detect_duplicate_payouts,
    detect_itc_mismatches,
    detect_auto_debit_creep,
    get_customer_aging_risk,
    get_monthly_cashflow_series,
)
from ai.copilot import ask_tallyx

# -----------------------------------------------------------------------------
# Page Configuration & Styling
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="TallyX — Governed MSME Financial Copilot",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    div[data-testid="stMetric"] {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.25);
        padding: 16px 20px;
        border-radius: 10px;
    }
    </style>
""", unsafe_allow_html=True)


def format_inr(amount: float) -> str:
    """Formats numbers into concise Indian Rupee notation (Lakhs / exact)."""
    if abs(amount) >= 100000:
        return f"₹{amount / 100000:,.2f} L"
    return f"₹{amount:,.2f}"


@st.cache_data(ttl=120)
def load_dashboard_data():
    return {
        "kpis": get_executive_kpis(),
        "dupes": detect_duplicate_payouts(),
        "itc": detect_itc_mismatches(),
        "creep": detect_auto_debit_creep(),
        "aging": get_customer_aging_risk(),
        "cashflow": get_monthly_cashflow_series(),
    }


data = load_dashboard_data()
kpis = data["kpis"]

# -----------------------------------------------------------------------------
# Sidebar: System Status & Demo Controls
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("📊 TallyX")
    st.caption("Zero-Hallucination MSME Financial & GST Copilot")
    st.divider()

    st.markdown("**Ledger Connection**")
    st.success("PostgreSQL `tallyx` • Connected")
    st.caption("Anchor Date: `2026-11-15` • 1,604 Records Indexed")

    st.divider()
    st.markdown("**Active Audit Guardrails**")
    st.markdown(
        "- ✅ Deterministic SQL Metrics\n"
        "- ✅ Read-Only NL-to-SQL Sandbox\n"
        "- ✅ GSTR-2B ITC Reconciliation\n"
        "- ✅ Duplicate UPI/NEFT Catcher"
    )

    st.divider()
    if st.button("🔄 Refresh Ledger Metrics", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# -----------------------------------------------------------------------------
# Header & Top KPI Strip
# -----------------------------------------------------------------------------
st.title("TallyX Executive Financial Cockpit")
st.caption("Real-time cash-flow intelligence, GSTR-2B leakage audit, and governed NL-to-SQL CFO copilot.")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric(
        label="Net Cash Balance",
        value=format_inr(kpis["current_cash_balance"]),
        delta=kpis["runway_status"],
    )
with col2:
    st.metric(
        label="Overdue Receivables (AR)",
        value=format_inr(kpis["overdue_receivables"]),
        delta=f"{kpis['overdue_invoice_count']} Overdue Invoices",
        delta_color="inverse",
    )
with col3:
    st.metric(
        label="Blocked GSTR-2B ITC",
        value=format_inr(kpis["blocked_itc_risk"]),
        delta="At Risk Before GSTR-3B",
        delta_color="inverse",
    )
with col4:
    st.metric(
        label="Nov 2026 Net GST Payable",
        value=format_inr(kpis["current_month_net_gst"]),
        delta="Output GST minus Valid ITC",
        delta_color="off",
    )

st.divider()

# -----------------------------------------------------------------------------
# Main Workspace: Visual Analytics + Automated Leak Audit (Left) | AI Copilot (Right)
# -----------------------------------------------------------------------------
left_col, right_col = st.columns([1.25, 1.0], gap="large")

with left_col:
    st.subheader("1. Cash-Flow & Receivables Intelligence")

    chart_tab1, chart_tab2 = st.tabs(["Monthly Cash Inflow vs. Outflow", "Overdue Customer Aging"])

    with chart_tab1:
        df_cf = data["cashflow"]
        fig_cf = go.Figure()
        fig_cf.add_trace(go.Bar(
            x=df_cf["month"],
            y=df_cf["cash_inflow"],
            name="Cash Inflow (Credits)",
            marker_color="#14B8A6",
        ))
        fig_cf.add_trace(go.Bar(
            x=df_cf["month"],
            y=df_cf["cash_outflow"],
            name="Cash Outflow (Debits)",
            marker_color="#F43F5E",
        ))
        fig_cf.add_trace(go.Scatter(
            x=df_cf["month"],
            y=df_cf["net_cashflow"],
            name="Net Cash Flow",
            mode="lines+markers",
            line=dict(color="#FBBF24", width=3),
        ))
        fig_cf.update_layout(
            barmode="group",
            height=330,
            margin=dict(l=10, r=10, t=25, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            yaxis_title="Amount (₹)",
        )
        st.plotly_chart(fig_cf, use_container_width=True)

    with chart_tab2:
        df_aging = data["aging"]
        fig_aging = px.bar(
            df_aging,
            x="overdue_amount",
            y="customer_name",
            orientation="h",
            color="avg_days_overdue",
            color_continuous_scale="Tealrose",
            labels={
                "overdue_amount": "Overdue Amount (₹)",
                "customer_name": "Customer",
                "avg_days_overdue": "Avg Days Overdue",
            },
        )
        fig_aging.update_layout(
            height=330,
            margin=dict(l=10, r=10, t=25, b=10),
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_aging, use_container_width=True)

    st.subheader("2. Automated Financial Leak Detector")
    leak_tab1, leak_tab2, leak_tab3 = st.tabs([
        f"🚨 Duplicate Payouts ({len(data['dupes'])})",
        f"⚠️ GSTR-2B ITC Mismatches ({len(data['itc'])})",
        f"📈 Auto-Debit Creep ({len(data['creep'])})",
    ])

    with leak_tab1:
        df_dupes = data["dupes"]
        total_leak = df_dupes["duplicate_amount"].sum() if not df_dupes.empty else 0.0
        st.warning(f"**Immediate Recovery Opportunity:** ₹{total_leak:,.2f} paid twice across {len(df_dupes)} vendor bills.")
        st.dataframe(df_dupes, use_container_width=True, hide_index=True)

    with leak_tab2:
        df_itc = data["itc"]
        st.info("Suppliers below have not filed GSTR-1. Chase them before filing GSTR-3B to unlock blocked Input Tax Credit.")
        st.dataframe(df_itc, use_container_width=True, hide_index=True)

    with leak_tab3:
        df_creep = data["creep"]
        st.warning("Recurring NACH / Auto-Debit mandates that jumped >20% above their historical baseline.")
        st.dataframe(df_creep, use_container_width=True, hide_index=True)

with right_col:
    st.subheader("3. Governed AI CFO Copilot")
    st.caption("Every answer is computed via live PostgreSQL queries—never LLM mental math.")

    # Quick-click demo prompts
    st.markdown("**Try a CFO Audit Prompt:**")
    demo_prompts = [
        "Which vendors have unmatched GSTR-2B bills and how much ITC is blocked?",
        "Which overdue customer invoices can cover November 2026 net GST liability?",
        "Show me any vendor bills paid twice in our bank ledger.",
    ]

    selected_demo = None
    for idx, q in enumerate(demo_prompts):
        if st.button(f"💬 {q}", key=f"demo_q_{idx}", use_container_width=True):
            selected_demo = q

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Welcome to **TallyX**. I'm connected directly to your PostgreSQL ledger (`1,604` transactions & invoices). "
                    "Ask me anything about cash flow, GST liabilities, overdue customers, or vendor anomalies."
                ),
                "sql": None,
                "data": None,
            }
        ]

    # Render chat history inside a scrollable container
    chat_box = st.container(height=460)
    with chat_box:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("sql"):
                    with st.expander("🔍 Verify Executed SQL & Raw Data"):
                        st.code(msg["sql"], language="sql")
                        if msg.get("data") is not None and not msg["data"].empty:
                            st.dataframe(msg["data"], use_container_width=True, hide_index=True)

    user_input = st.chat_input("Ask TallyX about cash flow, GST, or overdue bills...")
    active_prompt = selected_demo or user_input

    if active_prompt:
        st.session_state.messages.append({"role": "user", "content": active_prompt})
        with chat_box:
            with st.chat_message("user"):
                st.markdown(active_prompt)

            with st.chat_message("assistant"):
                with st.spinner("Translating to PostgreSQL & verifying numbers..."):
                    result = ask_tallyx(active_prompt)
                st.markdown(result["answer"])
                if result.get("sql"):
                    with st.expander("🔍 Verify Executed SQL & Raw Data", expanded=True):
                        st.code(result["sql"], language="sql")
                        if result.get("data") is not None and not result["data"].empty:
                            st.dataframe(result["data"], use_container_width=True, hide_index=True)

        st.session_state.messages.append({
            "role": "assistant",
            "content": result["answer"],
            "sql": result.get("sql"),
            "data": result.get("data"),
        })