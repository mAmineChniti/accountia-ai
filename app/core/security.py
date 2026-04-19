"""Security middleware for API authentication."""

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# API Key security scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# JWT Bearer security scheme (optional)
jwt_bearer = HTTPBearer(auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    Verify the API key from X-API-Key header.
    Only the Accountia API should have this key.
    """
    if not settings.api_key:
        logger.warning("api_key_not_configured", warning="AI Accountant running without API key protection")
        return "unprotected"
    
    if not api_key:
        logger.warning("api_key_missing")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Access denied.",
        )
    
    if api_key != settings.api_key:
        logger.warning("api_key_invalid", provided_key=api_key[:10] + "...")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key. Access denied.",
        )
    
    logger.debug("api_key_validated")
    return api_key


async def verify_optional_jwt(
    credentials: HTTPAuthorizationCredentials = Security(jwt_bearer)
) -> str | None:
    """
    Optionally verify JWT token if provided.
    Used to extract user/business context from Accountia API.
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    # JWT validation would happen here if needed
    # For now, just pass through - Accountia API validates it
    return token


async def secure_endpoint(
    api_key: str = Depends(verify_api_key),
    jwt_token: str | None = Depends(verify_optional_jwt),
) -> dict:
    """
    Combined security dependency for protected endpoints.
    
    Returns:
        dict with auth context for the endpoint
    """
    return {
        "api_key_valid": True,
        "jwt_token": jwt_token,
        "source": "accountia_api",  # Only Accountia API should have the key
    }
