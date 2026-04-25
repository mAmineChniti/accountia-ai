"""Accounting API endpoints."""

from datetime import datetime, timedelta
import calendar
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.security import secure_endpoint
from app.db.mongodb import get_tenant_db, get_platform_db, sanitize_bson_types
from app.config import get_settings
from app.tasks.queue import enqueue_job
from fastapi.encoders import jsonable_encoder
from app.db.schemas import AccountingTask, AccountingTaskStatus
from app.services.accounting_engine import AccountingEngine
from app.services.business_service import BusinessService

logger = structlog.get_logger()

# All endpoints require API key (only Accountia API can access)
router = APIRouter(dependencies=[Depends(secure_endpoint)])
settings = get_settings()


class CreateAccountingJobRequest(BaseModel):
    """Request to create an accounting job.
    
    The AI Accountant will look up the business's databaseName from the platform DB.
    Accepts both snake_case (business_id) and camelCase (businessId) field names.
    """
    business_id: str = Field(
        ...,
        alias="businessId",
        validation_alias="businessId",
        description="MongoDB ID of the business to process (business_id or businessId)",
        example="60d5ecb8b6f3c72e7c8e4a5b",
    )
    period_start: datetime = Field(..., alias="periodStart", validation_alias="periodStart", description="Start of accounting period (ISO format)", example="2024-01-01T00:00:00Z")
    period_end: datetime = Field(..., alias="periodEnd", validation_alias="periodEnd", description="End of accounting period (ISO format)", example="2024-01-31T23:59:59Z")
    
    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "business_id": "60d5ecb8b6f3c72e7c8e4a5b",
                "businessId": "60d5ecb8b6f3c72e7c8e4a5b",
                "period_start": "2024-01-01T00:00:00Z",
                "period_end": "2024-01-31T23:59:59Z",
                "periodStart": "2024-01-01T00:00:00Z",
                "periodEnd": "2024-01-31T23:59:59Z",
            }
        },
    }


class CreateAccountingJobResponse(BaseModel):
    """Response after creating an accounting job."""
    task_id: str = Field(..., alias="taskId", description="Unique task ID for this accounting job", example="60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131")
    status: str = Field(..., description="Current status: pending, processing, completed", example="pending")
    message: str = Field(..., description="Human-readable status message")
    estimated_seconds: Optional[int] = Field(None, alias="estimatedSeconds", description="Estimated seconds until completion")
    estimated_completion: Optional[datetime] = Field(None, alias="estimatedCompletion", description="Estimated completion timestamp (UTC)")
    model_config = {"populate_by_name": True}


