from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, BigInteger, func, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .user_banks import UserBanks
    from .admins import Admins

class Withdraws(Base):
    """出金・振込管理"""
    __tablename__ = "withdraws"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())

    # ユーザー・口座情報
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    user_bank_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user_banks.id"), nullable=False)

    # 出金申請金額
    withdraw_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="出金申請金額（円）")
    transfer_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="実際振込金額（円）")

    # ステータス管理
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, index=True, comment="1=pending, 2=processing, 3=completed, 4=failed, 5=cancelled")

    # 処理日時
    requested_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    processed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="処理開始日時")
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="処理完了日時")

    # エラー情報
    failure_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 管理者承認
    approved_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("admins.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["Users"] = relationship("Users", back_populates="withdraws")
    user_bank: Mapped["UserBanks"] = relationship("UserBanks", back_populates="withdraws")
    approver: Mapped[Optional["Admins"]] = relationship("Admins", back_populates="approved_withdraws")
