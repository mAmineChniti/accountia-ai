"""Accounting API endpoints."""

from datetime import datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.security import secure_endpoint
from app.db.mongodb import get_tenant_db
from app.db.schemas import AccountingTask, AccountingTaskStatus
from app.services.accounting_engine import AccountingEngine
from app.services.business_service import BusinessService

logger = structlog.get_logger()

# All endpoints require API key (only Accountia API can access)
router = APIRouter(dependencies=[Depends(secure_endpoint)])


class CreateAccountingJobRequest(BaseModel):
    """Request to create an accounting job.
    
    The AI Accountant will look up the business's databaseName from the platform DB.
    """
    business_id: str = Field(..., description="MongoDB ID of the business to process", example="60d5ecb8b6f3c72e7c8e4a5b")
    period_start: datetime = Field(..., description="Start of accounting period (ISO format)", example="2024-01-01T00:00:00Z")
    period_end: datetime = Field(..., description="End of accounting period (ISO format)", example="2024-01-31T23:59:59Z")
    
    class Config:
        json_schema_extra = {
            "example": {
                "business_id": "60d5ecb8b6f3c72e7c8e4a5b",
                "period_start": "2024-01-01T00:00:00Z",
                "period_end": "2024-01-31T23:59:59Z",
            }
        }


class CreateAccountingJobResponse(BaseModel):
    """Response after creating an accounting job."""
    task_id: str = Field(..., description="Unique task ID for this accounting job", example="60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131")
    status: str = Field(..., description="Current status: pending, processing, completed", example="pending")
    message: str = Field(..., description="Human-readable status message")
    estimated_completion: Optional[str] = Field(None, description="Estimated time to completion", example="~59 seconds")


class AccountingJobStatusResponse(BaseModel):
    """Status of an accounting job."""
    task_id: str = Field(..., description="Unique task ID")
    business_id: str = Field(..., description="Business ID")
    period_start: datetime = Field(..., description="Period start date")
    period_end: datetime = Field(..., description="Period end date")
    status: str = Field(..., description="Status: pending, processing, completed, failed")
    progress_percent: int = Field(..., description="Processing progress 0-100", ge=0, le=100)
    started_at: Optional[datetime] = Field(None, description="When processing started")
    completed_at: Optional[datetime] = Field(None, description="When processing completed")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    journal_entries_count: int = Field(0, description="Number of journal entries generated")
    reports_generated: int = Field(0, description="Number of reports generated")


class JournalEntryPreview(BaseModel):
    """Preview of a journal entry."""
    date: datetime = Field(..., description="Entry date")
    account: str = Field(..., description="Account name")
    debit: float = Field(..., description="Debit amount", ge=0)
    credit: float = Field(..., description="Credit amount", ge=0)
    description: str = Field(..., description="Entry description")

class TaxCalculationItem(BaseModel):
    """Tax calculation detail."""
    tax_type: str = Field(..., description="Type of tax: VAT, Corporate Tax, etc.")
    jurisdiction: str = Field(..., description="Tax jurisdiction")
    taxable_amount: float = Field(..., description="Amount subject to tax")
    tax_rate: float = Field(..., description="Tax rate as decimal")
    tax_amount: float = Field(..., description="Calculated tax amount")
    notes: str = Field("", description="Additional notes")

class AccountingResultsResponse(BaseModel):
    """Full accounting results for a completed job."""
    task_id: str = Field(..., description="Task ID")
    business_id: str = Field(..., description="Business ID")
    period_start: datetime = Field(..., description="Period start")
    period_end: datetime = Field(..., description="Period end")
    status: str = Field(..., description="Status: completed")
    
    # Financial Summary
    total_revenue: float = Field(..., description="Total revenue for period", ge=0)
    total_expenses: float = Field(..., description="Total expenses for period", ge=0)
    gross_profit: float = Field(..., description="Gross profit (revenue - COGS)")
    net_profit: float = Field(..., description="Net profit after all expenses")
    accounts_receivable: float = Field(..., description="Outstanding A/R balance", ge=0)
    accounts_payable: float = Field(..., description="Outstanding A/P balance", ge=0)
    cash_position: float = Field(..., description="Cash on hand")
    
    # Tax
    tax_calculations: list[TaxCalculationItem] = Field(..., description="Tax calculations breakdown")
    
    # AI Analysis
    ai_insights: str = Field(..., description="AI-generated analysis and insights")
    recommendations: list[str] = Field(..., description="Actionable recommendations")
    anomalies_detected: list = Field(..., description="Detected anomalies or red flags")
    
    # Reports
    reports: list[dict] = Field(..., description="Generated financial reports (P&L, Balance Sheet, etc.)")
    
    # Journal Entries (paginated)
    journal_entries_preview: list[JournalEntryPreview] = Field(..., description="First 10 journal entries")
    total_journal_entries: int = Field(..., description="Total count of journal entries", ge=0)


