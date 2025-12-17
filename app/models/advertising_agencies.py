from __future__ import annotations
from typing import Optional, TYPE_CHECKING, List
from uuid import UUID
from datetime import datetime

from sqlalchemy import Text, SmallInteger, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users


class AdvertisingAgencies(Base):
    """広告会社マスター"""
    __tablename__ = "advertising_agencies"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(Text, nullable=False)  # 広告会社名
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # 一意の識別コード
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)  # 1=有効, 2=停止
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # リレーション
    user_referrals: Mapped[List["UserReferrals"]] = relationship("UserReferrals", back_populates="agency")


class UserReferrals(Base):
    """ユーザーリファラル追跡"""
    __tablename__ = "user_referrals"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    agency_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("advertising_agencies.id", ondelete="CASCADE"), nullable=False)
    referral_code: Mapped[str] = mapped_column(Text, nullable=False)  # 使用されたリファラルコード
    registration_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 登録元 (web, mobile, etc.)
    ip_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 登録時のIPアドレス
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # ブラウザ情報
    landing_page: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 最初にアクセスしたページURL
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    # リレーション
    user: Mapped["Users"] = relationship("Users", back_populates="user_referrals")
    agency: Mapped["AdvertisingAgencies"] = relationship("AdvertisingAgencies", back_populates="user_referrals")


class AgencyAccessLogs(Base):
    """広告会社アクセスログ"""
    __tablename__ = "agency_access_logs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    agency_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("advertising_agencies.id", ondelete="CASCADE"), nullable=False)
    referral_code: Mapped[str] = mapped_column(Text, nullable=False)  # 使用されたリファラルコード
    ip_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # アクセス元IPアドレス
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # ブラウザ情報
    landing_page: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # アクセスしたページURL
    session_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # セッションID（重複カウント防止用）
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    # リレーション
    agency: Mapped["AdvertisingAgencies"] = relationship("AdvertisingAgencies")
