"""Gap detection for missing bank statements."""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Gap:
    """Represents a gap in statement dates."""

    iban: str
    account_holder_name: str
    gap_start: date
    gap_end: date
    missing_days: int

    @property
    def gap_range(self) -> str:
        """Format gap as date range string."""
        if self.missing_days == 1:
            return self.gap_start.isoformat()
        return f"{self.gap_start.isoformat()} - {self.gap_end.isoformat()}"


class GapDetector:
    """Detect missing bank statements."""

    DEFAULT_LOOKBACK_DAYS = 365

    def __init__(self):
        from ..services.bigquery.client import BigQueryClient

        self.bq = BigQueryClient()

    def detect_gaps(
        self,
        iban: Optional[str] = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> list[Gap]:
        """
        Detect gaps in statement dates.

        Args:
            iban: Optional IBAN filter
            lookback_days: How far back to check (default 365 days)

        Returns:
            List of Gap objects
        """
        cutoff_date = date.today() - timedelta(days=lookback_days)

        # Gap detection with balance check:
        # If closing_balance of previous statement equals opening_balance of current statement,
        # it means the bank wasn't operating (holidays/weekends) - not a real gap
        query = f"""
            WITH statement_dates AS (
                SELECT
                    iban,
                    account_holder_name,
                    statement_date,
                    opening_balance_eur,
                    closing_balance_eur,
                    LAG(statement_date) OVER (
                        PARTITION BY iban
                        ORDER BY statement_date
                    ) as prev_date,
                    LAG(closing_balance_eur) OVER (
                        PARTITION BY iban
                        ORDER BY statement_date
                    ) as prev_closing_balance
                FROM `{self.bq.full_table_id("statements")}`
                WHERE statement_date >= @cutoff_date
                {self._iban_filter(iban)}
            ),
            gaps AS (
                SELECT
                    iban,
                    account_holder_name,
                    prev_date,
                    statement_date,
                    DATE_DIFF(statement_date, prev_date, DAY) - 1 as missing_days,
                    prev_closing_balance,
                    opening_balance_eur
                FROM statement_dates
                WHERE prev_date IS NOT NULL
                AND DATE_DIFF(statement_date, prev_date, DAY) > 1
                -- Exclude gaps where balances match (bank wasn't operating)
                AND (prev_closing_balance IS NULL
                     OR opening_balance_eur IS NULL
                     OR prev_closing_balance != opening_balance_eur)
            )
            SELECT
                iban,
                account_holder_name,
                DATE_ADD(prev_date, INTERVAL 1 DAY) as gap_start,
                DATE_SUB(statement_date, INTERVAL 1 DAY) as gap_end,
                missing_days
            FROM gaps
            ORDER BY iban, gap_start
        """

        from google.cloud import bigquery

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    "cutoff_date", "DATE", cutoff_date.isoformat()
                )
            ]
        )

        result = self.bq.client.query(query, job_config=job_config).result()

        gaps = []
        for row in result:
            gaps.append(
                Gap(
                    iban=row.iban,
                    account_holder_name=row.account_holder_name,
                    gap_start=row.gap_start,
                    gap_end=row.gap_end,
                    missing_days=row.missing_days,
                )
            )

        return gaps

    def get_gaps_dataframe(
        self,
        iban: Optional[str] = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> pd.DataFrame:
        """
        Get gaps as a pandas DataFrame.

        Args:
            iban: Optional IBAN filter
            lookback_days: How far back to check

        Returns:
            DataFrame with gap information
        """
        gaps = self.detect_gaps(iban=iban, lookback_days=lookback_days)

        if not gaps:
            return pd.DataFrame(
                columns=[
                    "iban",
                    "account_holder_name",
                    "gap_start",
                    "gap_end",
                    "missing_days",
                ]
            )

        return pd.DataFrame(
            [
                {
                    "iban": g.iban,
                    "account_holder_name": g.account_holder_name,
                    "gap_start": g.gap_start,
                    "gap_end": g.gap_end,
                    "missing_days": g.missing_days,
                }
                for g in gaps
            ]
        )

    def get_coverage_summary(
        self,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> pd.DataFrame:
        """
        Get coverage summary per account.

        Returns DataFrame with:
        - iban
        - account_holder_name
        - first_statement
        - last_statement
        - total_statements
        - expected_statements (business days estimate)
        - gap_count
        - total_missing_days
        """
        cutoff_date = date.today() - timedelta(days=lookback_days)

        # Coverage summary with balance-aware gap detection
        query = f"""
            WITH statement_stats AS (
                SELECT
                    iban,
                    account_holder_name,
                    MIN(statement_date) as first_statement,
                    MAX(statement_date) as last_statement,
                    COUNT(*) as total_statements
                FROM `{self.bq.full_table_id("statements")}`
                WHERE statement_date >= @cutoff_date
                GROUP BY iban, account_holder_name
            ),
            gap_stats AS (
                SELECT
                    iban,
                    COUNT(*) as gap_count,
                    SUM(DATE_DIFF(statement_date, prev_date, DAY) - 1) as total_missing
                FROM (
                    SELECT
                        iban,
                        statement_date,
                        opening_balance_eur,
                        LAG(statement_date) OVER (
                            PARTITION BY iban ORDER BY statement_date
                        ) as prev_date,
                        LAG(closing_balance_eur) OVER (
                            PARTITION BY iban ORDER BY statement_date
                        ) as prev_closing_balance
                    FROM `{self.bq.full_table_id("statements")}`
                    WHERE statement_date >= @cutoff_date
                )
                WHERE prev_date IS NOT NULL
                AND DATE_DIFF(statement_date, prev_date, DAY) > 1
                -- Exclude gaps where balances match (bank wasn't operating)
                AND (prev_closing_balance IS NULL
                     OR opening_balance_eur IS NULL
                     OR prev_closing_balance != opening_balance_eur)
                GROUP BY iban
            )
            SELECT
                s.iban,
                s.account_holder_name,
                s.first_statement,
                s.last_statement,
                s.total_statements,
                COALESCE(g.gap_count, 0) as gap_count,
                COALESCE(g.total_missing, 0) as total_missing_days
            FROM statement_stats s
            LEFT JOIN gap_stats g ON s.iban = g.iban
            ORDER BY s.account_holder_name
        """

        from google.cloud import bigquery

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    "cutoff_date", "DATE", cutoff_date.isoformat()
                )
            ]
        )

        return self.bq.client.query(query, job_config=job_config).to_dataframe()

    def _iban_filter(self, iban: Optional[str]) -> str:
        """Build IBAN filter clause."""
        if iban and iban != "All":
            return f"AND iban = '{iban}'"
        return ""
