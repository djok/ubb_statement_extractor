"""Streamlit monitoring dashboard for UBB Statement Extractor."""

import sys
from pathlib import Path

# Add src to path for imports when running directly with streamlit
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import io
import streamlit as st
import pandas as pd
from datetime import date, timedelta

from src.monitoring.auth import check_password
from src.monitoring.queries import MonitoringQueries
from src.monitoring.gap_detector import GapDetector

# Page config
st.set_page_config(
    page_title="UBB Statement Monitor",
    page_icon="📊",
    layout="wide",
)

# Authentication
if not check_password():
    st.stop()

# Initialize services
@st.cache_resource
def get_queries():
    return MonitoringQueries()


@st.cache_resource
def get_gap_detector():
    return GapDetector()


queries = get_queries()
gap_detector = get_gap_detector()

# Sidebar
st.sidebar.title("📊 UBB Monitor")

# Account filter
accounts = ["All"] + queries.get_accounts()
selected_account = st.sidebar.selectbox("Account (IBAN)", accounts)
iban_filter = None if selected_account == "All" else selected_account

# Date range
st.sidebar.subheader("Date Range")
date_preset = st.sidebar.selectbox(
    "Quick Select",
    ["Last 30 days", "Last 90 days", "Last Year", "Custom"],
)

if date_preset == "Last 30 days":
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
elif date_preset == "Last 90 days":
    end_date = date.today()
    start_date = end_date - timedelta(days=90)
elif date_preset == "Last Year":
    end_date = date.today()
    start_date = end_date - timedelta(days=365)
else:
    start_date = st.sidebar.date_input("From", date.today() - timedelta(days=30))
    end_date = st.sidebar.date_input("To", date.today())

date_range = (start_date, end_date)

# Main content
st.title("Bank Statement Monitor")

# Metrics row
col1, col2, col3, col4 = st.columns(4)

with col1:
    stmt_count = queries.count_statements(iban=iban_filter, date_range=date_range)
    st.metric("Statements", stmt_count)

with col2:
    tx_count = queries.count_transactions(iban=iban_filter, date_range=date_range)
    st.metric("Transactions", f"{tx_count:,}")

with col3:
    failed_count = queries.count_failed_imports(date_range=date_range)
    st.metric("Failed Imports", failed_count, delta_color="inverse")

with col4:
    validation_issues = queries.get_validation_issues(iban=iban_filter)
    st.metric("Validation Issues", len(validation_issues), delta_color="inverse")

# Tabs for different views
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📈 Overview",
    "🔍 Gap Detection",
    "📋 Import Log",
    "⚠️ Validation Issues",
    "🏢 Accounts",
    "🔄 Admin",
    "💳 Transactions",
])

with tab1:
    st.subheader("Transaction Volume")

    volume_df = queries.get_transaction_volume(iban=iban_filter, date_range=date_range)

    if not volume_df.empty:
        import plotly.express as px

        fig = px.bar(
            volume_df,
            x="date",
            y="count",
            title="Daily Transaction Count",
            labels={"date": "Date", "count": "Transactions"},
        )
        st.plotly_chart(fig, use_container_width=True)

        # Debit/Credit breakdown
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Transaction Types")
            types_df = queries.get_transaction_types(
                iban=iban_filter, date_range=date_range
            )
            if not types_df.empty:
                fig2 = px.pie(
                    types_df,
                    values="count",
                    names="transaction_type",
                    title="By Type",
                )
                st.plotly_chart(fig2, use_container_width=True)

        with col2:
            st.subheader("Top Counterparties")
            top_df = queries.get_top_counterparties(
                iban=iban_filter, date_range=date_range, limit=10
            )
            if not top_df.empty:
                st.dataframe(
                    top_df,
                    hide_index=True,
                    column_config={
                        "counterparty_name": "Counterparty",
                        "transaction_count": "Count",
                        "total_eur": st.column_config.NumberColumn(
                            "Total EUR", format="%.2f"
                        ),
                    },
                )

        # Balance history
        st.subheader("Balance History")
        balance_df = queries.get_balance_history(
            iban=iban_filter, date_range=date_range
        )
        if not balance_df.empty:
            fig3 = px.line(
                balance_df,
                x="statement_date",
                y="closing_balance_eur",
                color="iban",
                title="Closing Balance (EUR)",
                labels={
                    "statement_date": "Date",
                    "closing_balance_eur": "Balance EUR",
                    "iban": "Account",
                },
            )
            st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("No transaction data for selected period.")

