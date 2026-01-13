"""BigQuery import service with idempotency."""

import logging
import uuid
from datetime import datetime
from typing import Optional

from google.cloud import bigquery

from ...models import BankStatement, Transaction
from .client import BigQueryClient
from .idempotency import generate_statement_id, generate_transaction_id
from .exceptions import DuplicateStatementError, ImportError

logger = logging.getLogger(__name__)


class BigQueryImporter:
    """Service for importing bank statements to BigQuery."""

    BATCH_SIZE = 500

    def __init__(self):
        self.bq = BigQueryClient()

    def check_duplicate(self, statement_id: str) -> bool:
        """Check if statement already exists in BigQuery."""
        query = f"""
            SELECT 1 FROM `{self.bq.full_table_id("statements")}`
            WHERE statement_id = @statement_id
            LIMIT 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("statement_id", "STRING", statement_id)
            ]
        )

        result = self.bq.client.query(query, job_config=job_config).result()
        return result.total_rows > 0

    def import_statement(
        self,
        statement: BankStatement,
        source_filename: str,
        source_checksum: Optional[str] = None,
        gcs_pdf_path: Optional[str] = None,
        gcs_json_path: Optional[str] = None,
        gcs_zip_path: Optional[str] = None,
    ) -> str:
        """
        Import a bank statement to BigQuery.

        Args:
            statement: Parsed bank statement
            source_filename: Original filename for tracking
            source_checksum: SHA256 of source file
            gcs_pdf_path: GCS path for PDF file (without gs:// prefix)
            gcs_json_path: GCS path for JSON file (without gs:// prefix)
            gcs_zip_path: GCS path for ZIP file (without gs:// prefix)

        Returns:
            statement_id if successful

        Raises:
            DuplicateStatementError: If statement already imported
            ImportError: If import fails
        """
        import_id = str(uuid.uuid4())
        started_at = datetime.utcnow()

        statement_id = generate_statement_id(statement.statement)

        if self.check_duplicate(statement_id):
            self._log_import(
                import_id=import_id,
                source_filename=source_filename,
                source_checksum=source_checksum or "",
                statement_id=statement_id,
                iban=statement.statement.iban,
                statement_date=statement.statement.statement_date,
                status="duplicate",
                started_at=started_at,
            )
            raise DuplicateStatementError(
                f"Statement {statement_id} already exists "
                f"(IBAN: {statement.statement.iban}, "
                f"Date: {statement.statement.statement_date})"
            )

        try:
            validation = statement.validate_balance()

            statement_row = self._build_statement_row(
                statement_id=statement_id,
                statement=statement,
                source_filename=source_filename,
                source_checksum=source_checksum or "",
                validation=validation,
                gcs_pdf_path=gcs_pdf_path,
                gcs_json_path=gcs_json_path,
                gcs_zip_path=gcs_zip_path,
            )

            transaction_rows = [
                self._build_transaction_row(
                    transaction_id=generate_transaction_id(statement_id, tx, idx),
                    statement_id=statement_id,
                    statement=statement,
                    transaction=tx,
                )
                for idx, tx in enumerate(statement.transactions)
            ]

            errors = []

            stmt_errors = self.bq.client.insert_rows_json(
                self.bq.table("statements"),
                [statement_row],
            )
            errors.extend(stmt_errors)

            for i in range(0, len(transaction_rows), self.BATCH_SIZE):
                batch = transaction_rows[i : i + self.BATCH_SIZE]
                tx_errors = self.bq.client.insert_rows_json(
                    self.bq.table("transactions"),
                    batch,
                )
                errors.extend(tx_errors)

            if errors:
                raise ImportError(f"BigQuery insert errors: {errors}")

            self._log_import(
                import_id=import_id,
                source_filename=source_filename,
                source_checksum=source_checksum or "",
                statement_id=statement_id,
                iban=statement.statement.iban,
                statement_date=statement.statement.statement_date,
                status="success",
                started_at=started_at,
                transactions_count=len(statement.transactions),
            )

            logger.info(
                f"Imported statement {statement_id}: "
                f"{len(statement.transactions)} transactions "
                f"(IBAN: {statement.statement.iban})"
            )

            return statement_id

        except ImportError:
            raise
        except Exception as e:
            self._log_import(
                import_id=import_id,
                source_filename=source_filename,
                source_checksum=source_checksum or "",
                statement_id=None,
                iban=statement.statement.iban,
                statement_date=statement.statement.statement_date,
                status="failed",
                error_message=str(e),
                started_at=started_at,
            )
            raise ImportError(f"Import failed: {e}") from e

    def _build_statement_row(
        self,
        statement_id: str,
        statement: BankStatement,
        source_filename: str,
        source_checksum: str,
        validation,
        gcs_pdf_path: Optional[str] = None,
        gcs_json_path: Optional[str] = None,
        gcs_zip_path: Optional[str] = None,
    ) -> dict:
        """Build BigQuery row for statement."""
        s = statement.statement
        return {
            "statement_id": statement_id,
            "iban": s.iban,
            "account_number": s.iban[-10:],
            "account_holder_code": s.account_holder.code,
            "account_holder_name": s.account_holder.name,
            "account_holder_address": s.account_holder.address,
            "bank": s.bank,
            "currency": s.currency,
            "statement_number": s.statement_number,
            "statement_date": s.statement_date.isoformat(),
            "period_from": s.period.from_date.isoformat(),
            "period_to": s.period.to_date.isoformat(),
            "opening_balance_eur": float(s.opening_balance.eur),
            "opening_balance_bgn": float(s.opening_balance.bgn),
            "closing_balance_eur": float(s.closing_balance.eur),
            "closing_balance_bgn": float(s.closing_balance.bgn),
            "turnover_debit_eur": float(s.turnover.debit.eur),
            "turnover_debit_bgn": float(s.turnover.debit.bgn),
            "turnover_credit_eur": float(s.turnover.credit.eur),
            "turnover_credit_bgn": float(s.turnover.credit.bgn),
            "accumulated_debit_eur": float(s.accumulated_turnover.debit.eur),
            "accumulated_debit_bgn": float(s.accumulated_turnover.debit.bgn),
            "accumulated_credit_eur": float(s.accumulated_turnover.credit.eur),
            "accumulated_credit_bgn": float(s.accumulated_turnover.credit.bgn),
            "transaction_count": len(statement.transactions),
            "source_filename": source_filename,
            "imported_at": datetime.utcnow().isoformat(),
            "import_checksum": source_checksum,
            "balance_validated": validation.is_valid,
            "validation_errors": validation.errors if not validation.is_valid else [],
            "gcs_pdf_path": gcs_pdf_path,
            "gcs_json_path": gcs_json_path,
            "gcs_zip_path": gcs_zip_path,
        }

    def _build_transaction_row(
        self,
        transaction_id: str,
        statement_id: str,
        statement: BankStatement,
        transaction: Transaction,
    ) -> dict:
        """Build BigQuery row for transaction."""
        signed_eur = (
            -transaction.amount.eur if transaction.is_debit else transaction.amount.eur
        )
        signed_bgn = (
            -transaction.amount.bgn if transaction.is_debit else transaction.amount.bgn
        )

        return {
            "transaction_id": transaction_id,
            "statement_id": statement_id,
            "iban": statement.statement.iban,
            "account_number": statement.statement.iban[-10:],
            "posting_date": transaction.posting_date.isoformat(),
            "value_date": transaction.value_date.isoformat(),
            "reference": transaction.reference,
            "transaction_type": transaction.type.value,
            "description": transaction.description,
            "raw_description": transaction.raw_description,
            "counterparty_name": (
                transaction.counterparty.name if transaction.counterparty else None
            ),
            "counterparty_reference": (
                transaction.counterparty.reference if transaction.counterparty else None
            ),
            "counterparty_bank": (
                transaction.counterparty.bank if transaction.counterparty else None
            ),
            "counterparty_iban": (
                transaction.counterparty.iban if transaction.counterparty else None
            ),
            "amount_eur": float(transaction.amount.eur),
            "amount_bgn": float(transaction.amount.bgn),
            "is_debit": transaction.is_debit,
            "signed_amount_eur": float(signed_eur),
            "signed_amount_bgn": float(signed_bgn),
            "imported_at": datetime.utcnow().isoformat(),
        }

    def _log_import(
        self,
        import_id: str,
        source_filename: str,
        source_checksum: str,
        statement_id: Optional[str],
        iban: str,
        statement_date,
        status: str,
        started_at: datetime,
        error_message: Optional[str] = None,
        transactions_count: int = 0,
    ):
        """Log import attempt to import_log table."""
        row = {
            "import_id": import_id,
            "source_filename": source_filename,
            "source_checksum": source_checksum,
            "statement_id": statement_id,
            "iban": iban,
            "statement_date": (
                statement_date.isoformat() if statement_date else None
            ),
            "status": status,
            "error_message": error_message,
            "started_at": started_at.isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
            "transactions_imported": transactions_count,
        }

        try:
            self.bq.client.insert_rows_json(
                self.bq.table("import_log"),
                [row],
            )
        except Exception as e:
            logger.warning(f"Failed to log import: {e}")
