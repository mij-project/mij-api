from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import Text, SmallInteger, UniqueConstraint, func, Float
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.db_session import Base

class Follows(Base):
    """フォロー"""
    __tablename__ = "follows"

    follower_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    creator_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

class Likes(Base):
    """いいね"""
    __tablename__ = "likes"

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

class Comments(Base):
    """コメント"""
    __tablename__ = "comments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    parent_comment_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

class Bookmarks(Base):
    """ブックマーク"""
    __tablename__ = "bookmarks"

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

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

class UserRecommendations(Base):
    """ユーザー推薦"""
    __tablename__ = "user_recommendations"
    __table_args__ = (
        UniqueConstraint("user_id", "type", name="uq_user_recommendations_user_type"),
    )
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    type: Mapped[int] = mapped_column(SmallInteger, nullable=False) # 1: creators 2: categories
    payload: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())