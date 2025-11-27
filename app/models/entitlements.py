from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, func, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .posts import Posts
    from .subscriptions import Subscriptions
    from .orders import OrderItems

class Entitlements(Base):
    """視聴権利 (ユーザーと投稿の多対多)"""
    __tablename__ = "entitlements"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    post_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("posts.id"), nullable=True)
    creator_user_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    ends_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    granted_by_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    granted_by_subscription_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True)
    granted_by_order_item_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("order_items.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    user: Mapped["Users"] = relationship("Users", foreign_keys=[user_id])
    post: Mapped[Optional["Posts"]] = relationship("Posts")
    creator: Mapped[Optional["Users"]] = relationship("Users", foreign_keys=[creator_user_id])
    granted_by_subscription: Mapped[Optional["Subscriptions"]] = relationship("Subscriptions")
    granted_by_order_item: Mapped[Optional["OrderItems"]] = relationship("OrderItems")

    __table_args__ = (
        Index('idx_entitlements_user_scope', 'user_id', 'scope', 'creator_user_id', 'ends_at'),
    )
