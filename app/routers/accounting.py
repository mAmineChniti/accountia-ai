"""Accounting API endpoints."""

from datetime import datetime, timedelta

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Path, Query
from fastapi.encoders import jsonable_encoder

from app.db.mongodb import get_tenant_db, sanitize_bson_types
from app.db.schemas import AccountingTask, AccountingTaskStatus
from app.models.accounting import (
    AccountingResultsResponse,
    CreateAccountingJobRequest,
    CreateAccountingJobResponse,
    JobsListResponse,
    TaxPersistResponse,
    TaxResultsResponse,
)
from app.models.common import ErrorResponse
from app.services import accounting_service
from app.services.accounting_engine import AccountingEngine
from app.services.business_service import BusinessService
from app.services.llm_service import get_llm_service
from app.services.tax_service import TunisianTaxService
from app.services.tiny_analyzer import TinyAccountingAnalyzer

logger = structlog.get_logger()


router = APIRouter(tags=["Accounting"])


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
            await tenant_db["accounting_tasks"].create_index(
                [
                    ("business_id", 1),
                    ("period_start", -1),
                ]
            )
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

        duration_seconds = (
            (completed_task.completed_at - task.started_at).total_seconds()
            if completed_task.completed_at and task.started_at
            else 0
        )
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
    description=(
        "Start AI accounting for a business period. The AI looks up the database, reads invoices, "
        "generates journal entries, and calculates taxes. Returns a task ID to poll for completion."
    ),
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
        raise HTTPException(status_code=404, detail=str(e)) from e

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

    if existing and existing.get("status") == AccountingTaskStatus.COMPLETED.value:
        logger.info("[JOB CREATE] Task already completed", task_id=task_id)
        return CreateAccountingJobResponse(
            task_id=task_id,
            business_id=request.business_id,
            status="completed",
            message=(
                "Accounting for this period has already been completed. Use GET /jobs/{task_id} to retrieve results."
            ),
            estimated_seconds=existing.get("estimated_seconds"),
            estimated_completion=existing.get("estimated_completion"),
        ).model_dump(by_alias=True)

    if existing and existing.get("status") == AccountingTaskStatus.PROCESSING.value:
        logger.info("[JOB CREATE] Task already processing", task_id=task_id)
        return CreateAccountingJobResponse(
            task_id=task_id,
            business_id=request.business_id,
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
        raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}") from e

    # Also persist a copy in the tenant DB collection so tenant-facing endpoints
    # (which read directly from the tenant DB) will see the task immediately.
    try:
        # ensure indexes (idempotent)
        await tenant_db["accounting_tasks"].create_index("task_id", unique=True)
        await tenant_db["accounting_tasks"].create_index(
            [
                ("business_id", 1),
                ("period_start", -1),
            ]
        )
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

    # Start background processing
    background_tasks.add_task(
        process_accounting_task,
        task,
        database_name,
    )

    logger.info(
        "[JOB CREATE] Returning success response",
        task_id=task_id,
        estimated_seconds=task.estimated_seconds,
    )

    return CreateAccountingJobResponse(
        task_id=task_id,
        business_id=request.business_id,
        status="pending",
        message=f"Accounting job created for period {request.period_start.date()} to {request.period_end.date()}",
        estimated_seconds=task.estimated_seconds,
        estimated_completion=task.estimated_completion,
    ).model_dump(by_alias=True)