with tab2:
    st.subheader("Missing Statements Detection")

    lookback = st.slider(
        "Lookback Period (days)",
        min_value=30,
        max_value=730,
        value=365,
        step=30,
    )

    # Coverage summary
    st.subheader("Coverage Summary")
    coverage_df = gap_detector.get_coverage_summary(lookback_days=lookback)

    if not coverage_df.empty:
        st.dataframe(
            coverage_df,
            hide_index=True,
            column_config={
                "iban": "IBAN",
                "account_holder_name": "Account Holder",
                "first_statement": "First Statement",
                "last_statement": "Last Statement",
                "total_statements": "Statements",
                "gap_count": st.column_config.NumberColumn(
                    "Gaps",
                    help="Number of gaps in statement sequence",
                ),
                "total_missing_days": st.column_config.NumberColumn(
                    "Missing Days",
                    help="Total number of missing statement days",
                ),
            },
        )

    # Gap details
    st.subheader("Gap Details")
    gaps_df = gap_detector.get_gaps_dataframe(iban=iban_filter, lookback_days=lookback)

    if not gaps_df.empty:
        st.warning(f"Found {len(gaps_df)} gaps in statement sequence!")
        st.dataframe(
            gaps_df,
            hide_index=True,
            column_config={
                "iban": "IBAN",
                "account_holder_name": "Account Holder",
                "gap_start": "Gap Start",
                "gap_end": "Gap End",
                "missing_days": st.column_config.NumberColumn("Missing Days"),
            },
        )
    else:
        st.success("No gaps detected in statement sequence.")

with tab3:
    st.subheader("Recent Import Log")

    import_limit = st.selectbox("Show last", [20, 50, 100, 200], index=0)
    imports_df = queries.get_recent_imports(limit=import_limit)

    if not imports_df.empty:
        # Status summary
        status_counts = imports_df["status"].value_counts()
        cols = st.columns(len(status_counts))
        for i, (status, count) in enumerate(status_counts.items()):
            with cols[i]:
                color = (
                    "green"
                    if status == "success"
                    else "orange" if status == "duplicate" else "red"
                )
                st.markdown(
                    f"**{status.upper()}**: :{color}[{count}]"
                )

        st.dataframe(
            imports_df,
            hide_index=True,
            column_config={
                "started_at": st.column_config.DatetimeColumn(
                    "Time", format="YYYY-MM-DD HH:mm"
                ),
                "source_filename": "Filename",
                "iban": "IBAN",
                "statement_date": "Statement Date",
                "status": "Status",
                "transactions_imported": "Transactions",
                "error_message": "Error",
            },
        )
    else:
        st.info("No import log entries.")

with tab4:
    st.subheader("Balance Validation Issues")

    issues_df = queries.get_validation_issues(iban=iban_filter)

    if not issues_df.empty:
        st.error(f"Found {len(issues_df)} statements with validation errors!")
        st.dataframe(
            issues_df,
            hide_index=True,
            column_config={
                "statement_id": "Statement ID",
                "iban": "IBAN",
                "account_holder_name": "Account Holder",
                "statement_date": "Date",
                "validation_errors": "Errors",
            },
        )
    else:
        st.success("All statements passed balance validation.")

with tab5:
    st.subheader("Account Overview")

    accounts_df = queries.get_account_details()

    if not accounts_df.empty:
        st.dataframe(
            accounts_df,
            hide_index=True,
            column_config={
                "iban": "IBAN",
                "account_holder_name": "Account Holder",
                "account_holder_code": "Code",
                "first_statement": "First Statement",
                "last_statement": "Last Statement",
                "statement_count": "Total Statements",
            },
        )
    else:
        st.info("No accounts found.")

