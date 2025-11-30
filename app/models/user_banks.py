from __future__ import annotations
from typing import Optional, List, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, func, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .banks import Banks
    from .withdraws import Withdraws
    from .admins import Admins

class UserBanks(Base):
    """ユーザー銀行口座情報"""
    __tablename__ = "user_banks"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    bank_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("banks.id"), nullable=False)

    # 口座情報（本番環境では暗号化推奨）
    account_type: Mapped[int] = mapped_column(SmallInteger, nullable=False,
                                              comment="1=普通, 2=当座, 3=貯蓄")
    account_number: Mapped[str] = mapped_column(String(20), nullable=False,
                                                comment="口座番号（暗号化推奨）")
    account_holder_name: Mapped[str] = mapped_column(String(255), nullable=False,
                                                      comment="口座名義人")
    account_holder_name_kana: Mapped[Optional[str]] = mapped_column(String(255), nullable=True,
                                                                      comment="口座名義人カナ")

    # デフォルト口座設定
    is_default: Mapped[bool] = mapped_column(nullable=False, default=False,
                                             comment="デフォルト振込先口座か")

    # 確認ステータス
    verification_status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1,
                                                      comment="1=unverified, 2=verified, 3=rejected")
    verified_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    verified_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True),
                                                         ForeignKey("admins.id"),
                                                         nullable=True,
                                                         comment="承認した管理者")

    # 論理削除
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["Users"] = relationship("Users", back_populates="user_banks")
    bank: Mapped["Banks"] = relationship("Banks", back_populates="user_banks")
    withdraws: Mapped[List["Withdraws"]] = relationship("Withdraws", back_populates="user_bank")
    verifier: Mapped[Optional["Admins"]] = relationship("Admins", back_populates="verified_user_banks")
