from __future__ import annotations
from typing import Optional, TYPE_CHECKING, List
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, func, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .payments import Payments
    from .providers import Providers

class PaymentTransactions(Base):
    """決済トランザクション"""
    __tablename__ = "payment_transactions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    type: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="1=single, 2=plan")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1=pending, 2=completed, 3=failed")
    provider_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)
    order_id: Mapped[str] = mapped_column(String(255), nullable=False , comment="plan_id or price_id")
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, comment="credixから発行されたセッションID")
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    # Relationships
    user: Mapped["Users"] = relationship("Users", foreign_keys=[user_id], back_populates="user_transactions")
    provider: Mapped["Providers"] = relationship("Providers", back_populates="payment_transactions")
    payment: Mapped[List["Payments"]] = relationship("Payments", back_populates="transaction")