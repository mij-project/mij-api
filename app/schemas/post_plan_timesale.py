from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import List, Optional, Any

class PlanTimeSaleResponse(BaseModel):
    id: str
    post_id: Optional[str] = None  # UUIDを文字列として扱う
    plan_id: Optional[str] = None  # 価格タイムセールの場合はNoneになる可能性がある
    price_id: Optional[str] = None  # UUIDを文字列として扱う
    start_date: datetime
    end_date: datetime
    sale_percentage: int
    max_purchase_count: Optional[int] = None
    purchase_count: int
    is_active: bool
    is_expired: bool
    created_at: datetime

class PaginatedPlanTimeSaleResponse(BaseModel):
    time_sales: List[PlanTimeSaleResponse]
    total: int
    total_pages: int
    page: int
    limit: int
    has_next: bool

class PlanTimeSaleCreateRequest(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    sale_percentage: int = Field(..., ge=0, le=100)
    max_purchase_count: Optional[int] = None

class PlanTimeSaleEditInitResponse(BaseModel):
    """プランのタイムセール編集初期化用レスポンス"""
    plan: Any  # PlanDetailResponse
    time_sale: Optional[PlanTimeSaleResponse] = None

class UpdateRequest(BaseModel):
    start_date: datetime
    end_date: datetime
    sale_percentage: int
    max_purchase_count: Optional[int] = None