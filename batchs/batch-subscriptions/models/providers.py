from __future__ import annotations
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from sqlalchemy import SmallInteger, func, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from common.db_session import Base

class Providers(Base):
    """決済プロバイダー"""
    __tablename__ = "providers"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())

    # プロバイダー基本情報
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, comment="プロバイダーコード（例: credix, stripe）")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="表示名（例: Credix, Stripe）")

    # プロバイダー別設定（JSON形式で柔軟に対応）
    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, comment="プロバイダー固有設定（JSON）")

    # ステータス
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1=active, 2=inactive")

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())