from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, BigInteger, func, CHAR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .orders import Orders

class Payments(Base):
    __tablename__ = "payments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    order_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    provider: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    provider_payment_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    order: Mapped["Orders"] = relationship("Orders")
    events: Mapped[list["PaymentEvents"]] = relationship("PaymentEvents", back_populates="payment")
    refunds: Mapped[list["Refunds"]] = relationship("Refunds", back_populates="payment")

class PaymentEvents(Base):
    __tablename__ = "payment_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    payment_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    event_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    payment: Mapped["Payments"] = relationship("Payments", back_populates="events")

class Refunds(Base):
    __tablename__ = "refunds"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    payment_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    payment: Mapped["Payments"] = relationship("Payments", back_populates="refunds")
