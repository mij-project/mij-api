"""
Subscriptions CRUD操作
"""
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.subscriptions import Subscriptions
from datetime import datetime
from typing import Optional
from sqlalchemy import or_

from app.models.prices import Prices
from app.models.plans import Plans, PostPlans
from datetime import datetime, timezone


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


def check_viewing_rights(db: Session, post_id: str, user_id: str | None) -> bool:
    """
    ユーザーが投稿の視聴権限を持っているかチェック

    subscriptionsテーブルで有効な権限があるかを確認:
    - status=1 (active)
    - access_end が NULL または 現在日時より後
    - order_id が当該投稿のprice_idまたは投稿が属するplanのいずれかに合致
    """
    if not user_id:
        return False

    now = datetime.now(timezone.utc)

    # 投稿のpriceを取得
    price = db.query(Prices).filter(Prices.post_id == post_id).first()

    # 投稿が属するplanを取得
    plan_ids = db.query(PostPlans.plan_id).filter(PostPlans.post_id == post_id).all()
    # plan_idsが空でも許容する
    plan_id_list = [str(plan.plan_id) for plan in plan_ids] if plan_ids else []

    # order_idのリスト（price_id + plan_ids）
    valid_order_ids = []
    if price:
        valid_order_ids.append(str(price.id))
    if plan_id_list:
        valid_order_ids.extend(plan_id_list)

    if not valid_order_ids:
        return False

    # 有効なsubscriptionが存在するかチェック
    subscription = (
        db.query(Subscriptions)
        .filter(
            Subscriptions.user_id == user_id,
            Subscriptions.status == 1,  # active
            Subscriptions.order_id.in_(valid_order_ids),
            or_(
                Subscriptions.access_end.is_(None),
                Subscriptions.access_end > now
            )
        )
        .first()
    )

    return subscription is not None