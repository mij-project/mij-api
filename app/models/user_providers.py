from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, func, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .providers import Providers

class UserProviders(Base):
    """ユーザーと決済プロバイダーの紐づけ"""
    __tablename__ = "user_providers"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    provider_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)

    # CredixカードID
    sendid: Mapped[Optional[str]] = mapped_column(String(25), nullable=True, index=True, comment="CredixカードID（リピーター決済用）")

    cardbrand: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, comment="カードブランド")
    cardnumber: Mapped[Optional[str]] = mapped_column(String(4), nullable=True, comment="カード番号")
    yuko: Mapped[Optional[str]] = mapped_column(String(4), nullable=True, comment="有効期限")

    # カード情報の有効性
    is_valid: Mapped[bool] = mapped_column(nullable=False, default=True, comment="カード情報が有効か")

    # 最終利用日時
    last_used_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="最終決済日時")

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["Users"] = relationship("Users", back_populates="user_providers")
    provider: Mapped["Providers"] = relationship("Providers", back_populates="user_providers")
