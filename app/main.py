import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.mongodb import close_mongodb, init_mongodb
from app.db.redis import close_redis, init_redis
from app.routers import accounting
from app.services.model_manager import ModelManager

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Accountia AI Accountant service...")
    
    # Initialize MongoDB connection
    await init_mongodb()
    
    # Initialize Redis (for caching)
    await init_redis()
    
    # Initialize model (in background for faster startup)
    asyncio.create_task(ModelManager.initialize())
    
    logger.info("Accountia AI Accountant service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Accountia AI Accountant service...")
    await close_mongodb()
    await close_redis()
    logger.info("Accountia AI Accountant service shut down")


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="AI-powered accounting service for Tunisian businesses. Provides automated journal entry generation, tax calculations (VAT, Corporate Tax, Withholding), financial reports, and AI insights.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {"name": "Accounting", "description": "Core accounting operations: create jobs, get results, tax calculations"},
        {"name": "System", "description": "Health checks and service info"},
    ],
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(accounting.router, prefix="/api/accounting", tags=["Accounting"])


@app.get("/", tags=["System"], summary="Service Info", description="Get service health and version information")
async def root():
    return {
        "service": "Accountia AI Accountant",
        "version": settings.version,
        "status": "operational",
        "description": "AI-powered accounting for Tunisian businesses"
    }
