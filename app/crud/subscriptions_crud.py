"""
Subscriptions CRUD操作
"""
from uuid import UUID

from sqlalchemy.orm import Session
from app.models.subscriptions import Subscriptions
from datetime import datetime
from typing import Optional
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy import cast
from app.models.prices import Prices
from app.models.plans import Plans, PostPlans
from datetime import datetime, timezone
from app.constants.enums import SubscriptionStatus, SubscriptionType, PaymentTransactionType


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

def create_expired_subscription(    
    db: Session,
    user_id: UUID,
    creator_id: UUID,
    order_id: str,
    order_type: int,
) -> Subscriptions:

    subscription = Subscriptions(
        access_type=SubscriptionType.PLAN,
        user_id=user_id,
        creator_id=creator_id,
        order_id=order_id,
        order_type=order_type,
        status=SubscriptionStatus.EXPIRED,
        cancel_at_period_end=True,
        failed_payment_count=1,
        last_payment_failed_at=datetime.now(timezone.utc),
        next_billing_date=None,
        canceled_at=datetime.now(timezone.utc),
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


def cancel_subscription(db: Session, plan_id: str, user_id: UUID):
    """
    サブスクリプションをキャンセル
    
    Note: order_typeの値について
    - payment.pyの_create_subscription_recordでは order_type=transaction.type を使用
    - PaymentTransactionType.SUBSCRIPTION = 2 がプラン購読
    - したがって、プラン購読の場合は order_type=2 となる
    """
    subscription = (
        db.query(Subscriptions)
        .filter(
            Subscriptions.order_id == plan_id,
            Subscriptions.order_type == PaymentTransactionType.SUBSCRIPTION,  # 2 = プラン購読
            Subscriptions.user_id == user_id,
            Subscriptions.status == SubscriptionStatus.ACTIVE,
            Subscriptions.canceled_at.is_(None)  # まだキャンセルされていない
        )
        .first()
    )
    if not subscription:
        # デバッグ用: 該当するサブスクリプションが存在するか確認
        all_subscriptions = (
            db.query(Subscriptions)
            .filter(
                Subscriptions.order_id == plan_id,
                Subscriptions.user_id == user_id
            )
            .all()
        )
        if not all_subscriptions:
            raise HTTPException(
                status_code=404, 
                detail=f"Subscription not found for plan_id={plan_id}, user_id={user_id}"
            )
        else:
            # サブスクリプションは存在するが、条件に一致しない
            details = [f"order_type={s.order_type}, status={s.status}, canceled_at={s.canceled_at}" 
                      for s in all_subscriptions]
            raise HTTPException(
                status_code=404,
                detail=f"Active subscription not found. Found subscriptions: {details}"
            )
    subscription.status = SubscriptionStatus.CANCELED
    subscription.canceled_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(subscription)
    return subscription


def get_subscription_by_order_id(db: Session, order_id: str):
    return (
        db.query(Subscriptions)
        .filter(
            Subscriptions.order_id == order_id,
            Subscriptions.order_type == PaymentTransactionType.SUBSCRIPTION,
            Subscriptions.status == SubscriptionStatus.ACTIVE,
            Subscriptions.canceled_at.is_(None)
        )
        .all()
    )


def update_subscription_status(db: Session, subscription_id: UUID, status: int):
    subscription = db.query(Subscriptions).filter(Subscriptions.id == subscription_id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail=f"Subscription not found: {subscription_id}")
    subscription.status = status
    db.commit()
    db.refresh(subscription)
    return subscription


def create_free_subscription(
    db: Session,
    access_type: int,  # 1=plan_subscription, 2=one_time_purchase
    user_id: UUID,
    creator_id: UUID,
    order_id: str,
    order_type: int,  # ItemType.PLAN or ItemType.POST
    payment_id: UUID,
) -> Subscriptions:
    """0円プラン・商品用のサブスクリプション作成（無期限）"""
    subscription = Subscriptions(
        access_type=access_type,
        user_id=user_id,
        creator_id=creator_id,
        order_id=order_id,
        order_type=order_type,
        access_start=datetime.now(timezone.utc),
        access_end=None,  # 無期限
        next_billing_date=None,  # 無期限なので課金なし
        provider_id=None,  # 0円なのでプロバイダーなし
        payment_id=payment_id,
        status=SubscriptionStatus.ACTIVE,
        cancel_at_period_end=False,
        failed_payment_count=0
    )
    db.add(subscription)
    db.flush()
    return subscription

def get_subscription_by_user_id(db: Session, user_id: UUID, partner_user_id: UUID):
    """
    ユーザーのDM解放プラン加入の有無を取得
    """
    has_dm_plan = db.query(Subscriptions).join(
        Plans,
        (Subscriptions.order_type == PaymentTransactionType.SUBSCRIPTION) & (cast(Subscriptions.order_id, PG_UUID) == Plans.id)
    ).filter(
        Subscriptions.user_id == user_id,
        Subscriptions.creator_id == partner_user_id,
        Plans.open_dm_flg == True,
        Subscriptions.status == SubscriptionStatus.ACTIVE
    ).first() is not None

    return has_dm_plan