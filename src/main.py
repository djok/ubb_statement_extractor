#!/usr/bin/env python3
"""Main entry point for UBB Statement Extractor."""

import argparse
import os
import sys
import tempfile
from pathlib import Path

import pyzipper
from dotenv import load_dotenv

from .extractor import UBBStatementExtractor


def extract_zip(zip_path: str, password: str, temp_dir: str) -> str:
    """Extract PDF from password-protected ZIP file.

    Args:
        zip_path: Path to the ZIP file
        password: Password for the ZIP file
        temp_dir: Temporary directory to extract to

    Returns:
        Path to the extracted PDF file
    """
    with pyzipper.AESZipFile(zip_path, "r") as zf:
        zf.setpassword(password.encode())

        # Find the PDF file in the archive
        pdf_files = [name for name in zf.namelist() if name.lower().endswith(".pdf")]

        if not pdf_files:
            raise ValueError("No PDF file found in ZIP archive")

        # Extract the first PDF
        pdf_name = pdf_files[0]
        zf.extract(pdf_name, temp_dir)

        return os.path.join(temp_dir, pdf_name)


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Extract UBB bank statement data from PDF to JSON"
    )
    parser.add_argument(
        "input_file",
        help="Input file (ZIP or PDF)"
    )
    parser.add_argument(
        "output_file",
        nargs="?",
        help="Output JSON file (optional, defaults to output/<input_name>.json)"
    )

    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    input_path = Path(args.input_file)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Determine output path
    if args.output_file:
        output_path = Path(args.output_file)
    else:
        # Default output path
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"{input_path.stem}.json"

    # Process the file
    pdf_path = None
    temp_dir = None

    try:
        if input_path.suffix.lower() == ".zip":
            # Extract from ZIP
            password = os.getenv("PDF_PASSWORD", "")
            if not password:
                print("Error: PDF_PASSWORD not set in environment", file=sys.stderr)
                sys.exit(1)

            temp_dir = tempfile.mkdtemp()
            print(f"Extracting ZIP file: {input_path}")
            pdf_path = extract_zip(str(input_path), password, temp_dir)
            print(f"Extracted PDF: {pdf_path}")
        else:
            pdf_path = str(input_path)

        # Parse the PDF
        print(f"Parsing PDF: {pdf_path}")
        extractor = UBBStatementExtractor(pdf_path)
        statement = extractor.parse()

        # Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)

        json_output = statement.to_json(indent=2)
        output_path.write_text(json_output, encoding="utf-8")

        print(f"Output written to: {output_path}")
        print(f"Total transactions: {len(statement.transactions)}")
        print(f"Opening balance: {statement.statement.opening_balance.eur} EUR")
        print(f"Closing balance: {statement.statement.closing_balance.eur} EUR")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    finally:
        # Cleanup temp directory
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    main()
