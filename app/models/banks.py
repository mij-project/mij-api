from __future__ import annotations
from typing import Optional, List, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import func, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user_banks import UserBanks

class Banks(Base):
    """銀行マスタ"""
    __tablename__ = "banks"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())

    bank_code: Mapped[str] = mapped_column(String(4), nullable=False, index=True, comment="銀行コード（4桁）")
    bank_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="銀行名")
    bank_name_kana: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="銀行名カナ")

    branch_code: Mapped[str] = mapped_column(String(3), nullable=False, comment="支店コード（3桁）")
    branch_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="支店名")
    branch_name_kana: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="支店名カナ")

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    user_banks: Mapped[List["UserBanks"]] = relationship("UserBanks", back_populates="bank")
