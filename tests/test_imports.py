"""Tests that all core modules can be imported."""


def test_import_main_app():
    """Test main FastAPI app imports."""
    from app.main import app
    assert app is not None
    assert app.title == "Accountia AI Accountant"


def test_import_config():
    """Test config imports."""
    from app.config import get_settings, Settings
    assert get_settings is not None
    assert Settings is not None


def test_import_routers():
    """Test all routers import."""
    from app.routers import accounting, health
    assert accounting.router is not None
    assert health.router is not None


def test_import_services():
    """Test all services import."""
    from app.services.accounting_engine import AccountingEngine
    from app.services.business_service import BusinessService
    from app.services.llm_service import LLMService, get_llm_service
    from app.services.tax_service import TunisianTaxService
    from app.services.model_manager import ModelManager
    
    assert AccountingEngine is not None
    assert BusinessService is not None
    assert LLMService is not None
    assert get_llm_service is not None
    assert TunisianTaxService is not None
    assert ModelManager is not None


def test_import_db():
    """Test database modules import."""
    from app.db.mongodb import get_tenant_db, get_platform_db, init_mongodb, close_mongodb
    from app.db.redis import get_redis, init_redis, close_redis
    from app.db.schemas import AccountingTask, AccountingPeriod, AccountingTaskStatus
    
    assert get_tenant_db is not None
    assert get_platform_db is not None
    assert init_mongodb is not None
    assert close_mongodb is not None
    assert get_redis is not None
    assert init_redis is not None
    assert close_redis is not None
    assert AccountingTask is not None
    assert AccountingPeriod is not None
    assert AccountingTaskStatus is not None


def test_import_security():
    """Test security module imports."""
    from app.core.security import secure_endpoint, verify_api_key
    assert secure_endpoint is not None
    assert verify_api_key is not None
