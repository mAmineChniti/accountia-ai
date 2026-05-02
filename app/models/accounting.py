from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JournalEntryPreview(BaseModel):
    """Preview of a journal entry."""

    date: datetime = Field(..., description="Entry date")
    account: str = Field(..., description="Account name")
    debit: float = Field(..., description="Debit amount", ge=0)
    credit: float = Field(..., description="Credit amount", ge=0)
    description: str = Field(..., description="Entry description")

    model_config = {"populate_by_name": True}


class TaxCalculationItem(BaseModel):
    """Tax calculation detail."""

    tax_type: str = Field(..., alias="taxType", description="Type of tax: VAT, Corporate Tax, etc.")
    jurisdiction: str = Field(..., description="Tax jurisdiction")
    taxable_amount: float = Field(..., alias="taxableAmount", description="Amount subject to tax")
    tax_rate: float = Field(..., alias="taxRate", description="Tax rate as decimal")
    tax_amount: float = Field(..., alias="taxAmount", description="Calculated tax amount")
    notes: str = Field("", description="Additional notes")

    model_config = {"populate_by_name": True}


class AccountingResultsResponse(BaseModel):
    """Full accounting results for a completed job."""

    task_id: str = Field(..., alias="taskId", description="Task ID")
    business_id: str = Field(..., alias="businessId", description="Business ID")
    period_start: datetime = Field(..., alias="periodStart", description="Period start")
    period_end: datetime = Field(..., alias="periodEnd", description="Period end")
    status: str = Field(..., description="Status: completed")

    # Financial Summary
    total_revenue: float = Field(..., alias="totalRevenue", description="Total revenue for period", ge=0)
    total_expenses: float = Field(..., alias="totalExpenses", description="Total expenses for period", ge=0)
    gross_profit: float = Field(..., alias="grossProfit", description="Gross profit (revenue - COGS)")
    net_profit: float = Field(..., alias="netProfit", description="Net profit after all expenses")
    accounts_receivable: float = Field(..., alias="accountsReceivable", description="Outstanding A/R balance", ge=0)
    accounts_payable: float = Field(..., alias="accountsPayable", description="Outstanding A/P balance", ge=0)
    cash_position: float = Field(..., alias="cashPosition", description="Cash on hand")

    # Tax
    tax_calculations: list[TaxCalculationItem] = Field(
        ..., alias="taxCalculations", description="Tax calculations breakdown"
    )

    # AI Analysis
    ai_insights: str = Field(..., alias="aiInsights", description="AI-generated analysis and insights")
    recommendations: list[str] = Field(..., description="Actionable recommendations")
    anomalies_detected: list = Field(..., alias="anomaliesDetected", description="Detected anomalies or red flags")

    # Reports
    reports: list[dict] = Field(..., description="Generated financial reports (P&L, Balance Sheet, etc.)")

    # Journal Entries (full)
    journal_entries: list[JournalEntryPreview] = Field(
        ..., alias="journalEntries", description="All journal entries for the period"
    )
    total_journal_entries: int = Field(
        ..., alias="totalJournalEntries", description="Total count of journal entries", ge=0
    )

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "taskId": "task_123",
                "businessId": "biz_001",
                "periodStart": "2024-01-01T00:00:00Z",
                "periodEnd": "2024-01-31T23:59:59Z",
                "status": "completed",
                "totalRevenue": 12500.5,
                "totalExpenses": 4200.25,
                "grossProfit": 8300.25,
                "netProfit": 7900.0,
                "accountsReceivable": 1500.0,
                "accountsPayable": 300.0,
                "cashPosition": 4800.75,
                "taxCalculations": [
                    {
                        "taxType": "VAT",
                        "jurisdiction": "TN",
                        "taxableAmount": 10000.0,
                        "taxRate": 0.19,
                        "taxAmount": 1900.0,
                        "notes": "Standard VAT",
                    }
                ],
                "aiInsights": "System identified recurring revenue growth.",
                "recommendations": ["Review VAT filing", "Consider cash buffer"],
                "anomaliesDetected": [
                    {
                        "type": "duplicate_invoice",
                        "detail": "Duplicate invoice number INV-2024-015 detected",
                        "severity": "medium",
                        "relatedInvoiceId": "INV-2024-015",
                    },
                    {
                        "type": "no_revenue",
                        "detail": "No revenue recorded for this period",
                        "severity": "high",
                    },
                ],
                "reports": [
                    {
                        "reportType": "P&L",
                        "data": {"revenue": 12500.5, "gross_profit": 8300.25},
                    }
                ],
                "journalEntries": [
                    {
                        "date": "2024-01-05T12:00:00Z",
                        "account": "Sales",
                        "debit": 0.0,
                        "credit": 1000.0,
                        "description": "Invoice INV-001",
                    }
                ],
                "totalJournalEntries": 1,
            }
        },
    }