class AccountingJobStatusResponse(BaseModel):
    """Status of an accounting job."""
    task_id: str = Field(..., alias="taskId", description="Unique task ID")
    business_id: str = Field(..., alias="businessId", description="Business ID")
    period_start: datetime = Field(..., alias="periodStart", description="Period start date")
    period_end: datetime = Field(..., alias="periodEnd", description="Period end date")
    status: str = Field(..., description="Status: pending, processing, completed, failed")
    progress_percent: int = Field(..., alias="progressPercent", description="Processing progress 0-100", ge=0, le=100)
    started_at: Optional[datetime] = Field(None, alias="startedAt", description="When processing started")
    completed_at: Optional[datetime] = Field(None, alias="completedAt", description="When processing completed")
    error_message: Optional[str] = Field(None, alias="errorMessage", description="Error message if failed")
    journal_entries_count: int = Field(0, alias="journalEntriesCount", description="Number of journal entries generated")
    reports_generated: int = Field(0, alias="reportsGenerated", description="Number of reports generated")
    # Time estimates
    estimated_seconds: Optional[int] = Field(None, alias="estimatedSeconds", description="Estimated total runtime in seconds")
    estimated_completion: Optional[datetime] = Field(None, alias="estimatedCompletion", description="Estimated completion timestamp (UTC)")
    estimated_time_remaining: Optional[int] = Field(None, alias="estimatedTimeRemaining", description="Estimated remaining time in seconds")
    model_config = {"populate_by_name": True}


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
    tax_calculations: list[TaxCalculationItem] = Field(..., alias="taxCalculations", description="Tax calculations breakdown")
    
    # AI Analysis
    ai_insights: str = Field(..., alias="aiInsights", description="AI-generated analysis and insights")
    recommendations: list[str] = Field(..., description="Actionable recommendations")
    anomalies_detected: list = Field(..., alias="anomaliesDetected", description="Detected anomalies or red flags")
    
    # Reports
    reports: list[dict] = Field(..., description="Generated financial reports (P&L, Balance Sheet, etc.)")
    
    # Journal Entries (full)
    journal_entries: list[JournalEntryPreview] = Field(..., alias="journalEntries", description="All journal entries for the period")
    total_journal_entries: int = Field(..., alias="totalJournalEntries", description="Total count of journal entries", ge=0)
    model_config = {"populate_by_name": True}


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
        
        # Save initial status using Beanie's save method
        await task.save()

        # Also sync to tenant DB so the tenant-facing endpoints can see updates
        try:
            tenant_db = get_tenant_db(database_name)
            # ensure indexes exist (idempotent)
            await tenant_db["accounting_tasks"].create_index("task_id", unique=True)
            await tenant_db["accounting_tasks"].create_index([
                ("business_id", 1),
                ("period_start", -1),
            ])
            # Use $set to update fields without overwriting the whole document
            await tenant_db["accounting_tasks"].update_one(
                {"task_id": task.task_id},
                {"$set": jsonable_encoder(task.model_dump())},
                upsert=True,
            )
        except Exception:
            logger.exception("[JOB SYNC] Failed to sync initial task to tenant DB")

        # Process
        task.progress_percent = 50
        completed_task = await engine.process_period(task)

        # Persist completed results to tenant DB (tenant is the authoritative store)
        try:
            tenant_db = get_tenant_db(database_name)
            payload = jsonable_encoder(completed_task.model_dump())
            # mark source and sync timestamp
            payload["processed_by"] = getattr(completed_task, "processed_by", "ai-accountant-v1")
            from datetime import datetime as _dt
            payload["last_synced_at"] = _dt.utcnow()
            await tenant_db["accounting_tasks"].update_one(
                {"task_id": completed_task.task_id},
                {"$set": payload},
                upsert=True,
            )
            logger.info("[JOB SYNC] Completed task written to tenant DB", task_id=completed_task.task_id)
        except Exception:
            logger.exception("[JOB SYNC] Failed to sync completed task to tenant DB")
        
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

        # Save failed status using Beanie's save method
        await task.save()

        # Sync failed status to tenant DB
        try:
            tenant_db = get_tenant_db(database_name)
            payload = jsonable_encoder(task.model_dump())
            from datetime import datetime as _dt
            payload["last_synced_at"] = _dt.utcnow()
            await tenant_db["accounting_tasks"].update_one(
                {"task_id": task.task_id},
                {"$set": payload},
                upsert=True,
            )
        except Exception:
            logger.exception("[JOB SYNC] Failed to sync failed task to tenant DB")


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
    
    logger.info(
        "[JOB CREATE] Request received",
        business_id=request.business_id,
        period_start=request.period_start.isoformat(),
        period_end=request.period_end.isoformat(),
    )
    
    # Validate period
    period_days = (request.period_end - request.period_start).days
    logger.debug("[JOB CREATE] Validating period", period_days=period_days)
    
    if period_days > 365:
        logger.warning("[JOB CREATE] Period too long", period_days=period_days)
        raise HTTPException(
            status_code=400,
            detail="Accounting period cannot exceed 365 days",
        )
    
    if request.period_end < request.period_start:
        logger.warning("[JOB CREATE] Invalid period range")
        raise HTTPException(
            status_code=400,
            detail="Period end must be after period start",
        )
    
    # Look up business database name from platform DB
    logger.debug("[JOB CREATE] Looking up business database", business_id=request.business_id)
    try:
        database_name = await BusinessService.get_database_name(request.business_id)
        logger.debug("[JOB CREATE] Database name resolved", database_name=database_name)
    except ValueError as e:
        logger.error("[JOB CREATE] Business lookup failed", business_id=request.business_id, error=str(e))
        raise HTTPException(status_code=404, detail=str(e))
    
    task_id = generate_task_id(
        request.business_id,
        request.period_start,
        request.period_end,
    )
    logger.info("[JOB CREATE] Generated task ID", task_id=task_id)
    
    # Check if task already exists
    tenant_db = get_tenant_db(database_name)
    logger.debug("[JOB CREATE] Checking for existing task")
    existing = await tenant_db["accounting_tasks"].find_one({"task_id": task_id})
    
    if existing and existing.get("status") == AccountingTaskStatus.COMPLETED:
        logger.info("[JOB CREATE] Task already completed", task_id=task_id)
        return CreateAccountingJobResponse(
            task_id=task_id,
            status="completed",
            message="Accounting for this period has already been completed. Use GET /jobs/{task_id} to retrieve results.",
            estimated_seconds=existing.get("estimated_seconds"),
            estimated_completion=existing.get("estimated_completion"),
        ).model_dump(by_alias=True)
    
    if existing and existing.get("status") == AccountingTaskStatus.PROCESSING:
        logger.info("[JOB CREATE] Task already processing", task_id=task_id)
        return CreateAccountingJobResponse(
            task_id=task_id,
            status="processing",
            message="Accounting job already in progress.",
            estimated_seconds=existing.get("estimated_seconds"),
            estimated_completion=existing.get("estimated_completion"),
        ).model_dump(by_alias=True)
    
    # Create new task
    logger.debug("[JOB CREATE] Creating AccountingTask object")
    try:
        task = AccountingTask(
                business_id=request.business_id,
                task_id=task_id,
                period_start=request.period_start,
                period_end=request.period_end,
                status=AccountingTaskStatus.PENDING,
            )
        logger.debug("[JOB CREATE] Task object created", task_dict=task.model_dump())
    except Exception as e:
        logger.error("[JOB CREATE] Failed to create task object", error=str(e), exc_info=True)
        raise
    
    # Add time estimate before saving so it's persisted and visible to list endpoints
    estimated_seconds = min(30 + period_days, 300)  # Rough estimate
    task.estimated_seconds = estimated_seconds
    task.estimated_completion = datetime.utcnow() + timedelta(seconds=estimated_seconds)

    # Save to DB using Beanie's save method for proper serialization
    logger.debug("[JOB CREATE] Saving task to database")
    try:
        await task.save()
        logger.info("[JOB CREATE] Task saved successfully", task_id=task_id)
    except Exception as e:
        logger.error("[JOB CREATE] Failed to save task", error=str(e), task_id=task_id, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}")

    # Also persist a copy in the tenant DB collection so tenant-facing endpoints
    # (which read directly from the tenant DB) will see the task immediately.
    try:
        # ensure indexes (idempotent)
        await tenant_db["accounting_tasks"].create_index("task_id", unique=True)
        await tenant_db["accounting_tasks"].create_index([
            ("business_id", 1),
            ("period_start", -1),
        ])
        await tenant_db["accounting_tasks"].update_one(
            {"task_id": task_id},
            {"$set": jsonable_encoder(task.model_dump())},
            upsert=True,
        )
        logger.debug("[JOB CREATE] Task synced to tenant DB", task_id=task_id)
    except Exception as e:
        logger.exception("[JOB CREATE] Failed to sync task to tenant DB", task_id=task_id, error=str(e))
    
    # Start background processing
    logger.info(
        "[JOB CREATE] Starting background processing",
        task_id=task_id,
        business_id=request.business_id,
        period_start=request.period_start.isoformat(),
        period_end=request.period_end.isoformat(),
        database_name=database_name,
    )
    
    # If configured, enqueue the job to Redis queue so a worker can process it.
    if settings.use_task_queue:
        try:
            await enqueue_job({
                "task_id": task_id,
                "database_name": database_name,
            })
            logger.info("[JOB CREATE] Enqueued job to Redis queue", task_id=task_id)
        except Exception:
            logger.exception("[JOB CREATE] Failed to enqueue job, falling back to background task")
            background_tasks.add_task(
                process_accounting_task,
                task,
                database_name,
            )
    else:
        background_tasks.add_task(
            process_accounting_task,
            task,
            database_name,
        )
    
    logger.info("[JOB CREATE] Returning success response", task_id=task_id, estimated_seconds=task.estimated_seconds)

    return CreateAccountingJobResponse(
        task_id=task_id,
        status="pending",
        message=f"Accounting job created for period {request.period_start.date()} to {request.period_end.date()}",
        estimated_seconds=task.estimated_seconds,
        estimated_completion=task.estimated_completion,
    ).model_dump(by_alias=True)


