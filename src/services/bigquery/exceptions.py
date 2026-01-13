"""Custom exceptions for BigQuery operations."""


class BigQueryError(Exception):
    """Base exception for BigQuery operations."""

    pass


class DuplicateStatementError(BigQueryError):
    """Raised when attempting to import a duplicate statement."""

    pass


class ImportError(BigQueryError):
    """Raised when import fails."""

    pass


class ConnectionError(BigQueryError):
    """Raised when BigQuery connection fails."""

    pass


class ValidationError(BigQueryError):
    """Raised when data validation fails."""

    pass
