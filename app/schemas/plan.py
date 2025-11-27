from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional, List
from datetime import datetime

class PlanCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    price: int = Field(..., ge=0)
    currency: str = Field(default="JPY")
    billing_cycle: int = Field(default=1)
    type: int = Field(default=1, description="1=通常, 2=おすすめ")
    welcome_message: Optional[str] = Field(None, max_length=1000)
    post_ids: Optional[List[UUID]] = Field(default=[], description="プランに含める投稿IDリスト")

class PlanUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    type: Optional[int] = Field(None, description="1=通常, 2=おすすめ")
    welcome_message: Optional[str] = Field(None, max_length=1000)
    post_ids: Optional[List[UUID]] = Field(None, description="プランに含める投稿IDリスト")

class PlanResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    price: int
    type: int = 1
    display_order: Optional[int] = None
    welcome_message: Optional[str] = None
    post_count: Optional[int] = 0
    subscriber_count: Optional[int] = 0

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
    type: int = 1
    welcome_message: Optional[str] = None

    class Config:
        from_attributes = True

class PlanSubscriberResponse(BaseModel):
    user_id: UUID
    username: str
    profile_name: str
    avatar_url: Optional[str] = None
    subscribed_at: datetime
    current_period_end: datetime

    class Config:
        from_attributes = True

class PlanSubscriberListResponse(BaseModel):
    subscribers: List[PlanSubscriberResponse] = []
    total: int
    page: int
    per_page: int
    has_next: bool

class PlanOrderItem(BaseModel):
    plan_id: str = Field(..., description="プランID")
    display_order: int = Field(..., description="表示順")

class PlanReorderRequest(BaseModel):
    plan_orders: List[PlanOrderItem] = Field(..., description="プランの並び順リスト")

class PlanPostsPaginatedResponse(BaseModel):
    posts: List[PlanPostResponse] = []
    total: int
    page: int
    per_page: int
    has_next: bool

class CreatorPost(BaseModel):
    id: UUID
    thumbnail_url: Optional[str] = None
    title: str
    duration: Optional[str] = None
    is_video: bool
    created_at: datetime
    is_included: bool

    class Config:
        from_attributes = True

class CreatorPostsForPlanResponse(BaseModel):
    posts: List[CreatorPost] = []