def generate_task_id(business_id: str, start: datetime, end: datetime) -> str:
    """Generate unique task ID."""
    return f"{business_id}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"


async def process_accounting_task(
    task: AccountingTask,
    database_name: str,
) -> None:
    """Background task to process accounting."""
    
    logger.info(
        "[JOB PROCESSING] Starting accounting processing",
        task_id=task.task_id,
        business_id=task.business_id,
        database_name=database_name,
    )
    
    engine = AccountingEngine(
        business_id=task.business_id,
        database_name=database_name,
    )
    
    try:
        # Update status
        task.status = AccountingTaskStatus.PROCESSING
        task.started_at = datetime.utcnow()
        task.progress_percent = 10
        
        tenant_db = get_tenant_db(database_name)
        await tenant_db["accounting_tasks"].replace_one(
            {"task_id": task.task_id},
            task.model_dump(),
            upsert=True,
        )
        
        # Process
        task.progress_percent = 50
        completed_task = await engine.process_period(task)
        
        # Save results
        await tenant_db["accounting_tasks"].replace_one(
            {"task_id": completed_task.task_id},
            completed_task.model_dump(),
            upsert=True,
        )
        
        duration_seconds = (completed_task.completed_at - task.started_at).total_seconds() if completed_task.completed_at and task.started_at else 0
        logger.info(
            "[JOB COMPLETED] Accounting job finished successfully",
            task_id=task.task_id,
            business_id=task.business_id,
            duration_seconds=round(duration_seconds, 2),
            journal_entries_count=len(completed_task.journal_entries),
            tax_calculations_count=len(completed_task.tax_calculations),
        )
        
    except Exception as e:
        duration_seconds = (datetime.utcnow() - task.started_at).total_seconds() if task.started_at else 0
        logger.error(
            "[JOB FAILED] Accounting job failed",
            task_id=task.task_id,
            business_id=task.business_id,
            duration_seconds=round(duration_seconds, 2),
            error=str(e),
        )
        task.status = AccountingTaskStatus.FAILED
        task.error_message = str(e)
        task.progress_percent = 0
        
        tenant_db = get_tenant_db(database_name)
        await tenant_db["accounting_tasks"].replace_one(
            {"task_id": task.task_id},
            task.model_dump(),
            upsert=True,
        )


