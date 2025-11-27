from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, BigInteger, func, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .plans import Plans


class Subscriptions(Base):
    """サブスクリプション"""
    __tablename__ = "subscriptions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    type: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="1=single, 2=plan")
    start_at: Mapped[datetime] = mapped_column(nullable=False , comment="start date of the subscription")
    end_at: Mapped[datetime] = mapped_column(nullable=False , comment="end date of the subscription")
    order_id: Mapped[str] = mapped_column(String(255), nullable=False , comment="plan_id or price_id")
    provider_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False, comment="provider id of the subscription")

    