class CreateAccountingJobRequest(BaseModel):
    business_id: str = Field(..., alias="businessId")
    period_start: datetime = Field(..., alias="periodStart")
    period_end: datetime = Field(..., alias="periodEnd")

    model_config = {
        "json_schema_extra": {
            "example": {
                "businessId": "biz_001",
                "periodStart": "2024-01-01T00:00:00Z",
                "periodEnd": "2024-01-31T23:59:59Z",
            }
        }
    }


class CreateAccountingJobResponse(BaseModel):
    task_id: str = Field(..., alias="taskId")
    business_id: str = Field(..., alias="businessId")
    status: str = Field(..., description="job status")
    message: str | None = Field(None, description="Optional message")
    estimated_seconds: int | None = Field(None, alias="estimatedSeconds")
    estimated_completion: datetime | None = Field(None, alias="estimatedCompletion")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "taskId": "task_123",
                "businessId": "biz_001",
                "status": "pending",
                "message": "Accounting job created",
                "estimatedSeconds": 45,
            }
        },
    }


class JobSummary(BaseModel):
    task_id: str = Field(..., alias="taskId")
    period_start: datetime = Field(..., alias="periodStart")
    period_end: datetime = Field(..., alias="periodEnd")
    status: str = Field(..., description="Status")
    progress_percent: int = Field(0, alias="progressPercent")
    estimated_seconds: int | None = Field(None, alias="estimatedSeconds")
    estimated_completion: datetime | None = Field(None, alias="estimatedCompletion")
    estimated_time_remaining: int | None = Field(None, alias="estimatedTimeRemaining")
    started_at: datetime | None = Field(None, alias="startedAt")
    completed_at: datetime | None = Field(None, alias="completedAt")
    journal_entries_count: int = Field(0, alias="journalEntriesCount")
    reports_generated: int = Field(0, alias="reportsGenerated")

    model_config = {"populate_by_name": True}


class JobsListResponse(BaseModel):
    business_id: str = Field(..., alias="businessId")
    jobs: list[JobSummary]

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "businessId": "biz_001",
                "jobs": [
                    {
                        "taskId": "task_123",
                        "periodStart": "2024-01-01T00:00:00Z",
                        "periodEnd": "2024-01-31T23:59:59Z",
                        "status": "completed",
                        "progressPercent": 100,
                        "journalEntriesCount": 42,
                        "reportsGenerated": 3,
                    }
                ],
            }
        },
    }


class TaxPersistResponse(BaseModel):
    business_id: str = Field(..., alias="businessId")
    year: int = Field(..., alias="year")
    success: bool = Field(..., alias="success")
    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {"example": {"businessId": "biz_001", "year": 2024, "success": True}},
    }


class TaxResultsResponse(BaseModel):
    success: bool = Field(True, description="Whether tax results were found")
    message: str | None = Field(None, description="Status message when results not found")
    business_id: str | None = Field(None, alias="businessId")
    year: int | None = Field(None, alias="year")
    tax_breakdown: dict[str, Any] | None = Field(None, alias="taxBreakdown")
    analysis: dict[str, Any] | None = Field(None, alias="analysis")
    llm_recommendations: list[str] | None = Field(None, alias="llmRecommendations")
    llm_summary: str | None = Field(None, alias="llmSummary")
    created_at: datetime | None = Field(None, alias="createdAt")
    last_updated_at: datetime | None = Field(None, alias="lastUpdatedAt")
    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "businessId": "biz_001",
                "year": 2024,
                "taxBreakdown": {
                    "vat_standard_19": 1900.0,
                    "vat_reduced_13": 0.0,
                    "vat_reduced_7": 0.0,
                    "vat_exempt": 0.0,
                    "vat_total": 1900.0,
                    "taxable_income": 8000.0,
                    "corporate_tax_rate": 0.15,
                    "corporate_tax_due": 1200.0,
                    "withholding_tax": 50.0,
                    "total_tax_liability": 3150.0,
                    "filing_period": "01/2024",
                    "due_date": "2024-02-28T00:00:00Z",
                },
                "analysis": {"insights": "Sample analysis"},
                "createdAt": "2024-05-01T12:00:00Z",
                "lastUpdatedAt": "2024-05-01T12:00:00Z",
                "llmRecommendations": ["Confirm VAT filing", "Check withholding tax on X"],
                "llmSummary": "LLM: prioritize VAT and withholding reviews.",
            }
        },
    }
