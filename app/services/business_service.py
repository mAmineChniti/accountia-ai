"""Business lookup service - gets databaseName from platform DB."""

from typing import Optional

import structlog
from bson import ObjectId

from app.db.mongodb import get_platform_db
from app.db.redis import cache_get, cache_set

logger = structlog.get_logger()

# Cache key prefix
CACHE_PREFIX = "business"


class BusinessService:
    """Service for looking up business information from platform DB."""
    
    @staticmethod
    async def get_database_name(business_id: str) -> str:
        """
        Look up databaseName for a business from the platform businesses collection.
        Uses Redis cache for performance.
        
        Args:
            business_id: The business ID (MongoDB ObjectId as string)
            
        Returns:
            databaseName for the tenant database
            
        Raises:
            ValueError: If business not found or no databaseName
        """
        cache_key = f"{CACHE_PREFIX}:db_name:{business_id}"
        
        # Try cache first
        cached = await cache_get(cache_key)
        if cached:
            logger.debug("business_cache_hit", business_id=business_id)
            return cached
        
        # Fetch from MongoDB
        platform_db = get_platform_db()
        
        # Try both ObjectId and string lookup
        business = None
        try:
            business = await platform_db["businesses"].find_one({
                "_id": ObjectId(business_id)
            })
        except Exception as e:
            logger.debug("business_objectid_lookup_failed", business_id=business_id, error=str(e))
        
        if not business:
            # Try string lookup
            business = await platform_db["businesses"].find_one({
                "_id": business_id
            })
        
        if not business:
            logger.error("business_not_found", business_id=business_id)
            raise ValueError(f"Business not found: {business_id}")
        
        database_name = business.get("databaseName")
        if not database_name:
            logger.error("business_no_database", business_id=business_id)
            raise ValueError(f"Business {business_id} has no databaseName configured")
        
        # Cache the result (1 hour TTL)
        await cache_set(cache_key, database_name, expire=3600)
        
        logger.debug(
            "business_lookup_success",
            business_id=business_id,
            database_name=database_name,
            cached=True,
        )
        
        return database_name
    
    @staticmethod
    async def get_business_info(business_id: str) -> dict:
        """
        Get full business information from platform DB.
        
        Returns:
            Business document with name, email, databaseName, etc.
        """
        platform_db = get_platform_db()
        
        business = None
        try:
            business = await platform_db["businesses"].find_one({
                "_id": ObjectId(business_id)
            })
        except Exception as e:
            logger.debug("business_objectid_lookup_failed", business_id=business_id, error=str(e))
        
        if not business:
            business = await platform_db["businesses"].find_one({
                "_id": business_id
            })
        
        if not business:
            raise ValueError(f"Business not found: {business_id}")
        
        # Convert ObjectId to string for JSON serialization
        business["_id"] = str(business["_id"])
        if "createdAt" in business:
            business["createdAt"] = business["createdAt"].isoformat()
        if "updatedAt" in business:
            business["updatedAt"] = business["updatedAt"].isoformat()
        
        return business
    
    @staticmethod
    async def list_businesses(
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list:
        """List all businesses (for admin/training purposes)."""
        platform_db = get_platform_db()
        
        query = {}
        if status:
            query["status"] = status
        
        cursor = platform_db["businesses"].find(query).limit(limit)
        businesses = await cursor.to_list(length=limit)
        
        for b in businesses:
            b["_id"] = str(b["_id"])
        
        return businesses
