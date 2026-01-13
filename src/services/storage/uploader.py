"""Statement file uploader for Google Cloud Storage."""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .client import GCSClient

logger = logging.getLogger(__name__)


@dataclass
class UploadResult:
    """Result of uploading statement files to GCS."""

    pdf_path: Optional[str] = None
    json_path: Optional[str] = None
    zip_path: Optional[str] = None


class StatementUploader:
    """Upload statement files to GCS with structured paths.

    Path structure: {IBAN}/{YYYY}/{MM}/{DD}/{filename}
    Example: BG12UBBS12345678901234/2024/01/15/statement.pdf
    """

    def __init__(self):
        self.gcs = GCSClient()

    def build_path(self, iban: str, statement_date: date, filename: str) -> str:
        """Build GCS path for a file.

        Args:
            iban: Account IBAN (e.g., BG12UBBS12345678901234)
            statement_date: Statement date
            filename: Filename (e.g., statement.pdf)

        Returns:
            GCS path like: BG12UBBS.../2024/01/15/statement.pdf
        """
        return (
            f"{iban}/"
            f"{statement_date.year}/"
            f"{statement_date.month:02d}/"
            f"{statement_date.day:02d}/"
            f"{filename}"
        )

    def upload_pdf(self, iban: str, statement_date: date, pdf_data: bytes) -> str:
        """Upload PDF and return GCS path (without gs:// prefix).

        Args:
            iban: Account IBAN
            statement_date: Statement date
            pdf_data: PDF file content

        Returns:
            GCS path (e.g., BG12UBBS.../2024/01/15/statement.pdf)
        """
        path = self.build_path(iban, statement_date, "statement.pdf")
        self.gcs.upload_bytes(path, pdf_data, content_type="application/pdf")
        logger.info(f"Uploaded PDF: {path}")
        return path

    def upload_json(self, iban: str, statement_date: date, json_data: str) -> str:
        """Upload JSON and return GCS path (without gs:// prefix).

        Args:
            iban: Account IBAN
            statement_date: Statement date
            json_data: JSON string content

        Returns:
            GCS path (e.g., BG12UBBS.../2024/01/15/statement.json)
        """
        path = self.build_path(iban, statement_date, "statement.json")
        self.gcs.upload_string(path, json_data, content_type="application/json")
        logger.info(f"Uploaded JSON: {path}")
        return path

    def upload_zip(self, iban: str, statement_date: date, zip_data: bytes) -> str:
        """Upload original ZIP and return GCS path (without gs:// prefix).

        Args:
            iban: Account IBAN
            statement_date: Statement date
            zip_data: ZIP file content

        Returns:
            GCS path (e.g., BG12UBBS.../2024/01/15/original.zip)
        """
        path = self.build_path(iban, statement_date, "original.zip")
        self.gcs.upload_bytes(path, zip_data, content_type="application/zip")
        logger.info(f"Uploaded ZIP: {path}")
        return path

    def upload_all(
        self,
        iban: str,
        statement_date: date,
        pdf_data: Optional[bytes] = None,
        json_data: Optional[str] = None,
        zip_data: Optional[bytes] = None,
    ) -> UploadResult:
        """Upload all provided files and return their paths.

        Args:
            iban: Account IBAN
            statement_date: Statement date
            pdf_data: Optional PDF content
            json_data: Optional JSON content
            zip_data: Optional ZIP content

        Returns:
            UploadResult with paths for each uploaded file
        """
        result = UploadResult()

        if pdf_data:
            result.pdf_path = self.upload_pdf(iban, statement_date, pdf_data)

        if json_data:
            result.json_path = self.upload_json(iban, statement_date, json_data)

        if zip_data:
            result.zip_path = self.upload_zip(iban, statement_date, zip_data)

        return result

    def get_signed_url(self, gcs_path: str, expiration_minutes: int = 15) -> str:
        """Generate a signed URL for downloading a file.

        Args:
            gcs_path: Path in GCS (without gs:// prefix)
            expiration_minutes: URL validity in minutes

        Returns:
            Signed URL for download
        """
        return self.gcs.get_signed_url(gcs_path, expiration_minutes)

    def file_exists(self, iban: str, statement_date: date, filename: str) -> bool:
        """Check if a file already exists in GCS.

        Args:
            iban: Account IBAN
            statement_date: Statement date
            filename: Filename to check

        Returns:
            True if file exists
        """
        path = self.build_path(iban, statement_date, filename)
        return self.gcs.blob_exists(path)
