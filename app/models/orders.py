from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, BigInteger, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .posts import Posts 
    from .plans import Plans

class Orders(Base):
    """注文（単品や初回サブスク課金など）"""
    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    total_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="JPY")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    user: Mapped["Users"] = relationship("Users", back_populates="orders")
    items: Mapped[list["OrderItems"]] = relationship("OrderItems", back_populates="order")

class OrderItems(Base):
    """注文アイテム（単品や初回サブスク課金など）"""
    __tablename__ = "order_items"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    order_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    item_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    post_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("posts.id"), nullable=True)
    plan_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("plans.id"), nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    creator_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    order: Mapped["Orders"] = relationship("Orders", back_populates="items")
    post: Mapped[Optional["Posts"]] = relationship("Posts")
    plan: Mapped[Optional["Plans"]] = relationship("Plans")
    creator: Mapped["Users"] = relationship("Users")

if TYPE_CHECKING:
    from .user import Users
    from .posts import Posts
    from .plans import Plans
    Users.orders = relationship("Orders", back_populates="user")
