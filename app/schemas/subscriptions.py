from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class SubscriptionAdminInfo(BaseModel):
    id: str
    subscriber_username: str
    creator_username: str
    money: int
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
