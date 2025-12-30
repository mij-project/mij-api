from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import List, Optional

class PriceTimeSaleResponse(BaseModel):
    id: str
    post_id: str
    plan_id: Optional[UUID] = None
    price_id: Optional[UUID] = None
    start_date: datetime
    end_date: datetime
    sale_percentage: int
    max_purchase_count: Optional[int] = None
    purchase_count: int
    is_active: bool
    is_expired: bool
    created_at: datetime

class PaginatedPriceTimeSaleResponse(BaseModel):
    time_sales: List[PriceTimeSaleResponse]
    total: int
    total_pages: int
    page: int
    limit: int
    has_next: bool

class PriceTimeSaleCreateRequest(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    sale_percentage: int = Field(..., ge=0, le=100)
    max_purchase_count: Optional[int] = None

class UpdateRequest(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    sale_percentage: Optional[int] = None
    max_purchase_count: Optional[int] = None