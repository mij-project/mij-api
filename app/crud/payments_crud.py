"""
Payments CRUD操作
"""
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.payments import Payments
from datetime import datetime


async def create_payment(
    db: AsyncSession,
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
        paid_at=datetime.utcnow()
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment
