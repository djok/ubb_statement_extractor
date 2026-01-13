"""PDF extractor for UBB bank statements."""

import re
from datetime import date
from decimal import Decimal
from typing import Optional

import pdfplumber

from .models import (
    AccountHolder,
    Balance,
    BankStatement,
    Counterparty,
    Period,
    StatementInfo,
    Transaction,
    TransactionType,
    Turnover,
)


class UBBStatementExtractor:
    """Extract data from UBB bank statement PDFs."""

    # Regex patterns
    ACCOUNT_HOLDER_PATTERN = re.compile(
        r"Титуляр на сметката\s+(\d+)\s+(.+?)(?:\s+\d{4}|\s+ДАО)"
    )
    IBAN_PATTERN = re.compile(r"IBAN:\s*(BG\w+)")
    CURRENCY_PATTERN = re.compile(r"Валута\s+([A-Z]{3})")
    PERIOD_PATTERN = re.compile(
        r"Период на извлечението:\s*ОТ\s+(\d{2})\s+(\w+)\s+(\d{4})\s+ДО\s+(\d{2})\s+(\w+)\s+(\d{4})"
    )
    STATEMENT_NUM_PATTERN = re.compile(
        r"Пореден номер / Дата:\s*(\d+)\s*/\s*(\d{2})\s+(\w+)\s+(\d{4})"
    )
    ADDRESS_PATTERN = re.compile(r"Адрес\s+(.+?)(?=IBAN:)", re.DOTALL)
    OPENING_BALANCE_PATTERN = re.compile(
        r"Начално салдо:\s*([\d,\.]+)\s*EUR\s*/\s*([\d,\.]+)\s*BGN"
    )
    CLOSING_BALANCE_PATTERN = re.compile(
        r"Крайно салдо:\s*([\d,\.]+)\s*EUR\s*/\s*([\d,\.]+)\s*BGN"
    )
    # Pattern for turnover section on last page
    # Format on same lines:
    # Обороти: Натрупани обороти:
    # Дебит: 634.13 EUR / 1,240.25 BGN Дебит: 1,570.94 EUR / 3,072.49 BGN
    # Кредит: 13,427.19 EUR / 26,261.30 BGN Кредит: 144,280.68 EUR / 282,188.48 BGN

    # First Дебит on line = current turnover debit
    TURNOVER_DEBIT_PATTERN = re.compile(
        r"^Дебит:\s*([\d,\.]+)\s*EUR\s*/\s*([\d,\.]+)\s*BGN",
        re.MULTILINE
    )
    # First Кредит on line = current turnover credit
    TURNOVER_CREDIT_PATTERN = re.compile(
        r"^Кредит:\s*([\d,\.]+)\s*EUR\s*/\s*([\d,\.]+)\s*BGN",
        re.MULTILINE
    )
    # Second Дебит on line = accumulated debit (after BGN and before next Дебит)
    ACCUMULATED_DEBIT_PATTERN = re.compile(
        r"BGN\s+Дебит:\s*([\d,\.]+)\s*EUR\s*/\s*([\d,\.]+)\s*BGN"
    )
    # Pattern to find all credit entries on a line
    ALL_CREDITS_PATTERN = re.compile(
        r"Кредит:\s*([\d,\.]+)\s*EUR\s*/\s*([\d,\.]+)\s*BGN"
    )

    # Transaction line pattern - matches the date column format
    TRANSACTION_DATE_PATTERN = re.compile(r"^(\d{2}/\d{2}/\d{2})\s+(\d{2}/\d{2})\s+")

    # Amount pattern at end of line
    AMOUNT_PATTERN = re.compile(
        r"(-?[\d,\.]+)\s*EUR\s*/\s*(-?[\d,\.]+)\s*BGN\s*$"
    )

    MONTH_MAP = {
        "ЯНУ": 1, "ФЕВ": 2, "МАР": 3, "АПР": 4, "МАЙ": 5, "ЮНИ": 6,
        "ЮЛИ": 7, "АВГ": 8, "СЕП": 9, "ОКТ": 10, "НОЕ": 11, "ДЕК": 12
    }

    def __init__(self, pdf_path: str):
        """Initialize extractor with PDF path."""
        self.pdf_path = pdf_path
        self.full_text = ""
        self.pages_text: list[str] = []

    def _parse_month(self, month_str: str) -> int:
        """Convert Bulgarian month abbreviation to number."""
        return self.MONTH_MAP.get(month_str.upper(), 1)

    def _parse_date(self, day: str, month: str, year: str) -> date:
        """Parse date from Bulgarian format."""
        return date(int(year), self._parse_month(month), int(day))

    def _parse_short_date(self, date_str: str, year: int) -> date:
        """Parse short date format DD/MM to full date."""
        parts = date_str.split("/")
        return date(year, int(parts[1]), int(parts[0]))

    def _parse_posting_date(self, date_str: str) -> date:
        """Parse posting date format DD/MM/YY."""
        parts = date_str.split("/")
        year = 2000 + int(parts[2])
        return date(year, int(parts[1]), int(parts[0]))

    def _parse_decimal(self, value: str) -> Decimal:
        """Parse decimal from string with comma as thousands separator."""
        # Remove thousands separator (comma) and convert
        cleaned = value.replace(",", "").replace(" ", "")
        return Decimal(cleaned)

    def _detect_transaction_type(self, description: str) -> TransactionType:
        """Detect transaction type from description."""
        desc_upper = description.upper()

        if "СЕПА ПОЛУЧЕН" in desc_upper:
            return TransactionType.SEPA_INCOMING
        elif "ИЗХОДЯЩ ВАЛУТЕН ПРЕВОД" in desc_upper or "ИЗХОДЯЩ" in desc_upper:
            return TransactionType.SEPA_OUTGOING
        elif "КАРТОВА ТРАНЗАКЦИЯ" in desc_upper:
            return TransactionType.CARD_TRANSACTION
        elif "СЪБРАНА ТАКСА ИЛИ КОМИСИОНА" in desc_upper:
            return TransactionType.FEE
        elif "ТАКСА ИЗХ." in desc_upper or "ТАКСА" in desc_upper:
            return TransactionType.TRANSFER_FEE
        elif "ПРЕВОД" in desc_upper:
            return TransactionType.INTERNAL_TRANSFER
        elif "ПРОДАЖБА НА ВАЛУТА" in desc_upper or "ПОКУПКА НА ВАЛУТА" in desc_upper:
            return TransactionType.CURRENCY_EXCHANGE
        else:
            return TransactionType.UNKNOWN

    # Patterns to skip when extracting counterparty (NOT counterparty names)
    # Note: IBAN lines (UBBSBGSF, BG...) are handled separately - IBAN is extracted before skip check
    SKIP_COUNTERPARTY_PATTERNS = [
        re.compile(r"^КАРТОВА ТРАНЗАКЦИЯ$"),
        re.compile(r"^(PO|SI|VI|R1)\d{6}$"),  # POS codes
        re.compile(r"^\d{8}-\d+-\d+$"),  # Terminal IDs like 10077271-556010-20260105
        re.compile(r"^\d{8}-[A-Z]\d+-\d+$"),  # Terminal IDs like 10077267-Q95823-20260105
        re.compile(r"^\d{4}X\d{4}-\d+-\d+$"),  # Card refs like 5574X4418-600500556010-000671255870
        re.compile(r"^ПРЕВОД$"),
    ]

    def _extract_counterparty(
        self, description_lines: list[str], tx_type: TransactionType
    ) -> Optional[Counterparty]:
        """Extract counterparty information from description lines.

        Args:
            description_lines: Lines of description text for the transaction
            tx_type: The transaction type (affects parsing logic)

        Returns:
            Counterparty object with extracted info, or None if no info found
        """
        name = None
        reference = None
        bank = None
        iban = None

        for i, line in enumerate(description_lines):
            # Skip the first line (transaction type description)
            if i == 0:
                continue

            line = line.strip()
            if not line:
                continue

            # Bank name - check first as it's very specific
            # Handle both "ОТ БАНКА:" and "ОТ БАНКА :" (space before colon)
            if "ОТ БАНКА" in line.upper():
                bank_match = re.search(r"ОТ БАНКА\s*[:\s]+(.+)", line, re.IGNORECASE)
                if bank_match:
                    bank = bank_match.group(1).strip()
                continue

            # IBAN - search anywhere in the line (may follow SWIFT code like "UBBSBGSF BG41UBBS...")
            iban_match = re.search(r"(BG\d{2}[A-Z]{4}\d{10,16})", line)
            if iban_match:
                iban = iban_match.group(1)
                continue

            # Check if line should be skipped
            should_skip = any(p.match(line) for p in self.SKIP_COUNTERPARTY_PATTERNS)
            if should_skip:
                continue

            # Long numeric strings (7+ digits) are payment references
            if re.match(r"^\d{7,}$", line):
                if not reference:
                    reference = line
                continue

            # For CARD transactions, look for merchant location (NAME-CITY-BG pattern)
            if tx_type == TransactionType.CARD_TRANSACTION:
                if re.match(r"^[A-Z0-9\s\-]+-[A-Z\s\.]+-(BG|RO|GR|TR)$", line):
                    if not name:
                        name = line
                    continue

            # For SEPA/transfers: first non-skipped line is usually the counterparty name
            if not name and len(line) > 2:
                # Skip lines that are purely numeric/punctuation (references, not names)
                if not re.match(r"^[\d\-/\.\s]+$", line):
                    name = line
                    continue

            # Payment reference (invoice numbers, etc.) - after name is set
            if not reference and name:
                # Lines like "F. 2400003707 19.12.2025" or "Ф.500003902405.01.2026"
                if re.search(r"[ФF][\.\s]", line, re.IGNORECASE):
                    reference = line
                    continue
                # Plain numeric references
                if re.match(r"^\d+$", line):
                    reference = line
                    continue

        if name or reference or bank or iban:
            return Counterparty(name=name, reference=reference, bank=bank, iban=iban)
        return None

    def _load_pdf(self) -> None:
        """Load PDF and extract text from all pages."""
        with pdfplumber.open(self.pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                self.pages_text.append(text)

        self.full_text = "\n".join(self.pages_text)

    def extract_header(self) -> dict:
        """Extract header information from first page."""
        first_page = self.pages_text[0] if self.pages_text else ""

        # Account holder
        holder_match = self.ACCOUNT_HOLDER_PATTERN.search(first_page)
        holder_code = holder_match.group(1) if holder_match else ""
        holder_name = holder_match.group(2).strip() if holder_match else ""

        # Address
        address_match = self.ADDRESS_PATTERN.search(first_page)
        address = ""
        if address_match:
            address = address_match.group(1).strip()
            address = " ".join(address.split())

        # IBAN
        iban_match = self.IBAN_PATTERN.search(first_page)
        iban = iban_match.group(1) if iban_match else ""

        # Currency
        currency_match = self.CURRENCY_PATTERN.search(first_page)
        currency = currency_match.group(1) if currency_match else "EUR"

        # Period
        period_match = self.PERIOD_PATTERN.search(first_page)
        if period_match:
            from_date = self._parse_date(
                period_match.group(1),
                period_match.group(2),
                period_match.group(3)
            )
            to_date = self._parse_date(
                period_match.group(4),
                period_match.group(5),
                period_match.group(6)
            )
        else:
            from_date = to_date = date.today()

        # Statement number and date
        stmt_match = self.STATEMENT_NUM_PATTERN.search(first_page)
        if stmt_match:
            stmt_num = int(stmt_match.group(1))
            stmt_date = self._parse_date(
                stmt_match.group(2),
                stmt_match.group(3),
                stmt_match.group(4)
            )
        else:
            stmt_num = 0
            stmt_date = date.today()

        # Opening balance
        opening_match = self.OPENING_BALANCE_PATTERN.search(first_page)
        if opening_match:
            opening_balance = Balance(
                eur=self._parse_decimal(opening_match.group(1)),
                bgn=self._parse_decimal(opening_match.group(2))
            )
        else:
            opening_balance = Balance(eur=Decimal("0"), bgn=Decimal("0"))

        return {
            "account_holder": AccountHolder(
                code=holder_code,
                name=holder_name,
                address=address
            ),
            "iban": iban,
            "currency": currency,
            "period": Period(**{"from": from_date, "to": to_date}),
            "statement_number": stmt_num,
            "statement_date": stmt_date,
            "opening_balance": opening_balance,
        }

    def extract_footer(self) -> dict:
        """Extract footer information (balances, turnovers) from last page with balance info.

        Note: The balance info may not be on the actual last page if there are
        trailing pages with notes (e.g., currency conversion notices).
        Search backwards to find the page with 'Крайно салдо:'.
        """
        # Search backwards from last page to find page with closing balance
        last_page = ""
        for i in range(len(self.pages_text) - 1, -1, -1):
            if "Крайно салдо:" in self.pages_text[i]:
                last_page = self.pages_text[i]
                break

        # Fallback to actual last page if pattern not found
        if not last_page:
            last_page = self.pages_text[-1] if self.pages_text else ""

        # Closing balance
        closing_match = self.CLOSING_BALANCE_PATTERN.search(last_page)
        if closing_match:
            closing_balance = Balance(
                eur=self._parse_decimal(closing_match.group(1)),
                bgn=self._parse_decimal(closing_match.group(2))
            )
        else:
            closing_balance = Balance(eur=Decimal("0"), bgn=Decimal("0"))

        # Current turnover - parse debit and credit separately
        turnover_debit_match = self.TURNOVER_DEBIT_PATTERN.search(last_page)
        turnover_credit_match = self.TURNOVER_CREDIT_PATTERN.search(last_page)

        if turnover_debit_match and turnover_credit_match:
            turnover = Turnover(
                debit=Balance(
                    eur=self._parse_decimal(turnover_debit_match.group(1)),
                    bgn=self._parse_decimal(turnover_debit_match.group(2))
                ),
                credit=Balance(
                    eur=self._parse_decimal(turnover_credit_match.group(1)),
                    bgn=self._parse_decimal(turnover_credit_match.group(2))
                )
            )
        else:
            turnover = Turnover(
                debit=Balance(eur=Decimal("0"), bgn=Decimal("0")),
                credit=Balance(eur=Decimal("0"), bgn=Decimal("0"))
            )

        # Accumulated turnover - parse debit and credit separately
        accumulated_debit_match = self.ACCUMULATED_DEBIT_PATTERN.search(last_page)

        # For accumulated credit, find all credit matches and take the second one
        all_credit_matches = list(self.ALL_CREDITS_PATTERN.finditer(last_page))
        accumulated_credit_match = all_credit_matches[1] if len(all_credit_matches) >= 2 else None

        if accumulated_debit_match and accumulated_credit_match:
            accumulated = Turnover(
                debit=Balance(
                    eur=self._parse_decimal(accumulated_debit_match.group(1)),
                    bgn=self._parse_decimal(accumulated_debit_match.group(2))
                ),
                credit=Balance(
                    eur=self._parse_decimal(accumulated_credit_match.group(1)),
                    bgn=self._parse_decimal(accumulated_credit_match.group(2))
                )
            )
        else:
            accumulated = Turnover(
                debit=Balance(eur=Decimal("0"), bgn=Decimal("0")),
                credit=Balance(eur=Decimal("0"), bgn=Decimal("0"))
            )

        return {
            "closing_balance": closing_balance,
            "turnover": turnover,
            "accumulated_turnover": accumulated,
        }

    def extract_transactions(self, statement_year: int) -> list[Transaction]:
        """Extract all transactions from the statement."""
        transactions = []

        for page_text in self.pages_text:
            lines = page_text.split("\n")
            i = 0

            while i < len(lines):
                line = lines[i]

                # Check if line starts with a transaction date
                date_match = self.TRANSACTION_DATE_PATTERN.match(line)
                if not date_match:
                    i += 1
                    continue

                posting_date_str = date_match.group(1)
                value_date_str = date_match.group(2)

                # Get the rest of the line after dates
                rest_of_line = line[date_match.end():]

                # Collect all lines of this transaction until we find the amount
                description_lines = [rest_of_line]

                # Look for amount in current line first
                amount_match = self.AMOUNT_PATTERN.search(line)

                if not amount_match:
                    # Continue to next lines until we find amount
                    i += 1
                    while i < len(lines):
                        next_line = lines[i]

                        # Check if this is a new transaction
                        if self.TRANSACTION_DATE_PATTERN.match(next_line):
                            break

                        # Check for amount
                        amount_match = self.AMOUNT_PATTERN.search(next_line)
                        if amount_match:
                            # Add line content before amount
                            before_amount = next_line[:amount_match.start()].strip()
                            if before_amount:
                                description_lines.append(before_amount)
                            i += 1
                            break
                        else:
                            # Skip certain lines
                            if not next_line.startswith("Междинно салдо") and \
                               not next_line.startswith("Страница") and \
                               not "ОББ Извлечение" in next_line:
                                description_lines.append(next_line)
                            i += 1
                else:
                    # Amount was on the same line
                    # Remove amount from description
                    desc_part = line[date_match.end():amount_match.start()].strip()
                    description_lines = [desc_part]
                    i += 1

                    # Continue collecting lines until next transaction
                    # (counterparty info follows on subsequent lines)
                    while i < len(lines):
                        next_line = lines[i]

                        # Stop at new transaction
                        if self.TRANSACTION_DATE_PATTERN.match(next_line):
                            break

                        # Skip page headers/footers
                        if next_line.startswith("Междинно салдо") or \
                           next_line.startswith("Страница") or \
                           "ОББ Извлечение" in next_line or \
                           next_line.startswith("Счет. Дата"):
                            i += 1
                            continue

                        description_lines.append(next_line)
                        i += 1

                if not amount_match:
                    continue

                # Parse the transaction
                posting_date = self._parse_posting_date(posting_date_str)
                value_date = self._parse_short_date(value_date_str, posting_date.year)

                # Extract reference and description
                full_desc = " ".join(description_lines)
                desc_parts = description_lines[0].split(None, 1) if description_lines else ["", ""]

                reference = desc_parts[0] if desc_parts else ""
                description = desc_parts[1] if len(desc_parts) > 1 else ""

                # Parse amount
                eur_amount = self._parse_decimal(amount_match.group(1))
                bgn_amount = self._parse_decimal(amount_match.group(2))

                is_debit = eur_amount < 0

                # Make amounts positive for storage
                amount = Balance(
                    eur=abs(eur_amount),
                    bgn=abs(bgn_amount)
                )

                # Detect type
                trans_type = self._detect_transaction_type(full_desc)

                # Extract counterparty (pass transaction type for context-aware parsing)
                counterparty = self._extract_counterparty(description_lines, trans_type)

                transaction = Transaction(
                    posting_date=posting_date,
                    value_date=value_date,
                    reference=reference,
                    type=trans_type,
                    description=description,
                    raw_description=full_desc,
                    counterparty=counterparty,
                    amount=amount,
                    is_debit=is_debit
                )

                transactions.append(transaction)

        return transactions

    def parse(self) -> BankStatement:
        """Parse the complete bank statement."""
        self._load_pdf()

        header = self.extract_header()
        footer = self.extract_footer()

        statement_year = header["period"].from_date.year
        transactions = self.extract_transactions(statement_year)

        statement_info = StatementInfo(
            bank="UBB",
            account_holder=header["account_holder"],
            iban=header["iban"],
            currency=header["currency"],
            period=header["period"],
            statement_number=header["statement_number"],
            statement_date=header["statement_date"],
            opening_balance=header["opening_balance"],
            closing_balance=footer["closing_balance"],
            turnover=footer["turnover"],
            accumulated_turnover=footer["accumulated_turnover"],
        )

        return BankStatement(
            statement=statement_info,
            transactions=transactions
        )