with tab6:
    st.subheader("Admin Operations")

    st.warning("⚠️ These operations modify data in BigQuery. Use with caution!")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Reprocess ZIP Files")
        st.markdown("""
        Re-extract and re-import all ZIP files from `/data/zip` using the latest extraction logic.
        Existing data will be replaced.
        """)

        if st.button("🔄 Reprocess All ZIP Files", type="primary"):
            import requests
            with st.spinner("Reprocessing ZIP files..."):
                try:
                    response = requests.post(
                        "http://api:8000/admin/reprocess",
                        params={"force": True},
                        timeout=300,
                    )
                    if response.status_code == 200:
                        result = response.json()
                        st.success(f"Reprocessing complete!")
                        st.json(result["summary"])

                        # Show details
                        with st.expander("Details"):
                            for f in result["files"]:
                                status_icon = {
                                    "success": "✅",
                                    "replaced": "🔄",
                                    "duplicate": "⏭️",
                                    "streaming_buffer": "⏳",
                                    "error": "❌",
                                }.get(f["status"], "❓")
                                st.markdown(f"{status_icon} **{f['filename']}**: {f['status']} - {f['message']}")

                        # Show warning if streaming buffer issues
                        if result["summary"].get("streaming_buffer", 0) > 0:
                            st.warning(
                                f"⏳ {result['summary']['streaming_buffer']} file(s) could not be replaced due to BigQuery streaming buffer. "
                                "Wait ~90 minutes after initial import and try again."
                            )
                    else:
                        st.error(f"Error: {response.text}")
                except requests.exceptions.ConnectionError:
                    st.error("Cannot connect to API service. Make sure it's running.")
                except Exception as e:
                    st.error(f"Error: {e}")

    with col2:
        st.markdown("### Truncate All Data")
        st.markdown("""
        **DANGER**: This will permanently delete ALL data from BigQuery tables
        (statements, transactions, import_log).

        Uses TRUNCATE which is faster and **bypasses streaming buffer**.
        """)

        confirm_text = st.text_input(
            "Type DELETE_ALL to confirm",
            key="delete_confirm",
            help="This action cannot be undone!",
        )

        if st.button("🗑️ Truncate All Data", type="secondary"):
            if confirm_text == "DELETE_ALL":
                import requests
                with st.spinner("Truncating all tables..."):
                    try:
                        response = requests.delete(
                            "http://api:8000/admin/data",
                            params={"confirm": "DELETE_ALL"},
                            timeout=60,
                        )
                        if response.status_code == 200:
                            result = response.json()
                            st.success("All tables truncated!")
                            st.json(result.get("truncated", result))
                        else:
                            st.error(f"Error: {response.text}")
                    except requests.exceptions.ConnectionError:
                        st.error("Cannot connect to API service. Make sure it's running.")
                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                st.error("Please type DELETE_ALL to confirm deletion.")

    st.markdown("---")
    st.markdown("### Transaction Type Statistics")

    # Show current transaction types
    types_stats = queries.get_transaction_types(iban=iban_filter, date_range=date_range)
    if not types_stats.empty:
        st.dataframe(
            types_stats,
            hide_index=True,
            column_config={
                "transaction_type": "Type",
                "count": "Count",
                "total_eur": st.column_config.NumberColumn("Total EUR", format="%.2f"),
                "avg_eur": st.column_config.NumberColumn("Avg EUR", format="%.2f"),
            },
        )

        # Show UNKNOWN count prominently if any
        unknown_count = types_stats[types_stats["transaction_type"] == "UNKNOWN"]["count"].sum()
        if unknown_count > 0:
            st.warning(f"⚠️ Found {unknown_count} UNKNOWN transaction types. Consider reprocessing ZIP files.")
    else:
        st.info("No transaction data.")