@router.post(
    "/jobs",
    response_model=CreateAccountingJobResponse,
    summary="Create Accounting Job",
    description="Start AI accounting for a business period. The AI looks up the database, reads invoices, generates journal entries, and calculates taxes. Returns a task ID to poll for completion.",
    response_description="Job created or existing job status",
)
async def create_accounting_job(
    request: CreateAccountingJobRequest,
    background_tasks: BackgroundTasks,
):
    """Create a new accounting job for a business period.
    
    The AI Accountant will:
    1. Look up the business from platform DB to get databaseName
    2. Read invoices from the tenant database
    3. Process accounting and write results back to tenant DB
    """
    
    # Validate period
    period_days = (request.period_end - request.period_start).days
    if period_days > 365:
        raise HTTPException(
            status_code=400,
            detail="Accounting period cannot exceed 365 days",
        )
    
    if request.period_end < request.period_start:
        raise HTTPException(
            status_code=400,
            detail="Period end must be after period start",
        )
    
    # Look up business database name from platform DB
    try:
        database_name = await BusinessService.get_database_name(request.business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    task_id = generate_task_id(
        request.business_id,
        request.period_start,
        request.period_end,
    )
    
    # Check if task already exists
    tenant_db = get_tenant_db(database_name)
    existing = await tenant_db["accounting_tasks"].find_one({"task_id": task_id})
    
    if existing and existing.get("status") == AccountingTaskStatus.COMPLETED:
        return CreateAccountingJobResponse(
            task_id=task_id,
            status="completed",
            message="Accounting for this period has already been completed. Use GET /jobs/{task_id} to retrieve results.",
        )
    
    if existing and existing.get("status") == AccountingTaskStatus.PROCESSING:
        return CreateAccountingJobResponse(
            task_id=task_id,
            status="processing",
            message="Accounting job already in progress.",
        )
    
    # Create new task
    task = AccountingTask(
        business_id=request.business_id,
        task_id=task_id,
        period_start=request.period_start,
        period_end=request.period_end,
        status=AccountingTaskStatus.PENDING,
    )
    
    # Save to DB
    await tenant_db["accounting_tasks"].insert_one(task.model_dump())
    
    # Start background processing
    logger.info(
        "[JOB STARTED] Accounting job created",
        task_id=task_id,
        business_id=request.business_id,
        period_start=request.period_start.isoformat(),
        period_end=request.period_end.isoformat(),
        database_name=database_name,
    )
    
    background_tasks.add_task(
        process_accounting_task,
        task,
        database_name,
    )
    
    estimated_seconds = min(30 + period_days, 300)  # Rough estimate
    
    return CreateAccountingJobResponse(
        task_id=task_id,
        status="pending",
        message=f"Accounting job created for period {request.period_start.date()} to {request.period_end.date()}",
        estimated_completion=f"~{estimated_seconds} seconds",
    )


@router.get(
    "/jobs/{task_id}",
    response_model=AccountingJobStatusResponse,
    summary="Get Job Status",
    description="Check the current status of an accounting job. Poll this endpoint to track progress until completion.",
    response_description="Current job status including progress percent and counts",
)
async def get_job_status(
    task_id: str,
    business_id: str = Query(..., description="Business ID"),
):
    """Get the status of an accounting job."""
    
    # Look up database name from platform DB
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    tenant_db = get_tenant_db(database_name)
    task_data = await tenant_db["accounting_tasks"].find_one({"task_id": task_id})
    
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return AccountingJobStatusResponse(
        task_id=task_data["task_id"],
        business_id=task_data["business_id"],
        period_start=task_data["period_start"],
        period_end=task_data["period_end"],
        status=task_data["status"],
        progress_percent=task_data.get("progress_percent", 0),
        started_at=task_data.get("started_at"),
        completed_at=task_data.get("completed_at"),
        error_message=task_data.get("error_message"),
        journal_entries_count=len(task_data.get("journal_entries", [])),
        reports_generated=len(task_data.get("reports", [])),
    )


@router.get(
    "/jobs/{task_id}/results",
    response_model=AccountingResultsResponse,
    summary="Get Job Results",
    description="Retrieve full accounting results including financial summary, tax calculations, AI insights, journal entries preview, and generated reports. Only available after job completes.",
    response_description="Complete accounting results with journal entries, taxes, and AI analysis",
)
async def get_job_results(
    task_id: str,
    business_id: str = Query(..., description="Business ID"),
):
    """Get the full accounting results for a completed job."""
    
    # Look up database name from platform DB
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    tenant_db = get_tenant_db(database_name)
    task_data = await tenant_db["accounting_tasks"].find_one({"task_id": task_id})
    
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task_data["status"] != AccountingTaskStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Task not completed. Current status: {task_data['status']}",
        )
    
    summary = task_data.get("financial_summary", {})
    journal_entries = task_data.get("journal_entries", [])
    
    # Preview first 10 journal entries
    entries_preview = [
        {
            "date": e["date"],
            "account": e["account"],
            "debit": float(e.get("debit", 0)),
            "credit": float(e.get("credit", 0)),
            "description": e["description"],
        }
        for e in journal_entries[:10]
    ]
    
    return AccountingResultsResponse(
        task_id=task_data["task_id"],
        business_id=task_data["business_id"],
        period_start=task_data["period_start"],
        period_end=task_data["period_end"],
        status=task_data["status"],
        total_revenue=summary.get("total_revenue", 0),
        total_expenses=summary.get("total_expenses", 0),
        gross_profit=summary.get("gross_profit", 0),
        net_profit=summary.get("net_profit", 0),
        accounts_receivable=summary.get("accounts_receivable", 0),
        accounts_payable=summary.get("accounts_payable", 0),
        cash_position=summary.get("cash_position", 0),
        tax_calculations=task_data.get("tax_calculations", []),
        ai_insights=task_data.get("ai_insights", ""),
        recommendations=task_data.get("recommendations", []),
        anomalies_detected=task_data.get("anomalies_detected", []),
        reports=task_data.get("reports", []),
        journal_entries_preview=entries_preview,
        total_journal_entries=len(journal_entries),
    )


