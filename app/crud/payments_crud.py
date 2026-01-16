"""
Payments CRUD操作
"""
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.payments import Payments
from datetime import datetime, timezone
from app.models.providers import Providers
from app.constants.enums import PaymentType, PaymentStatus
from typing import List, Optional, Tuple
from sqlalchemy import func

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
    paid_at: Optional[datetime] = datetime.now(timezone.utc),  # Noneの場合は設定しない
) -> Payments:
    """決済履歴作成"""
    payment_data = {
        "transaction_id": transaction_id,
        "payment_type": payment_type,
        "order_id": order_id,
        "order_type": order_type,
        "provider_id": provider_id,
        "provider_payment_id": provider_payment_id,
        "buyer_user_id": buyer_user_id,
        "seller_user_id": seller_user_id,
        "payment_amount": payment_amount,
        "payment_price": payment_price,
        "status": status,
        "platform_fee": platform_fee,
    }
    
    # paid_atがNoneでない場合のみ設定
    if paid_at is not None:
        payment_data["paid_at"] = paid_at
    
    payment = Payments(**payment_data)
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

def get_payment_by_user_id(
    db: Session,
    user_id: UUID,
    partner_user_id: UUID,
    payment_type: int,
) -> Payments:
    """
    ユーザーの決済履歴を取得
    """
    has_chip_history = db.query(Payments).filter(
        Payments.payment_type == PaymentType.CHIP,
        Payments.status == PaymentStatus.SUCCEEDED,
        (
            (Payments.buyer_user_id == user_id) & (Payments.seller_user_id == partner_user_id)
        ) | (
            (Payments.buyer_user_id == partner_user_id) & (Payments.seller_user_id == user_id)
        )
    ).first() is not None
    return has_chip_history

def get_top_buyers_by_user_id(
    db: Session,
    user_id: UUID,
) -> List[Payments]:
    """
    ユーザーの購入金額上位3名を取得
    3件ない場合は空配列を返す
    """
    top_buyers_query = (
        db.query(
            Payments.buyer_user_id,
            func.sum(Payments.payment_amount).label("total_amount")
        )
        .filter(
            Payments.seller_user_id == user_id,
            Payments.status == PaymentStatus.SUCCEEDED
        )
        .group_by(Payments.buyer_user_id)
        .order_by(func.sum(Payments.payment_amount).desc())
        .limit(3)
    )
    top_buyers_results = top_buyers_query.all()
    # 3件ない場合は空配列を返す
    if len(top_buyers_results) < 3:
        return []
    return top_buyers_results

def update_payment_status_by_transaction_id(
    db: Session,
    transaction_id: UUID,
    status: int,
    payment_amount: int,
    payment_price: int,
    paid_at: datetime,
) -> Payments:
    """
    Update payment status
    """
    payment = db.query(Payments).filter(Payments.transaction_id == transaction_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    payment.status = status
    payment.payment_amount = payment_amount
    payment.payment_price = payment_price
    payment.paid_at = paid_at
    db.commit()
    db.refresh(payment)
    return payment

def get_payment_by_session_id(
    db: Session,
    transaction_id: UUID,
) -> Payments:
    """
    Get payment by session id
    """
    return db.query(Payments).filter(Payments.transaction_id == transaction_id).first()

def get_payment_status_by_price_id(
    db: Session,
    price_id: str,
) -> Optional[Payments]:
    """
    Get payment status by price id
    """
    return (
        db.query(Payments)
        .filter(Payments.order_id == price_id)
        .filter(Payments.payment_type == PaymentType.SINGLE)
        .filter(Payments.status == PaymentStatus.PENDING)
        .first()
    )

def get_payment_by_transaction_id(
    db: Session,
    transaction_id: UUID,
) -> Optional[Payments]:
    """
    Get payment by transaction id
    """
    return (
        db.query(Payments)
        .filter(Payments.transaction_id == transaction_id)
        .filter(Payments.payment_type == PaymentType.PLAN)
        .order_by(Payments.paid_at.desc())
        .first()
    )

def get_payment_by_id(
    db: Session,
    payment_id: UUID,
) -> Tuple[Payments, str]:
    """
    Get payment by id
    """
    return (
        db.query(
            Payments,
            Providers.code.label("provider_code"),
        )
        .join(Providers, Providers.id == Payments.provider_id)
        .filter(Payments.id == payment_id)
        .first()
    )