with tab7:
    st.subheader("Transaction Browser")

    # Initialize session state for pagination
    if "tx_page" not in st.session_state:
        st.session_state.tx_page = 0
    if "tx_per_page" not in st.session_state:
        st.session_state.tx_per_page = 50

    # Filter section
    st.markdown("### Filters")
    filter_col1, filter_col2, filter_col3 = st.columns(3)

    with filter_col1:
        # Account filter (single select for running balance)
        all_accounts = queries.get_accounts()
        selected_iban = st.selectbox(
            "Account (IBAN)",
            options=[""] + all_accounts,
            format_func=lambda x: "Select account..." if x == "" else x,
            key="tx_iban_single",
        )

    with filter_col2:
        # Transaction types filter
        all_types = queries.get_all_transaction_types()
        selected_types = st.multiselect(
            "Transaction Types",
            options=all_types,
            default=[],
            placeholder="All types",
            key="tx_types",
        )

    with filter_col3:
        # Counterparties filter (search-enabled)
        counterparties = queries.get_distinct_counterparties(
            ibans=[selected_iban] if selected_iban else None,
            date_range=date_range,
        )
        selected_counterparties = st.multiselect(
            "Counterparties",
            options=counterparties,
            default=[],
            placeholder="All counterparties",
            key="tx_counterparties",
        )

    # Reset page when filters change
    filter_key = f"{selected_iban}_{selected_types}_{selected_counterparties}_{date_range}"
    if "last_filter_key" not in st.session_state:
        st.session_state.last_filter_key = filter_key
    if st.session_state.last_filter_key != filter_key:
        st.session_state.tx_page = 0
        st.session_state.last_filter_key = filter_key

    # Check if single account is selected (required for running balance)
    if not selected_iban:
        st.warning("Please select an account to view transactions with running balance.")

        # Show aggregations for all accounts
        aggs = queries.get_transaction_aggregations(
            ibans=None,
            counterparties=selected_counterparties if selected_counterparties else None,
            transaction_types=selected_types if selected_types else None,
            date_range=date_range,
        )

        st.markdown("### Summary (All Accounts)")
        agg_col1, agg_col2, agg_col3, agg_col4 = st.columns(4)
        with agg_col1:
            st.metric("Total Transactions", f"{aggs['total_count']:,}")
        with agg_col2:
            st.metric("Credits (+)", f"€{aggs['total_credits']:,.2f}")
        with agg_col3:
            st.metric("Debits (-)", f"€{aggs['total_debits']:,.2f}")
        with agg_col4:
            st.metric("Net", f"€{aggs['net_amount']:,.2f}")
    else:
        # Get aggregations for selected account
        aggs = queries.get_transaction_aggregations(
            ibans=[selected_iban],
            counterparties=selected_counterparties if selected_counterparties else None,
            transaction_types=selected_types if selected_types else None,
            date_range=date_range,
        )

        # Aggregations row
        st.markdown("### Summary")
        agg_col1, agg_col2, agg_col3, agg_col4 = st.columns(4)

        with agg_col1:
            st.metric("Total Transactions", f"{aggs['total_count']:,}")
        with agg_col2:
            st.metric("Credits (+)", f"€{aggs['total_credits']:,.2f}")
        with agg_col3:
            st.metric("Debits (-)", f"€{aggs['total_debits']:,.2f}")
        with agg_col4:
            st.metric("Net", f"€{aggs['net_amount']:,.2f}")

        # Pagination settings
        st.markdown("### Transactions")
        page_col1, page_col2, page_col3 = st.columns([1, 1, 3])

        with page_col1:
            rows_per_page = st.selectbox(
                "Rows per page",
                options=[25, 50, 100, 200],
                index=1,
                key="tx_rows_per_page",
            )
            st.session_state.tx_per_page = rows_per_page

        # Get transactions with running balance
        offset = st.session_state.tx_page * rows_per_page
        transactions_df, opening_balance, total_count = queries.get_transactions_with_balance(
            iban=selected_iban,
            date_range=date_range,
            counterparties=selected_counterparties if selected_counterparties else None,
            transaction_types=selected_types if selected_types else None,
            offset=offset,
            limit=rows_per_page,
        )

        total_pages = max(1, (total_count + rows_per_page - 1) // rows_per_page)

        with page_col2:
            st.write(f"Page {st.session_state.tx_page + 1} of {total_pages}")
            st.write(f"({total_count:,} total)")

        with page_col3:
            nav_col1, nav_col2, nav_col3, nav_col4 = st.columns(4)
            with nav_col1:
                if st.button("⏮️ First", disabled=st.session_state.tx_page == 0):
                    st.session_state.tx_page = 0
                    st.rerun()
            with nav_col2:
                if st.button("◀️ Prev", disabled=st.session_state.tx_page == 0):
                    st.session_state.tx_page -= 1
                    st.rerun()
            with nav_col3:
                if st.button("Next ▶️", disabled=st.session_state.tx_page >= total_pages - 1):
                    st.session_state.tx_page += 1
                    st.rerun()
            with nav_col4:
                if st.button("Last ⏭️", disabled=st.session_state.tx_page >= total_pages - 1):
                    st.session_state.tx_page = total_pages - 1
                    st.rerun()

        # Show opening balance prominently
        if opening_balance is not None:
            st.success(f"📊 **Opening Balance (before {date_range[0]}):** €{opening_balance:,.2f}")
        else:
            st.warning("⚠️ No opening balance found (no prior statement)")

        if not transactions_df.empty:
            # Format for display with colored credit/debit
            display_df = transactions_df[[
                "posting_date", "counterparty_name", "description",
                "transaction_type", "credit_eur", "debit_eur", "running_balance", "reference"
            ]].copy()

            # Style function for colored cells
            def style_credit_debit(df):
                styles = pd.DataFrame("", index=df.index, columns=df.columns)
                # Green for credit
                credit_mask = pd.notna(df["credit_eur"]) & (df["credit_eur"] != "")
                debit_mask = pd.notna(df["debit_eur"]) & (df["debit_eur"] != "")
                styles.loc[credit_mask, "credit_eur"] = "color: green; font-weight: bold"
                # Red for debit
                styles.loc[debit_mask, "debit_eur"] = "color: red; font-weight: bold"
                return styles

            # Replace NaN with empty string for cleaner display
            display_df["credit_eur"] = display_df["credit_eur"].apply(
                lambda x: f"{x:,.2f}" if pd.notna(x) else ""
            )
            display_df["debit_eur"] = display_df["debit_eur"].apply(
                lambda x: f"{x:,.2f}" if pd.notna(x) else ""
            )
            display_df["running_balance"] = display_df["running_balance"].apply(
                lambda x: f"{x:,.2f}" if pd.notna(x) else ""
            )

            styled_df = display_df.style.apply(style_credit_debit, axis=None)

            st.dataframe(
                styled_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "posting_date": st.column_config.DateColumn("Date"),
                    "counterparty_name": "Counterparty",
                    "description": "Description",
                    "transaction_type": "Type",
                    "credit_eur": st.column_config.TextColumn(
                        "Credit EUR",
                        help="Incoming amounts (green)",
                    ),
                    "debit_eur": st.column_config.TextColumn(
                        "Debit EUR",
                        help="Outgoing amounts (red)",
                    ),
                    "running_balance": st.column_config.TextColumn(
                        "Balance EUR",
                        help="Running balance after this transaction",
                    ),
                    "reference": "Reference",
                },
            )
        else:
            st.info("No transactions found for selected filters.")

    # Export section
    st.markdown("### Export")
    export_col1, export_col2, export_col3 = st.columns([1, 1, 3])

    # Get all transactions for export (no pagination)
    @st.cache_data(ttl=300)
    def get_all_transactions_for_export(ibans, counterparties, types, date_range_tuple):
        return queries.get_transactions(
            ibans=ibans if ibans else None,
            counterparties=counterparties if counterparties else None,
            transaction_types=types if types else None,
            date_range=date_range_tuple,
            offset=0,
            limit=100000,  # Max export limit
        )

    with export_col1:
        if st.button("📥 Prepare Export"):
            with st.spinner("Preparing export data..."):
                export_df = get_all_transactions_for_export(
                    tuple(selected_ibans) if selected_ibans else None,
                    tuple(selected_counterparties) if selected_counterparties else None,
                    tuple(selected_types) if selected_types else None,
                    date_range,
                )
                st.session_state.export_df = export_df
                st.success(f"Prepared {len(export_df):,} transactions for export")

    if "export_df" in st.session_state and st.session_state.export_df is not None:
        export_df = st.session_state.export_df

        with export_col2:
            # CSV download
            csv_data = export_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📄 Download CSV",
                data=csv_data,
                file_name=f"transactions_{start_date}_{end_date}.csv",
                mime="text/csv",
            )

        with export_col3:
            # Excel download
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                export_df.to_excel(writer, index=False, sheet_name="Transactions")
            excel_data = excel_buffer.getvalue()
            st.download_button(
                label="📊 Download Excel",
                data=excel_data,
                file_name=f"transactions_{start_date}_{end_date}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    # PDF Downloads section
    st.markdown("---")
    st.markdown("### Statement PDFs")

    statements_df = queries.get_statements_with_pdfs(
        ibans=[selected_iban] if selected_iban else None,
        date_range=date_range,
    )

    if not statements_df.empty and statements_df["gcs_pdf_path"].notna().any():
        st.info(f"Found {len(statements_df)} statements in selected period")

        # Import uploader for signed URLs
        try:
            from src.services.storage import StatementUploader
            uploader = StatementUploader()
            gcs_available = True
        except Exception as e:
            st.warning(f"GCS not configured: {e}")
            gcs_available = False

        if gcs_available:
            for _, row in statements_df.iterrows():
                pdf_col1, pdf_col2, pdf_col3, pdf_col4 = st.columns([2, 3, 2, 2])

                with pdf_col1:
                    st.write(f"📅 {row['statement_date']}")
                with pdf_col2:
                    st.write(f"🏦 {row['account_holder_name']}")
                with pdf_col3:
                    st.write(f"💳 ...{row['iban'][-8:]}")
                with pdf_col4:
                    if row["gcs_pdf_path"]:
                        try:
                            signed_url = uploader.get_signed_url(row["gcs_pdf_path"])
                            st.link_button(
                                "📄 PDF",
                                signed_url,
                                help=f"Download PDF (link valid 15 min)",
                            )
                        except Exception as e:
                            st.write("❌ Error")
                    else:
                        st.write("N/A")
    elif not statements_df.empty:
        st.info("Statements found but PDFs not yet uploaded to cloud storage.")
    else:
        st.info("No statements found for selected period.")

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown("UBB Statement Extractor v1.0")
