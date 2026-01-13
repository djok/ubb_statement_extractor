#!/usr/bin/env python3
"""Batch import ZIP files: extract PDFs, parse to JSON, and import to BigQuery."""

import argparse
import json
import logging
import os
import sys
import tempfile
import shutil
from pathlib import Path

import pyzipper
from dotenv import load_dotenv

from .extractor import UBBStatementExtractor
from .models import BankStatement
from .services.bigquery.client import BigQueryClient
from .services.bigquery.importer import BigQueryImporter
from .services.bigquery.idempotency import generate_file_checksum
from .services.bigquery.exceptions import DuplicateStatementError, BigQueryError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def extract_zip(zip_path: Path, password: str, temp_dir: str) -> str:
    """Extract PDF from password-protected ZIP file."""
    with pyzipper.AESZipFile(str(zip_path), "r") as zf:
        zf.setpassword(password.encode())
        pdf_files = [name for name in zf.namelist() if name.lower().endswith(".pdf")]
        if not pdf_files:
            raise ValueError("No PDF file found in ZIP archive")
        pdf_name = pdf_files[0]
        zf.extract(pdf_name, temp_dir)
        return os.path.join(temp_dir, pdf_name)


def process_zip(
    zip_path: Path,
    password: str,
    json_output_dir: Path,
    importer: BigQueryImporter,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """
    Process a single ZIP file: extract PDF, parse, save JSON, import to BigQuery.

    Returns:
        Tuple of (success, status_message)
    """
    temp_dir = None
    try:
        # Extract PDF from ZIP
        temp_dir = tempfile.mkdtemp()
        pdf_path = extract_zip(zip_path, password, temp_dir)
        logger.info(f"  Extracted PDF: {Path(pdf_path).name}")

        # Parse PDF
        extractor = UBBStatementExtractor(pdf_path)
        statement = extractor.parse()

        logger.info(
            f"  IBAN: {statement.statement.iban}, "
            f"Date: {statement.statement.statement_date}, "
            f"Transactions: {len(statement.transactions)}"
        )

        # Validate balance
        validation = statement.validate_balance()
        if not validation.is_valid:
            for error in validation.errors:
                logger.warning(f"  Validation: {error}")

        # Save JSON
        json_filename = f"{zip_path.stem}.json"
        json_path = json_output_dir / json_filename
        json_content = statement.to_json(indent=2)

        if not dry_run:
            json_output_dir.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json_content, encoding="utf-8")
            logger.info(f"  Saved JSON: {json_path.name}")

        # Import to BigQuery
        if dry_run:
            logger.info("  [DRY RUN] Would import to BigQuery")
            return True, "dry_run"

        checksum = generate_file_checksum(json_content.encode("utf-8"))
        statement_id = importer.import_statement(
            statement=statement,
            source_filename=json_filename,
            source_checksum=checksum,
        )
        logger.info(f"  Imported to BigQuery: {statement_id}")
        return True, "success"

    except DuplicateStatementError as e:
        logger.warning(f"  Skipped (duplicate): {e}")
        return True, "duplicate"

    except BigQueryError as e:
        logger.error(f"  BigQuery error: {e}")
        return False, f"bigquery_error: {e}"

    except Exception as e:
        logger.exception(f"  Error: {e}")
        return False, f"error: {e}"

    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Batch import ZIP files to BigQuery"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="/app/data/zip",
        help="Path to ZIP file or directory (default: /app/data/zip)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="/app/data/json",
        help="Output directory for JSON files (default: /app/data/json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate files without importing",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Create BigQuery dataset and tables if they don't exist",
    )

    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    password = os.getenv("PDF_PASSWORD", "")
    if not password:
        logger.error("PDF_PASSWORD not set in environment")
        sys.exit(1)

    path = Path(args.path)
    json_output_dir = Path(args.output)

    # Setup BigQuery
    if args.setup:
        logger.info("Setting up BigQuery dataset and tables...")
        client = BigQueryClient()
        client.setup()
        logger.info("Setup complete")

    # Initialize importer
    importer = BigQueryImporter()

    # Find ZIP files
    if path.is_file():
        zip_files = [path]
    elif path.is_dir():
        zip_files = sorted(path.glob("*.zip"))
    else:
        logger.error(f"Path not found: {path}")
        sys.exit(1)

    if not zip_files:
        logger.warning(f"No ZIP files found in {path}")
        sys.exit(0)

    logger.info(f"Found {len(zip_files)} ZIP file(s)")

    # Process files
    results = {"success": 0, "duplicate": 0, "failed": 0}

    for zip_path in zip_files:
        logger.info(f"Processing: {zip_path.name}")
        success, status = process_zip(
            zip_path=zip_path,
            password=password,
            json_output_dir=json_output_dir,
            importer=importer,
            dry_run=args.dry_run,
        )

        if success:
            if status == "duplicate":
                results["duplicate"] += 1
            else:
                results["success"] += 1
        else:
            results["failed"] += 1

    # Summary
    logger.info(
        f"\nSummary: {results['success']} imported, "
        f"{results['duplicate']} duplicates, "
        f"{results['failed']} failed"
    )

    if results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
