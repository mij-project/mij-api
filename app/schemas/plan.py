from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional, List
from datetime import datetime

class PlanCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    price: int = Field(..., gt=0)
    currency: str = Field(default="JPY")
    billing_cycle: int = Field(default=1)

class PlanResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    price: int
    
    class Config:
        from_attributes = True

class SubscribedPlanResponse(BaseModel):
    subscription_id: UUID
    plan_id: UUID
    plan_name: str
    plan_description: Optional[str] = None
    price: int
    current_period_start: datetime
    current_period_end: datetime
    subscription_created_at: datetime
    subscription_updated_at: datetime
    
    class Config:
        from_attributes = True

class PlanListResponse(BaseModel):
    plans: List[PlanResponse] = []

class SubscribedPlanListResponse(BaseModel):
    subscribed_plans: List[SubscribedPlanResponse] = []

class PlanPostResponse(BaseModel):
    id: UUID
    thumbnail_url: Optional[str] = None
    title: str
    creator_avatar: Optional[str] = None
    creator_name: str
    creator_username: str
    likes_count: int
    comments_count: int
    duration: Optional[str] = None
    is_video: bool
    created_at: datetime
    price: Optional[int] = None
    currency: Optional[str] = None

    class Config:
        from_attributes = True

class PlanPostsResponse(BaseModel):
    posts: List[PlanPostResponse] = []

class PlanDetailResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    price: int
    creator_id: UUID
    creator_name: str
    creator_username: str
    creator_avatar_url: Optional[str] = None
    creator_cover_url: Optional[str] = None
    post_count: int
    is_subscribed: bool

    class Config:
        from_attributes = True

class PlanPostsPaginatedResponse(BaseModel):
    posts: List[PlanPostResponse] = []
    total: int
    page: int
    per_page: int
    has_next: bool
