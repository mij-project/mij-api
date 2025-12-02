"""
Payment Transactions CRUD操作
"""
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.payment_transactions import PaymentTransactions
from datetime import datetime


async def create_payment_transaction(
    db: Session,
    user_id: UUID,  
    provider_id: UUID,
    transaction_type: int,  # 1=single, 2=plan
    session_id: str,
    order_id: str,
) -> PaymentTransactions:
    """決済トランザクション作成"""
    transaction = PaymentTransactions(
        user_id=user_id,
        provider_id=provider_id,
        type=transaction_type,
        session_id=session_id,
        order_id=order_id,
        status=1,  # 1=pending
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


async def get_transaction_by_session_id(
    db: Session,
    session_id: str
) -> PaymentTransactions | None:
    """セッションIDでトランザクション取得"""
    result = db.query(PaymentTransactions).filter(PaymentTransactions.session_id == session_id).first()
    return result


async def get_transaction_by_id(
    db: Session,
    transaction_id: UUID
) -> PaymentTransactions | None:
    """トランザクションID取得"""
    result = db.query(PaymentTransactions).filter(PaymentTransactions.id == transaction_id).first()
    return result


async def update_transaction_status(
    db: Session,
    transaction_id: UUID,
    status: int,  # 1=pending, 2=completed, 3=failed
) -> PaymentTransactions:
    """トランザクションステータス更新"""
    transaction = db.query(PaymentTransactions).filter(PaymentTransactions.id == transaction_id).first()
    transaction.status = status
    transaction.updated_at = datetime()
    db.commit()
    db.refresh(transaction)
    return transaction
