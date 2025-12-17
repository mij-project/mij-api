from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import func, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.db_session import Base

class UserProviders(Base):
    """ユーザーと決済プロバイダーの紐づけ"""
    __tablename__ = "user_providers"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    provider_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    # CredixカードID
    sendid: Mapped[Optional[str]] = mapped_column(String(25), nullable=True, index=True, comment="CredixカードID（リピーター決済用）")

    cardbrand: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, comment="カードブランド")
    cardnumber: Mapped[Optional[str]] = mapped_column(String(4), nullable=True, comment="カード番号")
    yuko: Mapped[Optional[str]] = mapped_column(String(4), nullable=True, comment="有効期限")

    # カード情報の有効性
    is_valid: Mapped[bool] = mapped_column(nullable=False, default=True, comment="カード情報が有効か")

    # 最終利用日時
    last_used_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="最終決済日時")

    # メインカード
    is_main_card: Mapped[bool] = mapped_column(nullable=False, default=False, comment="メインカードかどうか")
    
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())