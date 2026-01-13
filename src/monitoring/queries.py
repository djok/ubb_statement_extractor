"""BigQuery monitoring queries."""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class MonitoringQueries:
    """BigQuery queries for monitoring dashboard."""

    def __init__(self):
        from ..services.bigquery.client import BigQueryClient

        self.bq = BigQueryClient()

    def get_accounts(self) -> list[str]:
        """Get list of unique IBANs."""
        query = f"""
            SELECT DISTINCT iban
            FROM `{self.bq.full_table_id("statements")}`
            ORDER BY iban
        """
        result = self.bq.client.query(query).result()
        return [row.iban for row in result]

    def get_account_details(self) -> pd.DataFrame:
        """Get account details with holder names."""
        query = f"""
            SELECT DISTINCT
                iban,
                account_holder_name,
                account_holder_code,
                MIN(statement_date) as first_statement,
                MAX(statement_date) as last_statement,
                COUNT(*) as statement_count
            FROM `{self.bq.full_table_id("statements")}`
            GROUP BY iban, account_holder_name, account_holder_code
            ORDER BY account_holder_name
        """
        return self.bq.client.query(query).to_dataframe()

    def count_statements(
        self,
        iban: Optional[str] = None,
        date_range: Optional[tuple] = None,
    ) -> int:
        """Count statements with optional filters."""
        query = f"""
            SELECT COUNT(*) as count
            FROM `{self.bq.full_table_id("statements")}`
            WHERE 1=1
            {self._iban_filter(iban)}
            {self._date_filter("statement_date", date_range)}
        """
        result = self.bq.client.query(query).result()
        return next(result).count

    def count_transactions(
        self,
        iban: Optional[str] = None,
        date_range: Optional[tuple] = None,
    ) -> int:
        """Count transactions with optional filters."""
        query = f"""
            SELECT COUNT(*) as count
            FROM `{self.bq.full_table_id("transactions")}`
            WHERE 1=1
            {self._iban_filter(iban)}
            {self._date_filter("posting_date", date_range)}
        """
        result = self.bq.client.query(query).result()
        return next(result).count

    def count_failed_imports(self, date_range: Optional[tuple] = None) -> int:
        """Count failed imports in date range."""
        query = f"""
            SELECT COUNT(*) as count
            FROM `{self.bq.full_table_id("import_log")}`
            WHERE status = 'failed'
            {self._date_filter("DATE(started_at)", date_range)}
        """
        result = self.bq.client.query(query).result()
        return next(result).count

    def get_recent_imports(self, limit: int = 20) -> pd.DataFrame:
        """Get recent import log entries."""
        query = f"""
            SELECT
                started_at,
                source_filename,
                iban,
                statement_date,
                status,
                transactions_imported,
                error_message
            FROM `{self.bq.full_table_id("import_log")}`
            ORDER BY started_at DESC
            LIMIT {limit}
        """
        return self.bq.client.query(query).to_dataframe()

    def get_validation_issues(self, iban: Optional[str] = None) -> pd.DataFrame:
        """Get statements with balance validation issues."""
        query = f"""
            SELECT
                statement_id,
                iban,
                account_holder_name,
                statement_date,
                validation_errors
            FROM `{self.bq.full_table_id("statements")}`
            WHERE NOT balance_validated
            {self._iban_filter(iban)}
            ORDER BY statement_date DESC
        """
        return self.bq.client.query(query).to_dataframe()

    def get_transaction_volume(
        self,
        iban: Optional[str] = None,
        date_range: Optional[tuple] = None,
    ) -> pd.DataFrame:
        """Get daily transaction volume and totals."""
        query = f"""
            SELECT
                posting_date as date,
                COUNT(*) as count,
                SUM(ABS(signed_amount_eur)) as total_eur,
                SUM(CASE WHEN is_debit THEN amount_eur ELSE 0 END) as debit_eur,
                SUM(CASE WHEN NOT is_debit THEN amount_eur ELSE 0 END) as credit_eur
            FROM `{self.bq.full_table_id("transactions")}`
            WHERE 1=1
            {self._iban_filter(iban)}
            {self._date_filter("posting_date", date_range)}
            GROUP BY posting_date
            ORDER BY posting_date
        """
        return self.bq.client.query(query).to_dataframe()

    def get_transaction_types(
        self,
        iban: Optional[str] = None,
        date_range: Optional[tuple] = None,
    ) -> pd.DataFrame:
        """Get transaction breakdown by type."""
        query = f"""
            SELECT
                transaction_type,
                COUNT(*) as count,
                SUM(amount_eur) as total_eur,
                AVG(amount_eur) as avg_eur
            FROM `{self.bq.full_table_id("transactions")}`
            WHERE 1=1
            {self._iban_filter(iban)}
            {self._date_filter("posting_date", date_range)}
            GROUP BY transaction_type
            ORDER BY count DESC
        """
        return self.bq.client.query(query).to_dataframe()

    def get_top_counterparties(
        self,
        iban: Optional[str] = None,
        date_range: Optional[tuple] = None,
        limit: int = 10,
    ) -> pd.DataFrame:
        """Get top counterparties by transaction volume."""
        query = f"""
            SELECT
                counterparty_name,
                COUNT(*) as transaction_count,
                SUM(amount_eur) as total_eur
            FROM `{self.bq.full_table_id("transactions")}`
            WHERE counterparty_name IS NOT NULL
            {self._iban_filter(iban)}
            {self._date_filter("posting_date", date_range)}
            GROUP BY counterparty_name
            ORDER BY total_eur DESC
            LIMIT {limit}
        """
        return self.bq.client.query(query).to_dataframe()

    def get_balance_history(
        self,
        iban: Optional[str] = None,
        date_range: Optional[tuple] = None,
    ) -> pd.DataFrame:
        """Get closing balance history."""
        query = f"""
            SELECT
                statement_date,
                iban,
                account_holder_name,
                closing_balance_eur,
                closing_balance_bgn
            FROM `{self.bq.full_table_id("statements")}`
            WHERE 1=1
            {self._iban_filter(iban)}
            {self._date_filter("statement_date", date_range)}
            ORDER BY statement_date
        """
        return self.bq.client.query(query).to_dataframe()

    # =========================================================================
    # Transaction Browser Methods
    # =========================================================================

    def get_distinct_counterparties(
        self,
        ibans: Optional[list[str]] = None,
        date_range: Optional[tuple] = None,
        limit: int = 500,
    ) -> list[str]:
        """Get distinct counterparty names for filter dropdown."""
        query = f"""
            SELECT DISTINCT counterparty_name
            FROM `{self.bq.full_table_id("transactions")}`
            WHERE counterparty_name IS NOT NULL
            {self._multi_iban_filter(ibans)}
            {self._date_filter("posting_date", date_range)}
            ORDER BY counterparty_name
            LIMIT {limit}
        """
        result = self.bq.client.query(query).result()
        return [row.counterparty_name for row in result]

    def get_transactions(
        self,
        ibans: Optional[list[str]] = None,
        counterparties: Optional[list[str]] = None,
        transaction_types: Optional[list[str]] = None,
        date_range: Optional[tuple] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> pd.DataFrame:
        """Get paginated transactions with multi-filters."""
        query = f"""
            SELECT
                posting_date,
                iban,
                counterparty_name,
                description,
                transaction_type,
                amount_eur,
                signed_amount_eur,
                is_debit,
                reference
            FROM `{self.bq.full_table_id("transactions")}`
            WHERE 1=1
            {self._multi_iban_filter(ibans)}
            {self._multi_counterparty_filter(counterparties)}
            {self._multi_type_filter(transaction_types)}
            {self._date_filter("posting_date", date_range)}
            ORDER BY posting_date DESC, reference
            LIMIT {limit} OFFSET {offset}
        """
        return self.bq.client.query(query).to_dataframe()

    def count_filtered_transactions(
        self,
        ibans: Optional[list[str]] = None,
        counterparties: Optional[list[str]] = None,
        transaction_types: Optional[list[str]] = None,
        date_range: Optional[tuple] = None,
    ) -> int:
        """Count transactions matching filters for pagination."""
        query = f"""
            SELECT COUNT(*) as count
            FROM `{self.bq.full_table_id("transactions")}`
            WHERE 1=1
            {self._multi_iban_filter(ibans)}
            {self._multi_counterparty_filter(counterparties)}
            {self._multi_type_filter(transaction_types)}
            {self._date_filter("posting_date", date_range)}
        """
        result = self.bq.client.query(query).result()
        return next(result).count

    def get_transaction_aggregations(
        self,
        ibans: Optional[list[str]] = None,
        counterparties: Optional[list[str]] = None,
        transaction_types: Optional[list[str]] = None,
        date_range: Optional[tuple] = None,
    ) -> dict:
        """Get aggregated statistics for filtered transactions."""
        query = f"""
            SELECT
                COUNT(*) as total_count,
                COALESCE(SUM(CASE WHEN NOT is_debit THEN amount_eur ELSE 0 END), 0) as total_credits,
                COALESCE(SUM(CASE WHEN is_debit THEN amount_eur ELSE 0 END), 0) as total_debits,
                COALESCE(SUM(signed_amount_eur), 0) as net_amount
            FROM `{self.bq.full_table_id("transactions")}`
            WHERE 1=1
            {self._multi_iban_filter(ibans)}
            {self._multi_counterparty_filter(counterparties)}
            {self._multi_type_filter(transaction_types)}
            {self._date_filter("posting_date", date_range)}
        """
        result = self.bq.client.query(query).result()
        row = next(result)
        return {
            "total_count": row.total_count,
            "total_credits": float(row.total_credits),
            "total_debits": float(row.total_debits),
            "net_amount": float(row.net_amount),
        }

    def get_statements_with_pdfs(
        self,
        ibans: Optional[list[str]] = None,
        date_range: Optional[tuple] = None,
    ) -> pd.DataFrame:
        """Get statements with GCS PDF paths for download."""
        query = f"""
            SELECT
                statement_date,
                iban,
                account_holder_name,
                gcs_pdf_path,
                gcs_json_path,
                gcs_zip_path
            FROM `{self.bq.full_table_id("statements")}`
            WHERE 1=1
            {self._multi_iban_filter(ibans)}
            {self._date_filter("statement_date", date_range)}
            ORDER BY statement_date DESC, iban
        """
        return self.bq.client.query(query).to_dataframe()

    def get_all_transaction_types(self) -> list[str]:
        """Get all distinct transaction types from the database."""
        query = f"""
            SELECT DISTINCT transaction_type
            FROM `{self.bq.full_table_id("transactions")}`
            ORDER BY transaction_type
        """
        result = self.bq.client.query(query).result()
        return [row.transaction_type for row in result]

    def get_opening_balance_before_date(
        self,
        iban: str,
        before_date: date,
    ) -> Optional[float]:
        """Get the closing balance of the statement just before the given date."""
        query = f"""
            SELECT closing_balance_eur
            FROM `{self.bq.full_table_id("statements")}`
            WHERE iban = @iban AND statement_date < @before_date
            ORDER BY statement_date DESC
            LIMIT 1
        """
        from google.cloud import bigquery as bq_module
        job_config = bq_module.QueryJobConfig(
            query_parameters=[
                bq_module.ScalarQueryParameter("iban", "STRING", iban),
                bq_module.ScalarQueryParameter("before_date", "DATE", before_date.isoformat()),
            ]
        )
        result = self.bq.client.query(query, job_config=job_config).result()
        for row in result:
            return float(row.closing_balance_eur)
        return None

    def get_transactions_with_balance(
        self,
        iban: str,
        date_range: Optional[tuple] = None,
        counterparties: Optional[list[str]] = None,
        transaction_types: Optional[list[str]] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[pd.DataFrame, Optional[float]]:
        """
        Get transactions with running balance for a single IBAN.
        Returns (transactions_df, opening_balance).
        """
        # Get opening balance (closing balance of previous statement)
        start_date = date_range[0] if date_range else None
        opening_balance = None
        if start_date:
            opening_balance = self.get_opening_balance_before_date(iban, start_date)

        # Get transactions ordered by date ASC for running balance calculation
        query = f"""
            SELECT
                posting_date,
                iban,
                counterparty_name,
                description,
                transaction_type,
                CASE WHEN NOT is_debit THEN amount_eur ELSE NULL END as credit_eur,
                CASE WHEN is_debit THEN amount_eur ELSE NULL END as debit_eur,
                signed_amount_eur,
                is_debit,
                reference
            FROM `{self.bq.full_table_id("transactions")}`
            WHERE iban = '{iban}'
            {self._multi_counterparty_filter(counterparties)}
            {self._multi_type_filter(transaction_types)}
            {self._date_filter("posting_date", date_range)}
            ORDER BY posting_date ASC, reference ASC
        """
        df = self.bq.client.query(query).to_dataframe()

        # Calculate running balance
        if not df.empty and opening_balance is not None:
            df["running_balance"] = opening_balance + df["signed_amount_eur"].cumsum()
        elif not df.empty:
            df["running_balance"] = df["signed_amount_eur"].cumsum()
        else:
            df["running_balance"] = None

        # Apply pagination after calculation (reverse for DESC display)
        df = df.iloc[::-1].reset_index(drop=True)

        # Get total count before pagination
        total_count = len(df)

        # Apply pagination
        df = df.iloc[offset:offset + limit]

        return df, opening_balance, total_count

    # =========================================================================
    # Filter Helper Methods
    # =========================================================================

    def _iban_filter(self, iban: Optional[str]) -> str:
        """Build IBAN filter clause."""
        if iban and iban != "All":
            return f"AND iban = '{iban}'"
        return ""

    def _multi_iban_filter(self, ibans: Optional[list[str]]) -> str:
        """Build multi-IBAN filter clause."""
        if ibans and len(ibans) > 0:
            quoted = ", ".join(f"'{iban}'" for iban in ibans)
            return f"AND iban IN ({quoted})"
        return ""

    def _multi_counterparty_filter(self, counterparties: Optional[list[str]]) -> str:
        """Build multi-counterparty filter clause."""
        if counterparties and len(counterparties) > 0:
            # Escape single quotes in names
            escaped = [cp.replace("'", "''") for cp in counterparties]
            quoted = ", ".join(f"'{cp}'" for cp in escaped)
            return f"AND counterparty_name IN ({quoted})"
        return ""

    def _multi_type_filter(self, types: Optional[list[str]]) -> str:
        """Build multi-transaction-type filter clause."""
        if types and len(types) > 0:
            quoted = ", ".join(f"'{t}'" for t in types)
            return f"AND transaction_type IN ({quoted})"
        return ""

    def _date_filter(self, field: str, date_range: Optional[tuple]) -> str:
        """Build date range filter clause."""
        if date_range:
            start, end = date_range
            start_str = start.isoformat() if isinstance(start, date) else start
            end_str = end.isoformat() if isinstance(end, date) else end
            return f"AND {field} BETWEEN '{start_str}' AND '{end_str}'"
        return ""
