from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import Text, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from common.db_session import Base


class Creators(Base):
    """クリエイター"""

    __tablename__ = "creators"

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_name_kana: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_name_kana: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    birth_date: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    tos_accepted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    platform_fee_percent: Mapped[int] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
