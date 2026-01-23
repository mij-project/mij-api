from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, func, Float
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .posts import Posts

class Follows(Base):
    """フォロー"""
    __tablename__ = "follows"

    follower_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    creator_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    follower: Mapped["Users"] = relationship("Users", foreign_keys=[follower_user_id])
    creator: Mapped["Users"] = relationship("Users", foreign_keys=[creator_user_id])

class Likes(Base):
    """いいね"""
    __tablename__ = "likes"

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("posts.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    user: Mapped["Users"] = relationship("Users")
    post: Mapped["Posts"] = relationship("Posts")

class Comments(Base):
    """コメント"""
    __tablename__ = "comments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("posts.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    parent_comment_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("comments.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    post: Mapped["Posts"] = relationship("Posts")
    user: Mapped["Users"] = relationship("Users")
    parent_comment: Mapped[Optional["Comments"]] = relationship("Comments", remote_side=[id])
    replies: Mapped[list["Comments"]] = relationship("Comments", back_populates="parent_comment")

class Bookmarks(Base):
    """ブックマーク"""
    __tablename__ = "bookmarks"

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("posts.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    user: Mapped["Users"] = relationship("Users")
    post: Mapped["Posts"] = relationship("Posts")

class ProfileViewsTracking(Base):
    """プロフィール閲覧履歴"""
    __tablename__ = "profile_views_tracking"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    viewer_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    profile_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

class PostViewsTracking(Base):
    """投稿閲覧履歴"""
    __tablename__ = "post_views_tracking"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    viewer_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    watched_duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    video_duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

class PostPurchasesTracking(Base):
    """投稿購入履歴"""
    __tablename__ = "post_purchases_tracking"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())