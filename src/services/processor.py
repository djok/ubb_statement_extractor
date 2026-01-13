"""Email processing service for extracting bank statements."""

import base64
import io
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pyzipper

from ..api.schemas import PostalAttachment, PostalWebhook
from ..extractor import UBBStatementExtractor
from ..security import FileValidator, audit
from .storage import StatementUploader

logger = logging.getLogger(__name__)

# Check if GCS upload is enabled
GCS_ENABLED = bool(os.getenv("GCS_BUCKET"))


@dataclass
class ZipProcessingResult:
    """Result of processing a single ZIP file."""

    success: bool
    zip_filename: str
    json_filename: Optional[str] = None
    transactions_count: Optional[int] = None
    error: Optional[str] = None
    validation_errors: Optional[list[str]] = None
    bigquery_statement_id: Optional[str] = None
    bigquery_error: Optional[str] = None


@dataclass
class EmailProcessingResult:
    """Result of processing an email with potentially multiple ZIP attachments."""

    success: bool
    message: str
    email_id: int
    processed_zips: list[ZipProcessingResult]
    total_transactions: int = 0


class EmailProcessor:
    """Process incoming emails with ZIP attachments containing bank statements."""

    def __init__(self, data_dir: str = "/app/data"):
        """Initialize processor with data directory."""
        self.data_dir = Path(data_dir)
        self.zip_dir = self.data_dir / "zip"
        self.json_dir = self.data_dir / "json"
        self.raw_dir = self.data_dir / "raw"

        # Create directories
        for d in [self.zip_dir, self.json_dir, self.raw_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _save_raw(self, webhook: PostalWebhook) -> Path:
        """Save raw webhook payload for debugging."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        raw_file = self.raw_dir / f"postal_{timestamp}.json"

        with open(raw_file, "w", encoding="utf-8") as f:
            json.dump(webhook.model_dump(), f, indent=2, ensure_ascii=False)

        return raw_file

    def _process_zip(self, attachment: PostalAttachment) -> ZipProcessingResult:
        """Process a single ZIP attachment.

        Args:
            attachment: ZIP attachment from email

        Returns:
            ZipProcessingResult with processing details
        """
        logger.info(f"Processing ZIP: {attachment.filename} ({attachment.size} bytes)")

        # Sanitize filename to prevent path traversal
        try:
            safe_filename = FileValidator.sanitize_filename(attachment.filename)
        except ValueError as e:
            logger.warning(f"Invalid filename rejected: {attachment.filename}")
            audit.file_validation_failed(
                ip="webhook",
                filename=attachment.filename,
                reason=str(e)
            )
            return ZipProcessingResult(
                success=False,
                zip_filename=attachment.filename,
                error=f"Invalid filename: {e}",
            )

        try:
            # Validate base64 size before decoding
            is_valid, error = FileValidator.validate_base64_size(
                attachment.data, FileValidator.MAX_ZIP_SIZE
            )
            if not is_valid:
                logger.warning(f"Base64 data too large: {error}")
                audit.file_validation_failed(
                    ip="webhook",
                    filename=safe_filename,
                    reason=error or "Base64 data too large"
                )
                return ZipProcessingResult(
                    success=False,
                    zip_filename=safe_filename,
                    error=error,
                )

            # Decode ZIP data
            zip_data = base64.b64decode(attachment.data)

            # Validate ZIP for security issues (ZIP bomb, path traversal)
            is_valid, error = FileValidator.validate_zip(zip_data)
            if not is_valid:
                logger.warning(f"ZIP validation failed: {error}")
                audit.file_validation_failed(
                    ip="webhook",
                    filename=safe_filename,
                    reason=error or "ZIP validation failed"
                )
                return ZipProcessingResult(
                    success=False,
                    zip_filename=safe_filename,
                    error=error,
                )

            # Save ZIP file with sanitized filename
            zip_path = self.zip_dir / safe_filename
            zip_path.write_bytes(zip_data)
            logger.info(f"Saved ZIP to: {zip_path}")

            # Extract PDF from ZIP
            password = os.getenv("PDF_PASSWORD", "").encode()

            with pyzipper.AESZipFile(io.BytesIO(zip_data)) as zf:
                zf.setpassword(password)
                pdf_names = [n for n in zf.namelist() if n.lower().endswith(".pdf")]

                if not pdf_names:
                    return ZipProcessingResult(
                        success=False,
                        zip_filename=attachment.filename,
                        error="No PDF found in ZIP archive",
                    )

                pdf_name = pdf_names[0]
                pdf_data = zf.read(pdf_name)
                logger.info(f"Extracted PDF: {pdf_name}")

            # Write PDF to temp file for pdfplumber
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf_data)
                tmp_path = tmp.name

            try:
                # Parse PDF
                extractor = UBBStatementExtractor(tmp_path)
                statement = extractor.parse()
                logger.info(f"Parsed {len(statement.transactions)} transactions")

                # Validate balance
                validation = statement.validate_balance()
                if validation.is_valid:
                    logger.info(
                        f"Balance validation OK: "
                        f"opening {statement.statement.opening_balance.eur:.2f} EUR + "
                        f"credit {validation.total_credit_eur:.2f} - "
                        f"debit {validation.total_debit_eur:.2f} = "
                        f"closing {validation.calculated_closing_eur:.2f} EUR"
                    )
                else:
                    for error in validation.errors:
                        logger.error(f"Balance validation error: {error}")
                for warning in validation.warnings:
                    logger.warning(f"Balance validation warning: {warning}")

                # Save JSON locally
                json_filename = attachment.filename.replace(".zip", ".json")
                json_path = self.json_dir / json_filename
                json_content = statement.to_json()
                json_path.write_text(json_content, encoding="utf-8")
                logger.info(f"Saved JSON to: {json_path}")

                # Upload to GCS if enabled
                gcs_pdf_path = None
                gcs_json_path = None
                gcs_zip_path = None

                if GCS_ENABLED:
                    try:
                        uploader = StatementUploader()
                        iban = statement.statement.iban
                        stmt_date = statement.statement.statement_date

                        upload_result = uploader.upload_all(
                            iban=iban,
                            statement_date=stmt_date,
                            pdf_data=pdf_data,
                            json_data=json_content,
                            zip_data=zip_data,
                        )

                        gcs_pdf_path = upload_result.pdf_path
                        gcs_json_path = upload_result.json_path
                        gcs_zip_path = upload_result.zip_path
                        logger.info(f"Uploaded files to GCS: {iban}/{stmt_date}")

                    except Exception as e:
                        logger.warning(f"GCS upload failed (continuing anyway): {e}")

                # Import to BigQuery
                bigquery_statement_id = None
                bigquery_error = None
                try:
                    from .bigquery.importer import BigQueryImporter
                    from .bigquery.idempotency import generate_file_checksum
                    from .bigquery.exceptions import DuplicateStatementError, BigQueryError

                    importer = BigQueryImporter()
                    file_checksum = generate_file_checksum(json_path.read_bytes())

                    bigquery_statement_id = importer.import_statement(
                        statement=statement,
                        source_filename=json_filename,
                        source_checksum=file_checksum,
                        gcs_pdf_path=gcs_pdf_path,
                        gcs_json_path=gcs_json_path,
                        gcs_zip_path=gcs_zip_path,
                    )
                    logger.info(f"Imported to BigQuery: {bigquery_statement_id}")

                except DuplicateStatementError as e:
                    logger.warning(f"Duplicate statement skipped: {e}")
                    # Not an error - statement already imported
                except BigQueryError as e:
                    logger.error(f"BigQuery import failed: {e}")
                    bigquery_error = str(e)
                    # Raise to stop processing - per user requirement
                    raise

                return ZipProcessingResult(
                    success=True,
                    zip_filename=attachment.filename,
                    json_filename=json_filename,
                    transactions_count=len(statement.transactions),
                    validation_errors=validation.errors if not validation.is_valid else None,
                    bigquery_statement_id=bigquery_statement_id,
                    bigquery_error=bigquery_error,
                )

            finally:
                # Cleanup temp file
                os.unlink(tmp_path)

        except Exception as e:
            logger.exception(f"Error processing ZIP {attachment.filename}: {e}")
            return ZipProcessingResult(
                success=False,
                zip_filename=attachment.filename,
                error=str(e),
            )

    def process(self, webhook: PostalWebhook) -> EmailProcessingResult:
        """
        Process a Postal webhook with ZIP attachments.

        Handles multiple ZIP files in a single email.

        Args:
            webhook: Postal webhook payload

        Returns:
            EmailProcessingResult with success status and details for all ZIPs
        """
        logger.info(f"Processing email id={webhook.id} from {webhook.mail_from}")
        logger.info(f"Subject: {webhook.subject}")

        # Save raw payload for debugging
        self._save_raw(webhook)

        # Find all ZIP attachments (filter out images like UBB Logo)
        zip_attachments = [
            att for att in webhook.attachments if att.filename.lower().endswith(".zip")
        ]

        if not zip_attachments:
            logger.warning(f"No ZIP attachments found in email id={webhook.id}")
            return EmailProcessingResult(
                success=False,
                message="No ZIP attachments found",
                email_id=webhook.id,
                processed_zips=[],
            )

        logger.info(f"Found {len(zip_attachments)} ZIP attachment(s)")

        # Process each ZIP
        results: list[ZipProcessingResult] = []
        for att in zip_attachments:
            result = self._process_zip(att)
            results.append(result)

        # Calculate totals
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        total_transactions = sum(r.transactions_count or 0 for r in successful)

        # Determine overall success
        if not successful:
            message = f"All {len(failed)} ZIP(s) failed to process"
            success = False
        elif failed:
            message = f"Processed {len(successful)}/{len(results)} ZIP(s), {total_transactions} transactions"
            success = True  # Partial success
        else:
            message = f"Processed {len(successful)} ZIP(s), {total_transactions} transactions"
            success = True

        logger.info(f"Email id={webhook.id}: {message}")

        return EmailProcessingResult(
            success=success,
            message=message,
            email_id=webhook.id,
            processed_zips=results,
            total_transactions=total_transactions,
        )