@router.get(
    "/business/{business_id}/history",
    summary="Get Accounting History",
    description="List all accounting periods for a business with basic metadata.",
    response_description="List of accounting tasks with status and dates",
)
async def get_accounting_history(
    business_id: str,
    limit: int = Query(10, ge=1, le=100, description="Maximum number of records to return"),
):
    """Get accounting history for a business."""
    
    # Look up database name from platform DB
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    tenant_db = get_tenant_db(database_name)
    cursor = tenant_db["accounting_tasks"].find(
        {"business_id": business_id}
    ).sort("created_at", -1).limit(limit)
    
    tasks = await cursor.to_list(length=limit)
    
    return {
        "business_id": business_id,
        "tasks": [
            {
                "task_id": t["task_id"],
                "period_start": t["period_start"],
                "period_end": t["period_end"],
                "status": t["status"],
                "completed_at": t.get("completed_at"),
            }
            for t in tasks
        ],
    }


@router.get(
    "/business/{business_id}/work",
    summary="Get All Accountant Work",
    description="Comprehensive work log showing everything the AI Accountant has done for a business. Includes detailed period info, journal entry counts, tax calculations, and financial summaries.",
    response_description="Complete work history with summary statistics and period details",
)
async def get_all_accountant_work(
    business_id: str,
    start_date: Optional[datetime] = Query(None, description="Filter from date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="Filter to date (ISO format)"),
    status: Optional[str] = Query(None, description="Filter by status: pending, processing, completed, failed"),
):
    """
    Get ALL work performed by the AI Accountant for a business.
    
    This is the comprehensive work log - everything the accountant has done.
    Includes journal entries, tax calculations, reports, AI insights.
    """
    
    # Look up database name from platform DB
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    tenant_db = get_tenant_db(database_name)
    
    # Build query
    query = {"business_id": business_id}
    if status:
        query["status"] = status
    if start_date or end_date:
        date_query = {}
        if start_date:
            date_query["$gte"] = start_date
        if end_date:
            date_query["$lte"] = end_date
        query["period_start"] = date_query
    
    # Get all tasks
    cursor = tenant_db["accounting_tasks"].find(query).sort("created_at", -1)
    tasks = await cursor.to_list(length=1000)
    
    # Calculate totals
    total_invoices_processed = sum(
        len(t.get("journal_entries", [])) // 2  # Rough estimate: 2 entries per invoice
        for t in tasks if t.get("status") == "completed"
    )
    
    total_revenue = sum(
        float(t.get("financial_summary", {}).get("total_revenue", 0))
        for t in tasks if t.get("status") == "completed"
    )
    
    total_journal_entries = sum(
        len(t.get("journal_entries", []))
        for t in tasks
    )
    
    return {
        "business_id": business_id,
        "database_name": database_name,
        "summary": {
            "total_accounting_periods": len(tasks),
            "completed": sum(1 for t in tasks if t.get("status") == "completed"),
            "pending": sum(1 for t in tasks if t.get("status") == "pending"),
            "processing": sum(1 for t in tasks if t.get("status") == "processing"),
            "failed": sum(1 for t in tasks if t.get("status") == "failed"),
            "total_journal_entries_generated": total_journal_entries,
            "total_revenue_processed": total_revenue,
        },
        "accounting_periods": [
            {
                "task_id": t["task_id"],
                "period_start": t["period_start"],
                "period_end": t["period_end"],
                "status": t["status"],
                "created_at": t.get("created_at"),
                "started_at": t.get("started_at"),
                "completed_at": t.get("completed_at"),
                "journal_entries_count": len(t.get("journal_entries", [])),
                "tax_calculations_count": len(t.get("tax_calculations", [])),
                "reports_count": len(t.get("reports", [])),
                "has_ai_insights": bool(t.get("ai_insights")),
                "recommendations_count": len(t.get("recommendations", [])),
                "financial_summary": t.get("financial_summary"),
            }
            for t in tasks
        ],
    }


@router.get(
    "/business/{business_id}/taxes",
    summary="Get Tunisian Tax Summary",
    description="Calculate taxes per Tunisian law: VAT (19%, 13%, 7%), Corporate Tax (IS), and Withholding Tax. Returns annual summary with monthly breakdowns and tax calendar.",
    response_description="Complete tax calculations with monthly details and due dates",
)
async def get_tunisian_tax_summary(
    business_id: str,
    year: int = Query(None, description="Year to calculate taxes for (default: current year)"),
):
    """
    Get Tunisian tax summary for a business.
    
    Calculates VAT (19%, 13%, 7%), corporate income tax, and withholding taxes
    per Tunisian tax law.
    """
    from app.services.tax_service import TunisianTaxService
    
    # Look up database name from platform DB
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    tenant_db = get_tenant_db(database_name)
    
    # Get business info
    try:
        business_info = await BusinessService.get_business_info(business_id)
    except ValueError:
        business_info = {}
    
    # Determine year
    if not year:
        year = datetime.utcnow().year
    
    # Get all invoices for the year
    start_of_year = datetime(year, 1, 1)
    end_of_year = datetime(year, 12, 31, 23, 59, 59)
    
    invoices_cursor = tenant_db["invoices"].find({
        "issuerBusinessId": {"$in": [business_id]},
        "issuedDate": {"$gte": start_of_year, "$lte": end_of_year},
    })
    invoices = await invoices_cursor.to_list(length=None)
    
    # Get products for categorization
    products_cursor = tenant_db["products"].find({
        "businessId": {"$in": [business_id]},
    })
    products = await products_cursor.to_list(length=None)
    
    # Calculate taxes
    tax_service = TunisianTaxService()
    
    # Get monthly breakdowns
    monthly_taxes = []
    for month in range(1, 13):
        month_start = datetime(year, month, 1)
        month_end = datetime(year, month, 28 if month != 2 else 28)  # Approximate
        
        month_invoices = [
            inv for inv in invoices
            if month_start <= inv.get("issuedDate", datetime.utcnow()) <= month_end
        ]
        
        if month_invoices:
            tax_breakdown = tax_service.calculate_period_taxes(
                business_id,
                month_invoices,
                products,
                month_start,
                month_end,
            )
            
            monthly_taxes.append({
                "month": month,
                "period": f"{month:02d}/{year}",
                "vat_standard_19": float(tax_breakdown.vat_standard_19),
                "vat_reduced_13": float(tax_breakdown.vat_reduced_13),
                "vat_reduced_7": float(tax_breakdown.vat_reduced_7),
                "vat_total": float(tax_breakdown.vat_total),
                "taxable_income": float(tax_breakdown.taxable_income),
                "corporate_tax_due": float(tax_breakdown.corporate_tax_due),
                "withholding_tax": float(tax_breakdown.withholding_tax),
                "total_tax_liability": float(tax_breakdown.total_tax_liability),
                "due_date": tax_breakdown.due_date.isoformat(),
            })
    
    # Calculate annual totals
    annual_vat = sum(m["vat_total"] for m in monthly_taxes)
    annual_corp_tax = sum(m["corporate_tax_due"] for m in monthly_taxes)
    annual_withholding = sum(m["withholding_tax"] for m in monthly_taxes)
    
    # Tax calendar
    tax_calendar = tax_service.get_tax_calendar(year)
    
    return {
        "business_id": business_id,
        "business_name": business_info.get("name", "Unknown"),
        "year": year,
        "currency": "TND",
        "summary": {
            "annual_vat_total": annual_vat,
            "annual_corporate_tax": annual_corp_tax,
            "annual_withholding_tax": annual_withholding,
            "total_tax_liability": annual_vat + annual_corp_tax + annual_withholding,
        },
        "vat_breakdown": {
            "standard_rate_19_percent": annual_vat,  # Simplified - actually should sum 19% only
            "reduced_rate_13_percent": 0,  # Calculate from monthly
            "reduced_rate_7_percent": 0,   # Calculate from monthly
        },
        "monthly_details": monthly_taxes,
        "tax_calendar": [
            {
                "period": d["period"],
                "due_date": d["vat_due_date"].isoformat(),
                "description": d["description"],
            }
            for d in tax_calendar[:12]  # Monthly VAT deadlines
        ],
        "notes": [
            "VAT (TVA) is due by the 28th of the following month",
            "Standard VAT rate: 19%",
            "Reduced rates: 13% (transport, tourism), 7% (medical, education)",
            "Corporate tax (IS): 15% for SMEs, 25% for larger companies",
            "Withholding tax: 1.5% on B2B transactions",
        ],
    }