@router.get(
    "/jobs",
    response_model=JobsListResponse,
    summary="List Accounting Jobs",
    description="List all accounting jobs for a business with optional filtering.",
    response_description="List of accounting job summaries",
)
async def list_accounting_jobs(
    business_id: str = Query(..., alias="businessId", description="Business ID"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of records to return"),
):
    """List accounting jobs for a business."""

    # Delegate DB access to service layer
    result = await accounting_service.list_jobs(business_id, limit)
    return result


@router.get(
    "/jobs/{task_id}",
    response_model=AccountingResultsResponse,
    summary="Get Job Results",
    description=(
        "Retrieve full accounting results including financial summary, tax calculations, "
        "AI insights, journal entries preview, and generated reports. Only available after job completes."
    ),
    response_description="Complete accounting results with journal entries, taxes, and AI analysis",
    responses={
        200: {"model": AccountingResultsResponse, "description": "Complete accounting results"},
        400: {"description": "Task not completed or invalid request"},
        404: {"description": "Task or business not found"},
    },
)
async def get_job_results(
    task_id: str = Path(
        ...,
        description="Task ID (string)",
        examples={"taskId": {"summary": "Example task id", "value": "task_123"}},
    ),
    business_id: str = Query(
        ...,
        alias="businessId",
        description="Business ID (string)",
        examples={"businessId": {"summary": "Example business id", "value": "biz_001"}},
    ),
):
    """Get the full accounting results for a completed job."""
    # Delegate to service layer
    result = await accounting_service.get_job_results(task_id, business_id)
    return result


@router.post(
    "/taxes/{business_id}/{year}",
    response_model=TaxPersistResponse,
    summary="Calculate taxes for year and persist the result",
    description=(
        "Calculate Tunisian taxes for the specified year for a business, run a lightweight analysis, "
        "and persist the summarized result for later retrieval. This endpoint performs read-only "
        "operations on tenant data (invoices/products) and writes a `tax_results` document."
    ),
    responses={
        200: {"description": "Acknowledgement that tax results were persisted"},
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        404: {"model": ErrorResponse, "description": "Business not found"},
        500: {"model": ErrorResponse, "description": "Failed to persist tax results"},
    },
)
async def calculate_taxes_for_year(business_id: str, year: int):
    """Calculate Tunisian taxes for the given year and persist result for later retrieval.

    Returns a brief acknowledgement with location of persisted result.
    """
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    tenant_db = get_tenant_db(database_name)

    from datetime import datetime

    start = datetime(year, 1, 1)
    end = datetime(year, 12, 31)

    invoices = await tenant_db["invoices"].find({"issuedDate": {"$gte": start, "$lte": end}}).to_list(length=None)
    products = await tenant_db["products"].find({}).to_list(length=None)

    tax_service = TunisianTaxService()
    breakdown = tax_service.calculate_period_taxes(business_id, invoices, products, start, end)

    # Build a simple summary for analyzer
    total_revenue = sum(float(inv.get("totalAmount", 0) or 0) for inv in invoices)
    summary = {
        "total_revenue": total_revenue,
        "total_expenses": 0,
        "net_profit": total_revenue,
        "gross_profit": total_revenue,
        "accounts_receivable": 0,
        "accounts_payable": 0,
        "cash_position": sum(float(inv.get("amountPaid", 0) or 0) for inv in invoices),
    }

    try:
        analysis = await TinyAccountingAnalyzer.analyze(invoices=invoices, journal_entries=[], summary=summary)
    except Exception:
        analysis = {"insights": "Analysis unavailable", "recommendations": [], "anomalies": []}

    # Enhance recommendations using Groq LLM (if configured).
    try:
        llm = get_llm_service()
        # Build a concise prompt for recommendations
        prompt = (
            "Given the following tax breakdown and financial summary for business "
            f"{business_id} in {year}, produce concise, actionable tax recommendations "
            '(max 6) in JSON: {"recommendations": [...], "shortSummary": "..."}.\n'
            f"Tax breakdown: {str(breakdown)}\nSummary: {summary}"
        )

        output_schema = {
            "type": "object",
            "properties": {
                "recommendations": {"type": "array", "items": {"type": "string"}},
                "shortSummary": {"type": "string"},
            },
            "required": ["recommendations", "shortSummary"],
        }

        try:
            llm_result = await llm.generate_structured(prompt, output_schema)
        except Exception:
            llm_result = None

        # Prepare top-level LLM fields
        llm_recommendations: list | None = None
        llm_summary: str | None = None

        if llm_result:
            # Merge LLM recommendations into analyzer output
            analysis.setdefault("recommendations", [])
            if isinstance(llm_result.get("recommendations"), list):
                analysis["recommendations"].extend(llm_result.get("recommendations"))
                llm_recommendations = llm_result.get("recommendations")
            # Attach short LLM summary for UI
            llm_summary = llm_result.get("shortSummary")
            analysis["llmSummary"] = llm_summary
    except Exception:
        # LLM service not configured or unavailable
        pass

    # Ensure analysis shape is consistent for persistence/response
    if analysis is None:
        analysis = {"insights": "Analysis unavailable", "recommendations": [], "anomalies": []}
    analysis.setdefault("insights", "")
    analysis.setdefault("recommendations", [])

    # If there are recommendations, add a short summary into `insights` so UIs
    # that display `insights` (string) will surface recommendations.
    try:
        if analysis.get("recommendations"):
            short_recs = "; ".join(str(r) for r in analysis.get("recommendations")[:3])
            if short_recs:
                if analysis["insights"]:
                    analysis["insights"] = f"{analysis['insights'].strip()}\nRecommendations: {short_recs}"
                else:
                    analysis["insights"] = f"Recommendations: {short_recs}"
    except Exception:
        # Best effort; do not fail tax persistence
        pass

    # Serialize breakdown dataclass to plain dict
    try:
        tax_info = breakdown.model_dump()
    except Exception:
        tax_info = sanitize_bson_types(getattr(breakdown, "__dict__", breakdown))

    # Persist a simple tax result document for later retrieval
    doc = {
        "business_id": business_id,
        "year": year,
        "tax_breakdown": tax_info,
        "analysis": analysis,
        "llm_recommendations": llm_recommendations,
        "llm_summary": llm_summary,
        "created_at": datetime.utcnow(),
        "last_updated_at": datetime.utcnow(),
    }

    try:
        await tenant_db["tax_results"].create_index([("business_id", 1), ("year", 1)], unique=True)
        await tenant_db["tax_results"].update_one(
            {"business_id": business_id, "year": year}, {"$set": doc}, upsert=True
        )
    except Exception:
        logger.exception("failed_to_persist_tax_result", business_id=business_id, year=year)

    return {"businessId": business_id, "year": year, "success": True}


@router.get(
    "/taxes/{business_id}/{year}",
    response_model=TaxResultsResponse,
    summary="Get persisted tax results for year",
    description=(
        "Retrieve previously persisted tax calculations and analysis for a business and year. "
        "Returns tax breakdown, analysis, and (when available) LLM-generated recommendations and summary."
    ),
    responses={
        200: {"model": TaxResultsResponse, "description": "Persisted tax results"},
        404: {"model": ErrorResponse, "description": "Tax results not found for the given business/year"},
    },
)
async def get_tax_results(
    business_id: str = Path(
        ...,
        description="Business ID (string)",
        examples={"businessId": {"summary": "Example business id", "value": "biz_001"}},
    ),
    year: int = Path(
        ...,
        description="Calendar year (YYYY)",
        examples={"year": {"summary": "Example year", "value": 2024}},
    ),
):
    """Return persisted tax results for a given business and year."""
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    tenant_db = get_tenant_db(database_name)

    doc = await tenant_db["tax_results"].find_one({"business_id": business_id, "year": year})
    doc = sanitize_bson_types(doc)

    if not doc:
        # Return success:false instead of 404 when taxes not found
        return {
            "success": False,
            "message": f"Tax results not found for year {year}.",
        }

    # Convert stored fields to camelCase in the response and include LLM fields if present
    return {
        "success": True,
        "businessId": doc.get("business_id"),
        "year": doc.get("year"),
        "taxBreakdown": doc.get("tax_breakdown"),
        "analysis": doc.get("analysis"),
        "llmRecommendations": doc.get("llm_recommendations"),
        "llmSummary": doc.get("llm_summary"),
        "createdAt": doc.get("created_at"),
        "lastUpdatedAt": doc.get("last_updated_at"),
    }
