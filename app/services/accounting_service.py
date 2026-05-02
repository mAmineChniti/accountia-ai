from typing import Any

from fastapi import HTTPException

from app.db.mongodb import get_tenant_db, sanitize_bson_types
from app.db.schemas import AccountingTaskStatus
from app.services.business_service import BusinessService


async def list_jobs(business_id: str, limit: int = 25) -> dict[str, Any]:
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    tenant_db = get_tenant_db(database_name)
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
    cursor = (
        tenant_db["accounting_tasks"].find({"business_id": business_id}, projection).sort("created_at", -1).limit(limit)
    )

    tasks = await cursor.to_list(length=limit)
    tasks = [sanitize_bson_types(t) for t in tasks]

    jobs = [
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
    ]

    return {"businessId": business_id, "jobs": jobs}


async def get_job_results(task_id: str, business_id: str) -> dict[str, Any]:
    try:
        database_name = await BusinessService.get_database_name(business_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    tenant_db = get_tenant_db(database_name)
    task_data = await tenant_db["accounting_tasks"].find_one({"task_id": task_id})
    task_data = sanitize_bson_types(task_data)

    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")

    if task_data["status"] != AccountingTaskStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Task not completed. Current status: {task_data['status']}",
        )

    summary = task_data.get("financial_summary", {})
    journal_entries = task_data.get("journal_entries", [])

    entries_all = [
        {
            "date": e["date"],
            "account": e["account"],
            "debit": float(e.get("debit", 0)),
            "credit": float(e.get("credit", 0)),
            "description": e.get("description", ""),
            **({"invoiceId": e.get("invoice_id")} if e.get("invoice_id") else {}),
        }
        for e in journal_entries
    ]

    resp = {
        "taskId": task_data["task_id"],
        "businessId": task_data["business_id"],
        "periodStart": task_data["period_start"],
        "periodEnd": task_data["period_end"],
        "status": task_data["status"],
        "totalRevenue": summary.get("total_revenue", 0),
        "totalExpenses": summary.get("total_expenses", 0),
        "grossProfit": summary.get("gross_profit", 0),
        "netProfit": summary.get("net_profit", 0),
        "accountsReceivable": summary.get("accounts_receivable", 0),
        "accountsPayable": summary.get("accounts_payable", 0),
        "cashPosition": summary.get("cash_position", 0),
        "taxCalculations": task_data.get("tax_calculations", []),
        "aiInsights": task_data.get("ai_insights", ""),
        "recommendations": task_data.get("recommendations", []),
        "anomaliesDetected": task_data.get("anomalies_detected", []),
        "reports": task_data.get("reports", []),
        "journalEntries": entries_all,
        "totalJournalEntries": len(journal_entries),
    }

    return resp
