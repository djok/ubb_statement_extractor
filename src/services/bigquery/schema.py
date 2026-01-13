"""BigQuery table schema definitions."""

from google.cloud import bigquery


STATEMENTS_SCHEMA = [
    bigquery.SchemaField("statement_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("iban", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("account_number", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("account_holder_code", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("account_holder_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("account_holder_address", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("bank", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("currency", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("statement_number", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("statement_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("period_from", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("period_to", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("opening_balance_eur", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("opening_balance_bgn", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("closing_balance_eur", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("closing_balance_bgn", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("turnover_debit_eur", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("turnover_debit_bgn", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("turnover_credit_eur", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("turnover_credit_bgn", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("accumulated_debit_eur", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("accumulated_debit_bgn", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("accumulated_credit_eur", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("accumulated_credit_bgn", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("transaction_count", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("source_filename", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("imported_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("import_checksum", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("balance_validated", "BOOL", mode="REQUIRED"),
    bigquery.SchemaField("validation_errors", "STRING", mode="REPEATED"),
    # GCS file paths
    bigquery.SchemaField("gcs_pdf_path", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("gcs_json_path", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("gcs_zip_path", "STRING", mode="NULLABLE"),
]


TRANSACTIONS_SCHEMA = [
    bigquery.SchemaField("transaction_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("statement_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("iban", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("account_number", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("posting_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("value_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("reference", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("transaction_type", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("description", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("raw_description", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("counterparty_name", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("counterparty_reference", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("counterparty_bank", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("counterparty_iban", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("amount_eur", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("amount_bgn", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("is_debit", "BOOL", mode="REQUIRED"),
    bigquery.SchemaField("signed_amount_eur", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("signed_amount_bgn", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("imported_at", "TIMESTAMP", mode="REQUIRED"),
]


IMPORT_LOG_SCHEMA = [
    bigquery.SchemaField("import_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_filename", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_checksum", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("statement_id", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("iban", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("statement_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("error_message", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("started_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("completed_at", "TIMESTAMP", mode="NULLABLE"),
    bigquery.SchemaField("transactions_imported", "INT64", mode="NULLABLE"),
]


def get_statements_table(table_ref: bigquery.TableReference) -> bigquery.Table:
    """Create statements table definition with partitioning."""
    table = bigquery.Table(table_ref, schema=STATEMENTS_SCHEMA)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="statement_date",
    )
    table.clustering_fields = ["iban", "account_holder_code"]
    table.description = "UBB bank statement headers with account and balance information"
    return table


def get_transactions_table(table_ref: bigquery.TableReference) -> bigquery.Table:
    """Create transactions table definition with partitioning."""
    table = bigquery.Table(table_ref, schema=TRANSACTIONS_SCHEMA)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="posting_date",
    )
    table.clustering_fields = ["iban", "transaction_type"]
    table.description = "Individual bank transactions from UBB statements"
    return table


def get_import_log_table(table_ref: bigquery.TableReference) -> bigquery.Table:
    """Create import_log table definition with partitioning."""
    table = bigquery.Table(table_ref, schema=IMPORT_LOG_SCHEMA)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="started_at",
    )
    table.description = "Audit log for statement imports, tracking duplicates and failures"
    return table
