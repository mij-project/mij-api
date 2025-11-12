from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, func, PrimaryKeyConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy import Index
from app.db.base import Base
from typing import List

if TYPE_CHECKING:
    from .user import Users

class Events(Base):
    __tablename__ = "events"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    start_date: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    user_events: Mapped[List["UserEvents"]] = relationship("UserEvents", back_populates="event")

    indexes = [
        Index("idx_events_code", id, code, unique=True),
    ]

class UserEvents(Base):
    __tablename__ = "user_events"

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "event_id", name="pk_user_events"),
    )

    user: Mapped["Users"] = relationship("Users", back_populates="user_events")
    event: Mapped["Events"] = relationship("Events", back_populates="user_events")