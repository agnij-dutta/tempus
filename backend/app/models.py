from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class CreatePreviewRequest(BaseModel):
    """
    Request model for creating a preview environment.
    
    Attributes:
        ttl_hours: Time to live in hours. The preview environment will automatically
                   be destroyed after this duration. Must be between 1 and 24 hours.
    """
    ttl_hours: int = Field(
        default=2,
        ge=1,
        le=24,
        description="Time to live in hours (1-24)",
        example=2
    )


class PreviewResponse(BaseModel):
    """
    Response model for preview creation.
    
    Attributes:
        preview_id: Unique identifier for the preview environment (UUID)
        preview_url: Public URL to access the preview environment
        expires_at: ISO 8601 timestamp when the preview will be automatically destroyed
    """
    preview_id: str = Field(description="Unique preview identifier", example="550e8400-e29b-41d4-a716-446655440000")
    preview_url: str = Field(description="Public URL to access the preview", example="http://alb-123456789.us-east-1.elb.amazonaws.com/preview-550e8400")
    expires_at: str = Field(description="ISO 8601 timestamp of expiration", example="2024-01-01T14:00:00Z")


class PreviewMetadata(BaseModel):
    """Model for storing preview metadata in DynamoDB."""
    preview_id: str
    service_arn: str
    target_group_arn: str
    expires_at: str
    created_at: str
    eventbridge_rule_name: Optional[str] = None


class PreviewStatus(BaseModel):
    """Status summary for a preview environment."""
    preview_id: str
    status: str
    preview_url: str
    expires_at: str
    created_at: str
    service_status: Optional[str] = None
    target_group_health: Optional[str] = None


class PreviewStatusDetail(BaseModel):
    """Detailed status with health information."""
    preview_id: str
    status: str
    preview_url: str
    expires_at: str
    created_at: str
    service_status: Optional[str] = None
    desired_count: Optional[int] = None
    running_count: Optional[int] = None
    pending_count: Optional[int] = None
    target_group_health: Optional[str] = None
    target_health_descriptions: Optional[list] = None


class PreviewListResponse(BaseModel):
    """Paginated list of previews."""
    items: list[PreviewStatus]
    total: int


class ExtendPreviewRequest(BaseModel):
    """Request to extend preview TTL."""
    additional_hours: int = Field(
        default=1,
        ge=1,
        le=24,
        description="Number of hours to extend the preview TTL (1-24)"
    )

