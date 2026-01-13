"""Migration script to upload existing local files to Google Cloud Storage.

This script:
1. Scans /app/data/zip for all ZIP files
2. For each ZIP, extracts PDF and parses to get IBAN and statement_date
3. Uploads ZIP, PDF, and corresponding JSON to GCS
4. Updates BigQuery records with GCS paths

Usage:
    docker-compose run --rm extractor python -m src.migrate_to_gcs [--dry-run]
"""

import argparse
import io
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import pyzipper

from src.extractor import UBBStatementExtractor
from src.services.storage import StatementUploader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def update_bigquery_gcs_paths(
    iban: str,
    statement_date,
    gcs_pdf_path: str,
    gcs_json_path: str,
    gcs_zip_path: str,
) -> bool:
    """Update BigQuery record with GCS paths."""
    from src.services.bigquery.client import BigQueryClient

    bq = BigQueryClient()

    query = f"""
        UPDATE `{bq.full_table_id("statements")}`
        SET
            gcs_pdf_path = @gcs_pdf_path,
            gcs_json_path = @gcs_json_path,
            gcs_zip_path = @gcs_zip_path
        WHERE iban = @iban AND statement_date = @statement_date
    """

    from google.cloud import bigquery

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("gcs_pdf_path", "STRING", gcs_pdf_path),
            bigquery.ScalarQueryParameter("gcs_json_path", "STRING", gcs_json_path),
            bigquery.ScalarQueryParameter("gcs_zip_path", "STRING", gcs_zip_path),
            bigquery.ScalarQueryParameter("iban", "STRING", iban),
            bigquery.ScalarQueryParameter(
                "statement_date", "DATE", statement_date.isoformat()
            ),
        ]
    )

    try:
        job = bq.client.query(query, job_config=job_config)
        job.result()
        return job.num_dml_affected_rows > 0
    except Exception as e:
        logger.error(f"Failed to update BigQuery: {e}")
        return False


def migrate_zip_file(zip_path: Path, json_dir: Path, dry_run: bool = False) -> bool:
    """Migrate a single ZIP file and its corresponding JSON to GCS.

    Args:
        zip_path: Path to the ZIP file
        json_dir: Directory containing JSON files
        dry_run: If True, don't actually upload

    Returns:
        True if successful
    """
    logger.info(f"Processing: {zip_path.name}")

    password = os.getenv("PDF_PASSWORD", "").encode()

    try:
        # Read ZIP
        zip_data = zip_path.read_bytes()

        # Extract PDF
        with pyzipper.AESZipFile(io.BytesIO(zip_data)) as zf:
            zf.setpassword(password)
            pdf_names = [n for n in zf.namelist() if n.lower().endswith(".pdf")]

            if not pdf_names:
                logger.warning(f"No PDF in {zip_path.name}, skipping")
                return False

            pdf_data = zf.read(pdf_names[0])

        # Parse PDF to get metadata
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_data)
            tmp_path = tmp.name

        try:
            extractor = UBBStatementExtractor(tmp_path)
            statement = extractor.parse()
        finally:
            os.unlink(tmp_path)

        iban = statement.statement.iban
        stmt_date = statement.statement.statement_date

        # Find corresponding JSON
        json_filename = zip_path.name.replace(".zip", ".json")
        json_path = json_dir / json_filename

        json_data = None
        if json_path.exists():
            json_data = json_path.read_text(encoding="utf-8")
        else:
            # Generate JSON if not found
            json_data = statement.to_json()
            logger.warning(f"JSON not found, regenerated: {json_filename}")

        if dry_run:
            logger.info(
                f"[DRY RUN] Would upload to: {iban}/{stmt_date.year}/"
                f"{stmt_date.month:02d}/{stmt_date.day:02d}/"
            )
            return True

        # Upload to GCS
        uploader = StatementUploader()

        # Check if already uploaded
        if uploader.file_exists(iban, stmt_date, "statement.pdf"):
            logger.info(f"Already exists in GCS, skipping: {iban}/{stmt_date}")
            return True

        upload_result = uploader.upload_all(
            iban=iban,
            statement_date=stmt_date,
            pdf_data=pdf_data,
            json_data=json_data,
            zip_data=zip_data,
        )

        logger.info(f"Uploaded to GCS: {iban}/{stmt_date}")

        # Update BigQuery
        updated = update_bigquery_gcs_paths(
            iban=iban,
            statement_date=stmt_date,
            gcs_pdf_path=upload_result.pdf_path,
            gcs_json_path=upload_result.json_path,
            gcs_zip_path=upload_result.zip_path,
        )

        if updated:
            logger.info(f"Updated BigQuery record: {iban}/{stmt_date}")
        else:
            logger.warning(f"BigQuery record not found for: {iban}/{stmt_date}")

        return True

    except Exception as e:
        logger.error(f"Failed to process {zip_path.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Migrate local files to GCS")
    parser.add_argument(
        "--data-dir",
        type=str,
        default="/app/data",
        help="Data directory path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually upload, just show what would happen",
    )
    args = parser.parse_args()

    if not os.getenv("GCS_BUCKET"):
        logger.error("GCS_BUCKET environment variable is not set")
        sys.exit(1)

    data_dir = Path(args.data_dir)
    zip_dir = data_dir / "zip"
    json_dir = data_dir / "json"

    if not zip_dir.exists():
        logger.error(f"ZIP directory not found: {zip_dir}")
        sys.exit(1)

    zip_files = sorted(zip_dir.glob("*.zip"))
    logger.info(f"Found {len(zip_files)} ZIP files to migrate")

    if args.dry_run:
        logger.info("=== DRY RUN MODE - No changes will be made ===")

    success = 0
    failed = 0

    for zip_path in zip_files:
        if migrate_zip_file(zip_path, json_dir, args.dry_run):
            success += 1
        else:
            failed += 1

    logger.info("=" * 50)
    logger.info(f"Migration complete: {success} success, {failed} failed")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
