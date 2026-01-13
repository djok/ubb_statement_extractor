"""ID generation utilities for idempotency."""

import hashlib
from datetime import date
from decimal import Decimal

from ...models import StatementInfo, Transaction


def generate_statement_id(statement: StatementInfo) -> str:
    """
    Generate unique statement ID from immutable properties.

    Components:
    - IBAN (unique per account)
    - Statement date (unique per day)
    - Statement number (sequential, unique per account per year)
    - Opening balance EUR (additional uniqueness guarantee)

    Returns:
        32-character hex string (truncated SHA256)
    """
    components = [
        statement.iban,
        statement.statement_date.isoformat(),
        str(statement.statement_number),
        str(statement.opening_balance.eur),
    ]
    canonical = "|".join(components)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def generate_transaction_id(
    statement_id: str,
    transaction: Transaction,
    index: int,
) -> str:
    """
    Generate unique transaction ID.

    Uses statement_id + reference + index to ensure uniqueness
    even for transactions with same reference (e.g., fee after card transaction).

    Args:
        statement_id: Parent statement ID
        transaction: Transaction object
        index: Position in statement (0-based)

    Returns:
        32-character hex string (truncated SHA256)
    """
    components = [
        statement_id,
        transaction.reference,
        transaction.posting_date.isoformat(),
        str(transaction.amount.eur),
        str(transaction.is_debit),
        str(index),
    ]
    canonical = "|".join(components)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def generate_file_checksum(content: bytes) -> str:
    """
    Generate SHA256 checksum of file content.

    Args:
        content: File content as bytes

    Returns:
        64-character hex string (full SHA256)
    """
    return hashlib.sha256(content).hexdigest()
