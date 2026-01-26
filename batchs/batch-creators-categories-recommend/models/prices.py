from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import BigInteger, SmallInteger, func, CHAR, Boolean
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.db_session import Base

class Prices(Base):
    __tablename__ = "prices"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    ends_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
