from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from uuid import UUID


class SubscriptionAdminInfo(BaseModel):
    id: str
    subscriber_username: str
    creator_username: str
    money: Optional[int] = None
    payment_amount: Optional[int] = None
    access_start: datetime
    access_end: Optional[datetime] = None
    status: int
    canceled_at: Optional[datetime] = None
    next_billing_date: Optional[datetime] = None
    last_payment_failed_at: Optional[datetime] = None


class SubscriptionAdminInfoResponse(BaseModel):
    subscriptions: List[SubscriptionAdminInfo] = Field(default_factory=list)
    total_items: int
    page: int
    limit: int
    total_pages: int


class FreeSubscriptionRequest(BaseModel):
    """0円プラン・商品加入リクエスト"""
    purchase_type: int  # 1=SINGLE, 2=SUBSCRIPTION
    order_id: str  # プランIDまたはpriceID(post_id)


class FreeSubscriptionResponse(BaseModel):
    """0円プラン・商品加入レスポンス"""
    result: bool
    subscription_id: UUID
    message: str
