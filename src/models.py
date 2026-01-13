"""Pydantic models for UBB bank statement data."""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TransactionType(str, Enum):
    """Types of transactions in UBB statements."""
    SEPA_INCOMING = "SEPA_INCOMING"
    SEPA_OUTGOING = "SEPA_OUTGOING"
    CARD_TRANSACTION = "CARD_TRANSACTION"
    FEE = "FEE"
    TRANSFER_FEE = "TRANSFER_FEE"
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"
    CURRENCY_EXCHANGE = "CURRENCY_EXCHANGE"
    UNKNOWN = "UNKNOWN"


class Balance(BaseModel):
    """Balance in EUR and BGN."""
    eur: Decimal
    bgn: Decimal


class Turnover(BaseModel):
    """Turnover with debit and credit."""
    debit: Balance
    credit: Balance


class AccountHolder(BaseModel):
    """Account holder information."""
    code: str
    name: str
    address: str


class Period(BaseModel):
    """Statement period."""
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")

    class Config:
        populate_by_name = True


class Counterparty(BaseModel):
    """Counterparty information for a transaction."""
    name: Optional[str] = None
    reference: Optional[str] = None
    bank: Optional[str] = None
    iban: Optional[str] = None


class Transaction(BaseModel):
    """Single transaction entry."""
    posting_date: date
    value_date: date
    reference: str
    type: TransactionType
    description: str
    raw_description: str
    counterparty: Optional[Counterparty] = None
    amount: Balance
    is_debit: bool


class StatementInfo(BaseModel):
    """Statement metadata."""
    bank: str = "UBB"
    account_holder: AccountHolder
    iban: str
    currency: str
    period: Period
    statement_number: int
    statement_date: date
    opening_balance: Balance
    closing_balance: Balance
    turnover: Turnover
    accumulated_turnover: Turnover


class ValidationResult(BaseModel):
    """Result of balance validation."""

    is_valid: bool
    errors: list[str] = []
    warnings: list[str] = []

    # Calculated values
    calculated_closing_eur: Optional[Decimal] = None
    calculated_closing_bgn: Optional[Decimal] = None
    expected_closing_eur: Optional[Decimal] = None
    expected_closing_bgn: Optional[Decimal] = None

    # Transaction sums
    total_debit_eur: Optional[Decimal] = None
    total_credit_eur: Optional[Decimal] = None
    total_debit_bgn: Optional[Decimal] = None
    total_credit_bgn: Optional[Decimal] = None


class BankStatement(BaseModel):
    """Complete bank statement with all transactions."""

    statement: StatementInfo
    transactions: list[Transaction]

    def validate_balance(self) -> ValidationResult:
        """
        Validate that the statement balances are correct.

        Checks:
        1. Opening balance + Credits - Debits = Closing balance
        2. Sum of transaction amounts matches reported turnover

        Returns:
            ValidationResult with is_valid flag and any errors/warnings
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Calculate totals from transactions
        total_debit_eur = Decimal("0")
        total_credit_eur = Decimal("0")
        total_debit_bgn = Decimal("0")
        total_credit_bgn = Decimal("0")

        for tx in self.transactions:
            if tx.is_debit:
                total_debit_eur += tx.amount.eur
                total_debit_bgn += tx.amount.bgn
            else:
                total_credit_eur += tx.amount.eur
                total_credit_bgn += tx.amount.bgn

        # Calculate expected closing balance
        opening = self.statement.opening_balance
        calculated_closing_eur = opening.eur + total_credit_eur - total_debit_eur
        calculated_closing_bgn = opening.bgn + total_credit_bgn - total_debit_bgn

        # Compare with reported closing balance
        expected = self.statement.closing_balance
        eur_diff = abs(calculated_closing_eur - expected.eur)
        bgn_diff = abs(calculated_closing_bgn - expected.bgn)

        # Allow small rounding differences
        # BGN values have more rounding issues due to EUR->BGN conversion (1.95583)
        eur_tolerance = Decimal("0.02")
        bgn_tolerance = Decimal("0.10")  # Allow more for BGN due to conversion rounding

        if eur_diff > eur_tolerance:
            errors.append(
                f"EUR balance mismatch: calculated {calculated_closing_eur:.2f}, "
                f"expected {expected.eur:.2f}, diff {eur_diff:.2f}"
            )

        if bgn_diff > bgn_tolerance:
            errors.append(
                f"BGN balance mismatch: calculated {calculated_closing_bgn:.2f}, "
                f"expected {expected.bgn:.2f}, diff {bgn_diff:.2f}"
            )

        # Check if transaction totals match reported turnover
        turnover = self.statement.turnover
        debit_eur_diff = abs(total_debit_eur - turnover.debit.eur)
        credit_eur_diff = abs(total_credit_eur - turnover.credit.eur)

        if debit_eur_diff > eur_tolerance:
            warnings.append(
                f"Debit turnover mismatch: transactions sum {total_debit_eur:.2f}, "
                f"reported {turnover.debit.eur:.2f}"
            )

        if credit_eur_diff > eur_tolerance:
            warnings.append(
                f"Credit turnover mismatch: transactions sum {total_credit_eur:.2f}, "
                f"reported {turnover.credit.eur:.2f}"
            )

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            calculated_closing_eur=calculated_closing_eur,
            calculated_closing_bgn=calculated_closing_bgn,
            expected_closing_eur=expected.eur,
            expected_closing_bgn=expected.bgn,
            total_debit_eur=total_debit_eur,
            total_credit_eur=total_credit_eur,
            total_debit_bgn=total_debit_bgn,
            total_credit_bgn=total_credit_bgn,
        )

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return self.model_dump_json(indent=indent, by_alias=True)
