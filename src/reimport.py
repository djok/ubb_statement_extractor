#!/usr/bin/env python3
"""Re-import existing JSON files to BigQuery."""

import argparse
import json
import logging
import sys
from pathlib import Path

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


def reimport_json(json_path: Path, dry_run: bool = False) -> bool:
    """
    Re-import a single JSON file to BigQuery.

    Args:
        json_path: Path to JSON file
        dry_run: If True, only validate without importing

    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Processing: {json_path.name}")

    try:
        # Read and parse JSON
        content = json_path.read_text(encoding="utf-8")
        data = json.loads(content)
        statement = BankStatement.model_validate(data)

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

        if dry_run:
            logger.info("  [DRY RUN] Would import to BigQuery")
            return True

        # Import to BigQuery
        importer = BigQueryImporter()
        checksum = generate_file_checksum(content.encode("utf-8"))

        statement_id = importer.import_statement(
            statement=statement,
            source_filename=json_path.name,
            source_checksum=checksum,
        )

        logger.info(f"  Imported: {statement_id}")
        return True

    except DuplicateStatementError as e:
        logger.warning(f"  Skipped (duplicate): {e}")
        return True  # Not an error

    except BigQueryError as e:
        logger.error(f"  BigQuery error: {e}")
        return False

    except Exception as e:
        logger.exception(f"  Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Re-import existing JSON files to BigQuery"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="/app/data/json",
        help="Path to JSON file or directory (default: /app/data/json)",
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
    path = Path(args.path)

    # Setup BigQuery
    if args.setup:
        logger.info("Setting up BigQuery dataset and tables...")
        client = BigQueryClient()
        client.setup()
        logger.info("Setup complete")

    # Find JSON files
    if path.is_file():
        json_files = [path]
    elif path.is_dir():
        json_files = sorted(path.glob("*.json"))
    else:
        logger.error(f"Path not found: {path}")
        sys.exit(1)

    if not json_files:
        logger.warning(f"No JSON files found in {path}")
        sys.exit(0)

    logger.info(f"Found {len(json_files)} JSON file(s)")

    # Process files
    success = 0
    failed = 0

    for json_path in json_files:
        if reimport_json(json_path, dry_run=args.dry_run):
            success += 1
        else:
            failed += 1

    # Summary
    logger.info(f"\nSummary: {success} successful, {failed} failed")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