@router.get(
    "/jobs",
    summary="List Accounting Jobs",
    description="List all accounting jobs for a business with optional filtering.",
    response_description="List of accounting job summaries",
)
async def list_accounting_jobs(
    business_id: str = Query(..., alias="businessId", description="Business ID"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of records to return"),
):
    """List accounting jobs for a business."""
    
    # Look up database name from platform DB
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    tenant_db = get_tenant_db(database_name)
    # Project only the fields we need to reduce IO
    projection = {
        "task_id": 1,
        "business_id": 1,
        "period_start": 1,
        "period_end": 1,
        "status": 1,
        "progress_percent": 1,
        "started_at": 1,
        "completed_at": 1,
        "journal_entries": 1,
        "reports": 1,
        "estimated_seconds": 1,
        "estimated_completion": 1,
    }
    cursor = tenant_db["accounting_tasks"].find(
        {"business_id": business_id}, projection
    ).sort("created_at", -1).limit(limit)

    tasks = await cursor.to_list(length=limit)
    tasks = [sanitize_bson_types(t) for t in tasks]

    return {
        "businessId": business_id,
        "jobs": [
            {
                "taskId": t["task_id"],
                "periodStart": t["period_start"],
                "periodEnd": t["period_end"],
                "status": t["status"],
                "progressPercent": t.get("progress_percent", 0),
                "estimatedSeconds": t.get("estimated_seconds"),
                "estimatedCompletion": t.get("estimated_completion"),
                "estimatedTimeRemaining": None,
                "startedAt": t.get("started_at"),
                "completedAt": t.get("completed_at"),
                "journalEntriesCount": len(t.get("journal_entries", [])),
                "reportsGenerated": len(t.get("reports", [])),
            }
            for t in tasks
        ],
    }


@router.get(
    "/jobs/{task_id}",
    response_model=AccountingJobStatusResponse,
    summary="Get Job Status",
    description="Check the current status of an accounting job. Poll this endpoint to track progress until completion.",
    response_description="Current job status including progress percent and counts",
)
async def get_job_status(
    task_id: str,
    business_id: str = Query(..., alias="businessId", description="Business ID"),
):
    """Get the status of an accounting job."""
    
    # Look up database name from platform DB
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    tenant_db = get_tenant_db(database_name)
    task_data = await tenant_db["accounting_tasks"].find_one({"task_id": task_id})
    task_data = sanitize_bson_types(task_data)
    
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    
    resp = AccountingJobStatusResponse(
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
        estimated_seconds=task_data.get("estimated_seconds"),
        estimated_completion=task_data.get("estimated_completion"),
        estimated_time_remaining=(
            max(0, int((task_data.get("estimated_seconds", 0) - ((datetime.utcnow() - task_data.get("started_at")).total_seconds()))) )
            if task_data.get("status") in ["processing", "pending"] and task_data.get("estimated_seconds") and task_data.get("started_at")
            else None
        ),
    )
    return resp.model_dump(by_alias=True)


@router.get(
    "/jobs/{task_id}/results",
    response_model=AccountingResultsResponse,
    summary="Get Job Results",
    description="Retrieve full accounting results including financial summary, tax calculations, AI insights, journal entries preview, and generated reports. Only available after job completes.",
    response_description="Complete accounting results with journal entries, taxes, and AI analysis",
)
async def get_job_results(
    task_id: str,
    business_id: str = Query(..., alias="businessId", description="Business ID"),
):
    """Get the full accounting results for a completed job."""
    
    # Look up database name from platform DB
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    tenant_db = get_tenant_db(database_name)
    task_data = await tenant_db["accounting_tasks"].find_one({"task_id": task_id})
    task_data = sanitize_bson_types(task_data)
    
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task_data["status"] != AccountingTaskStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Task not completed. Current status: {task_data['status']}",
        )
    
    summary = task_data.get("financial_summary", {})
    journal_entries = task_data.get("journal_entries", [])
    
    # Return full list of journal entries (convert amounts to floats)
    entries_all = [
        {
            "date": e["date"],
            "account": e["account"],
            "debit": float(e.get("debit", 0)),
            "credit": float(e.get("credit", 0)),
            "description": e.get("description", ""),
            **({"invoiceId": e.get("invoice_id")} if e.get("invoice_id") else {}),
            **({"metadata": e.get("metadata")} if e.get("metadata") else {}),
        }
        for e in journal_entries
    ]
    
    resp = AccountingResultsResponse(
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
        journal_entries=entries_all,
        total_journal_entries=len(journal_entries),
    )
    return resp.model_dump(by_alias=True)


