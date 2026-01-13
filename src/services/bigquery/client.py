"""BigQuery client wrapper with connection management."""

import logging
import os
from typing import Optional

from google.cloud import bigquery
from google.oauth2 import service_account

from .exceptions import ConnectionError

logger = logging.getLogger(__name__)


class BigQueryClient:
    """Singleton BigQuery client with lazy initialization."""

    _instance: Optional["BigQueryClient"] = None

    # Configuration from environment variables
    DEFAULT_PROJECT_ID = "your-gcp-project-id"
    DEFAULT_DATASET_ID = "ubb_statements"
    DEFAULT_CREDENTIALS_PATH = "/app/secrets/gcp-credentials.json"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # Get configuration from environment
        self.PROJECT_ID = os.getenv("BIGQUERY_PROJECT_ID", self.DEFAULT_PROJECT_ID)
        self.DATASET_ID = os.getenv("BIGQUERY_DATASET", self.DEFAULT_DATASET_ID)

        try:
            creds_path = os.getenv(
                "GOOGLE_APPLICATION_CREDENTIALS", self.DEFAULT_CREDENTIALS_PATH
            )
            credentials = service_account.Credentials.from_service_account_file(
                creds_path
            )

            # Use project from credentials if not explicitly set
            if self.PROJECT_ID == self.DEFAULT_PROJECT_ID:
                self.PROJECT_ID = credentials.project_id

            self.client = bigquery.Client(
                project=self.PROJECT_ID, credentials=credentials
            )
            self.dataset_ref = self.client.dataset(self.DATASET_ID)
            self._initialized = True

            logger.info(
                f"BigQuery client initialized for project {self.PROJECT_ID}, "
                f"dataset {self.DATASET_ID}"
            )

        except Exception as e:
            raise ConnectionError(f"Failed to initialize BigQuery client: {e}") from e

    def table(self, table_name: str) -> bigquery.TableReference:
        """Get reference to a table in the dataset."""
        return self.dataset_ref.table(table_name)

    def full_table_id(self, table_name: str) -> str:
        """Get fully qualified table ID."""
        return f"{self.PROJECT_ID}.{self.DATASET_ID}.{table_name}"

    def ensure_dataset(self) -> None:
        """Create dataset if it doesn't exist."""
        dataset = bigquery.Dataset(self.dataset_ref)
        dataset.location = "EU"
        self.client.create_dataset(dataset, exists_ok=True)
        logger.info(f"Dataset {self.DATASET_ID} ensured")

    def ensure_tables(self) -> None:
        """Create tables if they don't exist."""
        from .schema import get_statements_table, get_transactions_table, get_import_log_table

        tables = [
            get_statements_table(self.table("statements")),
            get_transactions_table(self.table("transactions")),
            get_import_log_table(self.table("import_log")),
        ]

        for table in tables:
            self.client.create_table(table, exists_ok=True)
            logger.info(f"Table {table.table_id} ensured")

    def setup(self) -> None:
        """Initialize dataset and tables."""
        self.ensure_dataset()
        self.ensure_tables()
        logger.info("BigQuery setup completed")

    def delete_statement(self, statement_id: str) -> int:
        """Delete a statement and its transactions from BigQuery.

        Args:
            statement_id: The statement ID to delete

        Returns:
            Number of transactions deleted
        """
        # Delete transactions first
        tx_query = f"""
            DELETE FROM `{self.full_table_id("transactions")}`
            WHERE statement_id = @statement_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("statement_id", "STRING", statement_id)
            ]
        )
        result = self.client.query(tx_query, job_config=job_config).result()
        tx_deleted = result.num_dml_affected_rows or 0

        # Delete statement
        stmt_query = f"""
            DELETE FROM `{self.full_table_id("statements")}`
            WHERE statement_id = @statement_id
        """
        self.client.query(stmt_query, job_config=job_config).result()

        logger.info(f"Deleted statement {statement_id} and {tx_deleted} transactions")
        return tx_deleted

    def truncate_all_tables(self) -> dict:
        """Truncate all tables. Much faster than DELETE and ignores streaming buffer.

        Returns:
            Dict with truncated table names
        """
        results = {}

        for table in ["transactions", "statements", "import_log"]:
            query = f"TRUNCATE TABLE `{self.full_table_id(table)}`"
            self.client.query(query).result()
            results[table] = "truncated"
            logger.info(f"Truncated table {table}")

        return results
