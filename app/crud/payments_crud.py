"""
Payments CRUD操作
"""
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.payments import Payments
from datetime import datetime, timezone


def create_payment(
    db: Session,
    transaction_id: UUID,
    payment_type: int,  # 1=subscription, 2=one_time_purchase
    order_id: str,
    order_type: int,  # 1=plan_id, 2=price_id
    provider_id: UUID,
    provider_payment_id: str,
    buyer_user_id: UUID,
    seller_user_id: UUID,
    payment_amount: int,
    payment_price: int,
    status: int = 2,  # 2=succeeded
    platform_fee: int = 0, # プラットフォーム手数料
) -> Payments:
    """決済履歴作成"""
    payment = Payments(
        transaction_id=transaction_id,
        payment_type=payment_type,
        order_id=order_id,
        order_type=order_type,
        provider_id=provider_id,
        provider_payment_id=provider_payment_id,
        buyer_user_id=buyer_user_id,
        seller_user_id=seller_user_id,
        payment_amount=payment_amount,
        payment_price=payment_price,
        status=status,
        paid_at=datetime.now(timezone.utc),
        platform_fee=platform_fee,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def create_free_payment(
    db: Session,
    payment_type: int,  # 1=subscription, 2=one_time_purchase
    order_id: str,
    order_type: int,  # ItemType.PLAN or ItemType.POST
    buyer_user_id: UUID,
    seller_user_id: UUID,
    payment_price: int,  # 0円
    platform_fee: int = 0,
) -> Payments:
    """0円プラン・商品用の決済履歴作成（transaction_id, provider関連はNULL）"""
    payment = Payments(
        transaction_id=None,  # 0円なのでtransaction不要
        payment_type=payment_type,
        order_id=order_id,
        order_type=order_type,
        provider_id=None,  # 0円なのでプロバイダーなし
        provider_payment_id=None,  # 0円なのでプロバイダー決済IDなし
        buyer_user_id=buyer_user_id,
        seller_user_id=seller_user_id,
        payment_amount=0,  # 0円
        payment_price=payment_price,  # 0円
        status=2,  # 2=succeeded (即座に成功)
        paid_at=datetime.now(timezone.utc),
        platform_fee=platform_fee,
    )
    db.add(payment)
    db.flush()
    return payment