@router.delete(
    "/jobs/{task_id}",
    summary="Cancel Accounting Job",
    description="Cancel a pending or processing accounting job. Cannot cancel completed or failed jobs.",
    response_description="Cancellation confirmation",
)
async def cancel_accounting_job(
    task_id: str,
    business_id: str = Query(..., alias="businessId", description="Business ID"),
):
    """Cancel an accounting job if it's still pending or processing."""
    
    # Look up database name from platform DB
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    tenant_db = get_tenant_db(database_name)
    task_data = await tenant_db["accounting_tasks"].find_one({"task_id": task_id})
    
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    
    current_status = task_data.get("status")
    
    # Can only cancel pending or processing jobs
    if current_status not in [AccountingTaskStatus.PENDING, AccountingTaskStatus.PROCESSING]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status '{current_status}'. Only pending or processing jobs can be cancelled.",
        )
    
    # Prevent cancelling if platform record is already completed
    try:
        platform_db = get_platform_db()
        platform_task = await platform_db["accounting_tasks"].find_one({"task_id": task_id})
        if platform_task and platform_task.get("status") == AccountingTaskStatus.COMPLETED:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job; platform record already completed for task {task_id}",
            )
    except HTTPException:
        raise
    except Exception:
        # If platform DB not available, proceed with tenant cancellation but log
        logger.exception("platform_db_check_failed", task_id=task_id)

    # Update status to cancelled in both tenant and platform DBs (best-effort)
    cancel_payload = {
        "$set": {
            "status": AccountingTaskStatus.CANCELLED,
            "completed_at": datetime.utcnow(),
            "error_message": "Job cancelled by user",
        }
    }
    # Tenant update (authoritative for tenant API)
    try:
        await tenant_db["accounting_tasks"].update_one({"task_id": task_id}, cancel_payload)
    except Exception:
        logger.exception("tenant_cancel_failed", task_id=task_id)

    # Platform update (best-effort) to keep records in sync
    try:
        platform_db = get_platform_db()
        await platform_db["accounting_tasks"].update_one({"task_id": task_id}, cancel_payload)
    except Exception:
        logger.exception("platform_cancel_failed", task_id=task_id)
    
    return {
        "taskId": task_id,
        "status": "cancelled",
        "message": "Accounting job cancelled successfully",
        "previousStatus": current_status,
    }


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
    tasks = [sanitize_bson_types(t) for t in tasks]
    return {
        "businessId": business_id,
        "tasks": [
            {
                "taskId": t["task_id"],
                "periodStart": t["period_start"],
                "periodEnd": t["period_end"],
                "status": t["status"],
                "completedAt": t.get("completed_at"),
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
    tasks = [sanitize_bson_types(t) for t in tasks]
    
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
        "businessId": business_id,
        "databaseName": database_name,
        "summary": {
            "totalAccountingPeriods": len(tasks),
            "completed": sum(1 for t in tasks if t.get("status") == "completed"),
            "pending": sum(1 for t in tasks if t.get("status") == "pending"),
            "processing": sum(1 for t in tasks if t.get("status") == "processing"),
            "failed": sum(1 for t in tasks if t.get("status") == "failed"),
            "totalJournalEntriesGenerated": total_journal_entries,
            "totalRevenueProcessed": total_revenue,
        },
        "accountingPeriods": [
            {
                "taskId": t["task_id"],
                "periodStart": t["period_start"],
                "periodEnd": t["period_end"],
                "status": t["status"],
                "createdAt": t.get("created_at"),
                "startedAt": t.get("started_at"),
                "completedAt": t.get("completed_at"),
                "journalEntriesCount": len(t.get("journal_entries", [])),
                "taxCalculationsCount": len(t.get("tax_calculations", [])),
                "reportsCount": len(t.get("reports", [])),
                "hasAiInsights": bool(t.get("ai_insights")),
                "recommendationsCount": len(t.get("recommendations", [])),
                "financialSummary": t.get("financial_summary"),
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
    year: int = Query(None, description="Year to fetch taxes for (default: current year)"),
):
    """Return a persisted Tunisian tax summary for a business and year.

    If a summary does not exist, returns 404 telling the caller to POST to calculate.
    """
    # Resolve year
    if not year:
        year = datetime.utcnow().year

    # Look up database name from platform DB
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    tenant_db = get_tenant_db(database_name)

    # Try to find persisted summary
    summary_doc = await tenant_db["tax_summaries"].find_one({"business_id": business_id, "year": year})
    if not summary_doc:
        raise HTTPException(
            status_code=404,
            detail=f"Tax summary for year {year} not found. POST /business/{business_id}/taxes/calculate?year={year} to compute it.",
        )

    summary_doc = sanitize_bson_types(summary_doc)

    # Build camelCase response from persisted snake_case document
    return {
        "businessId": summary_doc.get("business_id", business_id),
        "businessName": summary_doc.get("business_name", "Unknown"),
        "year": summary_doc.get("year", year),
        "currency": summary_doc.get("currency", "TND"),
        "summary": {
            "annualVatTotal": summary_doc.get("summary", {}).get("annual_vat_total", 0),
            "annualCorporateTax": summary_doc.get("summary", {}).get("annual_corporate_tax", 0),
            "annualWithholdingTax": summary_doc.get("summary", {}).get("annual_withholding_tax", 0),
            "totalTaxLiability": summary_doc.get("summary", {}).get("total_tax_liability", 0),
        },
        "vatBreakdown": {
            "standardRate19Percent": summary_doc.get("vat_breakdown", {}).get("standard_rate_19_percent", 0),
            "reducedRate13Percent": summary_doc.get("vat_breakdown", {}).get("reduced_rate_13_percent", 0),
            "reducedRate7Percent": summary_doc.get("vat_breakdown", {}).get("reduced_rate_7_percent", 0),
        },
        "monthlyDetails": [
            {
                "month": m.get("month"),
                "period": m.get("period"),
                "vatStandard19": m.get("vat_standard_19"),
                "vatReduced13": m.get("vat_reduced_13"),
                "vatReduced7": m.get("vat_reduced_7"),
                "vatTotal": m.get("vat_total"),
                "taxableIncome": m.get("taxable_income"),
                "corporateTaxDue": m.get("corporate_tax_due"),
                "withholdingTax": m.get("withholding_tax"),
                "totalTaxLiability": m.get("total_tax_liability"),
                "dueDate": m.get("due_date"),
            }
            for m in summary_doc.get("monthly_details", [])
        ],
        "taxCalendar": [
            {
                "period": d.get("period"),
                "dueDate": (d.get("vat_due_date") or d.get("due_date")).isoformat() if (d.get("vat_due_date") or d.get("due_date")) else None,
                "description": d.get("description"),
            }
            for d in summary_doc.get("tax_calendar", [])
        ],
        "notes": summary_doc.get("notes", []),
        "createdAt": summary_doc.get("created_at"),
        "lastUpdatedAt": summary_doc.get("last_updated_at"),
    }



@router.post(
    "/business/{business_id}/taxes/calculate",
    summary="Calculate and persist Tunisian Tax Summary",
    description="Calculate taxes for a year and persist the summary if not already present.",
    response_description="Persisted tax summary in camelCase",
)
async def calculate_tunisian_tax_summary(
    business_id: str,
    year: int = Query(None, description="Year to calculate taxes for (default: current year)"),
):
    """Calculate taxes for a business and year and persist the result if absent.

    If a summary already exists, returns the existing summary.
    """
    from app.services.tax_service import TunisianTaxService

    # Resolve year
    if not year:
        year = datetime.utcnow().year

    # Look up database name
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    tenant_db = get_tenant_db(database_name)

    # Check existing
    existing = await tenant_db["tax_summaries"].find_one({"business_id": business_id, "year": year})
    if existing:
        existing = sanitize_bson_types(existing)
        return {
            "message": "Tax summary already exists",
            **{
                "businessId": existing.get("business_id", business_id),
                "year": existing.get("year", year),
            },
        }

    # Fetch invoices and products
    start_of_year = datetime(year, 1, 1)
    end_of_year = datetime(year, 12, 31, 23, 59, 59)

    invoices_cursor = tenant_db["invoices"].find({
        "issuerBusinessId": {"$in": [business_id]},
        "issuedDate": {"$gte": start_of_year, "$lte": end_of_year},
    })
    invoices = await invoices_cursor.to_list(length=None)

    products_cursor = tenant_db["products"].find({"businessId": {"$in": [business_id]}})
    products = await products_cursor.to_list(length=None)

    tax_service = TunisianTaxService()

    monthly_taxes = []
    for month in range(1, 13):
        month_start = datetime(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        month_end = datetime(year, month, last_day, 23, 59, 59)

        month_invoices = [
            inv for inv in invoices
            if month_start <= inv.get("issuedDate", datetime.utcnow()) <= month_end
        ]

        if month_invoices:
            tax_breakdown = tax_service.calculate_period_taxes(
                business_id, month_invoices, products, month_start, month_end
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
                "due_date": tax_breakdown.due_date,
            })

    annual_vat = sum(m["vat_total"] for m in monthly_taxes)
    annual_corp_tax = sum(m["corporate_tax_due"] for m in monthly_taxes)
    annual_withholding = sum(m["withholding_tax"] for m in monthly_taxes)

    tax_calendar = tax_service.get_tax_calendar(year)

    # Get business info if available
    try:
        business_info = await BusinessService.get_business_info(business_id)
        business_name = business_info.get("name")
    except Exception:
        business_name = None

    # Persist snake_case document
    doc = {
        "business_id": business_id,
        "business_name": business_name or "Unknown",
        "year": year,
        "currency": "TND",
        "summary": {
            "annual_vat_total": annual_vat,
            "annual_corporate_tax": annual_corp_tax,
            "annual_withholding_tax": annual_withholding,
            "total_tax_liability": annual_vat + annual_corp_tax + annual_withholding,
        },
        "vat_breakdown": {
            "standard_rate_19_percent": annual_vat,
            "reduced_rate_13_percent": 0,
            "reduced_rate_7_percent": 0,
        },
        "monthly_details": monthly_taxes,
        "tax_calendar": tax_calendar,
        "notes": [
            "VAT (TVA) is due by the 28th of the following month",
            "Standard VAT rate: 19%",
            "Reduced rates: 13% (transport, tourism), 7% (medical, education)",
            "Corporate tax (IS): 15% for SMEs, 25% for larger companies",
            "Withholding tax: 1.5% on B2B transactions",
        ],
        "created_at": datetime.utcnow(),
        "last_updated_at": datetime.utcnow(),
    }

    try:
        await tenant_db["tax_summaries"].create_index([("business_id", 1), ("year", 1)], unique=True)
        await tenant_db["tax_summaries"].update_one(
            {"business_id": business_id, "year": year},
            {"$set": doc},
            upsert=True,
        )
    except Exception:
        logger.exception("Failed to persist tax summary to tenant DB")
        raise HTTPException(status_code=500, detail="Failed to persist tax summary")

    # Build camelCase response
    return {
        "businessId": doc["business_id"],
        "businessName": doc["business_name"],
        "year": doc["year"],
        "currency": doc["currency"],
        "summary": {
            "annualVatTotal": doc["summary"]["annual_vat_total"],
            "annualCorporateTax": doc["summary"]["annual_corporate_tax"],
            "annualWithholdingTax": doc["summary"]["annual_withholding_tax"],
            "totalTaxLiability": doc["summary"]["total_tax_liability"],
        },
        "vatBreakdown": {
            "standardRate19Percent": doc["vat_breakdown"]["standard_rate_19_percent"],
            "reducedRate13Percent": doc["vat_breakdown"]["reduced_rate_13_percent"],
            "reducedRate7Percent": doc["vat_breakdown"]["reduced_rate_7_percent"],
        },
        "monthlyDetails": [
            {
                "month": m.get("month"),
                "period": m.get("period"),
                "vatStandard19": m.get("vat_standard_19"),
                "vatReduced13": m.get("vat_reduced_13"),
                "vatReduced7": m.get("vat_reduced_7"),
                "vatTotal": m.get("vat_total"),
                "taxableIncome": m.get("taxable_income"),
                "corporateTaxDue": m.get("corporate_tax_due"),
                "withholdingTax": m.get("withholding_tax"),
                "totalTaxLiability": m.get("total_tax_liability"),
                "dueDate": m.get("due_date").isoformat() if m.get("due_date") else None,
            }
            for m in doc.get("monthly_details", [])
        ],
        "taxCalendar": [
            {
                "period": d.get("period"),
                "dueDate": (d.get("vat_due_date") or d.get("due_date")).isoformat() if (d.get("vat_due_date") or d.get("due_date")) else None,
                "description": d.get("description"),
            }
            for d in doc.get("tax_calendar", [])
        ],
        "notes": doc.get("notes", []),
        "createdAt": doc.get("created_at"),
        "lastUpdatedAt": doc.get("last_updated_at"),
    }
