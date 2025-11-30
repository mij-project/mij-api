from __future__ import annotations
from typing import Optional, TYPE_CHECKING, List
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, BigInteger, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .identity import IdentityVerifications
    from .conversation_messages import ConversationMessages
    from .user_banks import UserBanks
    from .withdraws import Withdraws
class Admins(Base):
    """管理者"""
    __tablename__ = "admins"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    identity_verifications: Mapped[List["IdentityVerifications"]] = relationship("IdentityVerifications", back_populates="approver")
    conversations: Mapped[List["ConversationMessages"]] = relationship("ConversationMessages", back_populates="sender_admin", foreign_keys="ConversationMessages.sender_admin_id")

    # 決済システム関連
    verified_user_banks: Mapped[List["UserBanks"]] = relationship("UserBanks", back_populates="verifier")
    approved_withdraws: Mapped[List["Withdraws"]] = relationship("Withdraws", back_populates="approver")