"""Training API endpoints for fine-tuning the accounting LLM."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.business_service import BusinessService
from app.services.model_manager import ModelManager
from app.db.mongodb import get_tenant_db

logger = structlog.get_logger()
router = APIRouter()
settings = get_settings()


class TrainingDataRequest(BaseModel):
    """Request to generate training data."""
    num_examples: int = Field(default=1000, ge=100, le=10000)
    output_file: str = "training_data.jsonl"


class TrainingDataResponse(BaseModel):
    """Response after generating training data."""
    examples_generated: int
    output_file: str
    sample_prompt: str


class FineTuneRequest(BaseModel):
    """Request to start fine-tuning."""
    training_file: str = "training_data.jsonl"
    output_dir: Optional[str] = None
    num_epochs: int = Field(default=3, ge=1, le=10)
    batch_size: int = Field(default=4, ge=1, le=16)
    learning_rate: float = Field(default=2e-4, ge=1e-5, le=1e-2)


class FineTuneResponse(BaseModel):
    """Response after starting fine-tuning."""
    job_id: str
    status: str
    estimated_duration_minutes: int
    output_dir: str


class ModelStatusResponse(BaseModel):
    """Model status response."""
    initialized: bool
    base_model: str
    using_fine_tuned: bool
    device: str
    fine_tuned_path: Optional[str]


class TrainOnBusinessDataRequest(BaseModel):
    """Request to train/fine-tune on actual business data.
    
    The AI Accountant will:
    1. Look up the business from platform DB
    2. Export actual invoices and products from tenant DB
    3. Generate training examples from real business data
    4. Optionally start fine-tuning with this data
    """
    business_id: str
    period_months: int = Field(default=12, ge=3, le=24, description="How many months of data to export")
    output_file: str = "business_training_data.jsonl"
    auto_fine_tune: bool = Field(default=False, description="Whether to start fine-tuning immediately")


class TrainOnBusinessDataResponse(BaseModel):
    """Response after exporting business data for training."""
    business_id: str
    business_name: str
    database_name: str
    invoices_exported: int
    products_exported: int
    training_examples_generated: int
    output_file: str
    fine_tune_job_id: Optional[str] = None
    message: str


@router.get("/status", response_model=ModelStatusResponse)
async def get_model_status():
    """Get current model status."""
    info = ModelManager.get_model_info()
    return ModelStatusResponse(**info)


@router.post("/data/generate", response_model=TrainingDataResponse)
async def generate_training_data(request: TrainingDataRequest):
    """Generate synthetic training data for fine-tuning."""
    
    from training.scripts.generate_data import generate_accounting_dataset
    
    output_path = Path("training/data") / request.output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Generate in background to avoid timeout
    examples = await asyncio.to_thread(
        generate_accounting_dataset,
        num_examples=request.num_examples,
        output_path=str(output_path),
    )
    
    # Get a sample
    sample = examples[0] if examples else {}
    
    return TrainingDataResponse(
        examples_generated=len(examples),
        output_file=str(output_path),
        sample_prompt=sample.get("instruction", "")[:200] + "...",
    )


@router.post("/fine-tune", response_model=FineTuneResponse)
async def start_fine_tuning(
    request: FineTuneRequest,
    background_tasks: BackgroundTasks,
):
    """Start fine-tuning the accounting LLM."""
    
    training_path = Path("training/data") / request.training_file
    if not training_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Training file not found: {request.training_file}. Generate data first.",
        )
    
    output_dir = request.output_dir or settings.training_output_dir
    job_id = f"ft_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    
    # Start fine-tuning in background
    from training.scripts.fine_tune import run_fine_tuning
    
    background_tasks.add_task(
        run_fine_tuning,
        training_file=str(training_path),
        output_dir=output_dir,
        num_epochs=request.num_epochs,
        batch_size=request.batch_size,
        learning_rate=request.learning_rate,
        job_id=job_id,
    )
    
    # Estimate duration
    estimated_minutes = (request.num_epochs * 30) + 10  # Rough estimate
    
    return FineTuneResponse(
        job_id=job_id,
        status="started",
        estimated_duration_minutes=estimated_minutes,
        output_dir=output_dir,
    )


@router.post("/reload")
async def reload_model():
    """Reload the model (useful after fine-tuning)."""
    
    try:
        await ModelManager.initialize()
        info = ModelManager.get_model_info()
        return {
            "status": "reloaded",
            "model_info": info,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reload model: {str(e)}")


@router.get("/data/samples")
async def get_training_samples(n: int = Query(5, ge=1, le=20)):
    """Get sample training data examples."""
    
    from training.scripts.generate_data import generate_accounting_dataset
    
    examples = await asyncio.to_thread(
        generate_accounting_dataset,
        num_examples=n,
        output_path=None,  # Don't save, just return
    )
    
    return {
        "count": len(examples),
        "samples": examples,
    }


@router.post("/data/export-business", response_model=TrainOnBusinessDataResponse)
async def export_business_data_for_training(
    request: TrainOnBusinessDataRequest,
    background_tasks: BackgroundTasks,
):
    """
    Export actual business data and generate training examples.
    
    This endpoint:
    1. Looks up the business in platform DB
    2. Exports invoices and products from the tenant database
    3. Generates training examples from real business transactions
    4. Optionally starts fine-tuning
    """
    
    # Look up business
    try:
        business_info = await BusinessService.get_business_info(request.business_id)
        database_name = business_info.get("databaseName")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    # Connect to tenant DB
    tenant_db = get_tenant_db(database_name)
    
    # Calculate date range
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=30 * request.period_months)
    
    # Export invoices
    invoices_cursor = tenant_db["invoices"].find({
        "issuerBusinessId": {"$in": [request.business_id]},
        "issuedDate": {"$gte": start_date, "$lte": end_date},
    })
    invoices = await invoices_cursor.to_list(length=None)
    
    # Export products
    products_cursor = tenant_db["products"].find({
        "businessId": {"$in": [request.business_id]},
    })
    products = await products_cursor.to_list(length=None)
    
    if not invoices:
        raise HTTPException(
            status_code=400,
            detail=f"No invoices found for business in the last {request.period_months} months",
        )
    
    # Generate training examples from real data
    from training.scripts.generate_data_from_business import generate_from_business_data
    
    output_path = Path("training/data") / request.output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    examples = await asyncio.to_thread(
        generate_from_business_data,
        invoices=invoices,
        products=products,
        business_name=business_info.get("name", "Unknown"),
        output_path=str(output_path),
    )
    
    fine_tune_job_id = None
    message = f"Exported {len(invoices)} invoices and {len(products)} products. Generated {len(examples)} training examples."
    
    # Optionally start fine-tuning
    if request.auto_fine_tune and len(examples) >= 100:
        from training.scripts.fine_tune import run_fine_tuning
        
        job_id = f"ft_business_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        output_dir = f"./models/business_{request.business_id}_lora"
        
        background_tasks.add_task(
            run_fine_tuning,
            training_file=str(output_path),
            output_dir=output_dir,
            num_epochs=3,
            batch_size=4,
            learning_rate=2e-4,
            job_id=job_id,
        )
        
        fine_tune_job_id = job_id
        message += f" Fine-tuning started with job ID: {job_id}"
    elif request.auto_fine_tune:
        message += " Not enough data for fine-tuning (minimum 100 examples)."
    
    return TrainOnBusinessDataResponse(
        business_id=request.business_id,
        business_name=business_info.get("name", ""),
        database_name=database_name,
        invoices_exported=len(invoices),
        products_exported=len(products),
        training_examples_generated=len(examples),
        output_file=str(output_path),
        fine_tune_job_id=fine_tune_job_id,
        message=message,
    )
