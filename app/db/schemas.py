"""Beanie document models for accounting results."""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from beanie import Document, Indexed
from pydantic import BaseModel, Field


class AccountingTaskStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JournalEntry(BaseModel):
    """Individual accounting journal entry."""

    date: datetime
    account: str  # e.g., "Revenue", "Accounts Receivable", "Cost of Goods Sold"
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    description: str
    invoice_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class TaxCalculation(BaseModel):
    """Tax calculation for a period."""

    tax_type: str  # e.g., "VAT", "Sales Tax", "Income Tax"
    jurisdiction: str
    taxable_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    notes: str = ""


class FinancialSummary(BaseModel):
    """Summary financial metrics."""

    total_revenue: Decimal
    total_expenses: Decimal
    gross_profit: Decimal
    net_profit: Decimal
    accounts_receivable: Decimal
    accounts_payable: Decimal
    cash_position: Decimal


class AccountingReport(BaseModel):
    """Generated accounting report."""

    report_type: str  # "P&L", "Balance Sheet", "Cash Flow", "General Ledger"
    period_start: datetime
    period_end: datetime
    data: dict  # Structured report data
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class AccountingTask(Document):
    """Main accounting task document - stored in tenant DB."""

    # Identification
    business_id: Indexed(str)
    task_id: Indexed(str, unique=True)

    # Period
    period_start: datetime
    period_end: datetime

    # Status
    status: AccountingTaskStatus = AccountingTaskStatus.PENDING
    progress_percent: int = 0

    # Processing
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    # Time estimates
    estimated_seconds: int | None = None  # Rough time estimate in seconds
    estimated_completion: datetime | None = None  # Estimated completion timestamp (UTC)

    # Results
    journal_entries: list[JournalEntry] = Field(default_factory=list)
    tax_calculations: list[TaxCalculation] = Field(default_factory=list)
    financial_summary: FinancialSummary | None = None
    reports: list[AccountingReport] = Field(default_factory=list)

    # AI-generated insights
    ai_insights: str = ""  # Natural language summary from LLM
    recommendations: list[str] = Field(default_factory=list)
    anomalies_detected: list[dict] = Field(default_factory=list)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    processed_by: str = "ai-accountant-v1"

    class Settings:
        name = "accounting_tasks"
        indexes = [
            "business_id",
            "task_id",
            "status",
            ["business_id", "period_start", "period_end"],
        ]


class AccountingPeriod(Document):
    """Completed accounting period - serves as audit trail."""

    business_id: Indexed(str)
    period_start: datetime
    period_end: datetime

    # Closing entries
    closing_entries: list[JournalEntry]

    # Final balances
    closing_balances: dict[str, Decimal]  # Account -> Balance

    # Status
    is_closed: bool = True
    closed_at: datetime = Field(default_factory=datetime.utcnow)
    closed_by: str = "ai-accountant"

    # Reference to task
    task_id: str

    class Settings:
        name = "accounting_periods"
