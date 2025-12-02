"""
Subscriptions CRUD操作
"""
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.subscriptions import Subscriptions
from datetime import datetime
from typing import Optional


def create_subscription(
    db: Session,
    access_type: int,  # 1=plan_subscription, 2=one_time_purchase
    user_id: UUID,
    creator_id: UUID,
    order_id: str,
    order_type: int,  # 1=plan_id, 2=price_id
    access_start: datetime,
    access_end: Optional[datetime],
    next_billing_date: Optional[datetime],
    provider_id: UUID,
    payment_id: UUID,
    status: int = 1,  # 1=active
) -> Subscriptions:
    """サブスクリプション作成"""
    subscription = Subscriptions(
        access_type=access_type,
        user_id=user_id,
        creator_id=creator_id,
        order_id=order_id,
        order_type=order_type,
        access_start=access_start,
        access_end=access_end,
        next_billing_date=next_billing_date,
        provider_id=provider_id,
        payment_id=payment_id,
        status=status,
        cancel_at_period_end=False,
        failed_payment_count=0
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription
