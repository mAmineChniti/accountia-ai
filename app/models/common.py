from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    code: int = Field(..., description="HTTP status code")
    message: str = Field(..., description="Short description of the error")
    details: dict[str, Any] | None = Field(None, description="Optional additional error details")
    occurred_at: datetime = Field(..., alias="occurredAt", description="Timestamp when the error occurred")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "code": 404,
                "message": "Resource not found",
                "details": {"resource": "tax_results", "businessId": "biz_001"},
                "occurredAt": "2024-05-01T12:00:00Z",
            }
        },
    }
