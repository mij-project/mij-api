from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, func, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users

class BankRequestHistories(Base):
    """銀行口座取得APIリクエスト履歴"""
    __tablename__ = "bank_request_histories"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())

    # リクエスト者
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True, comment="APIリクエストを実行したユーザー")

    # リクエスト種別
    request_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="1=bank_search(銀行検索), 2=branch_search(支店検索), 3=account_verify(口座確認)")

    # リクエスト内容
    bank_code: Mapped[Optional[str]] = mapped_column(String(4), nullable=True, comment="銀行コード（検索時）")
    branch_code: Mapped[Optional[str]] = mapped_column(String(3), nullable=True, comment="支店コード（検索時）")
    account_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="口座番号（確認時）")

    # APIレスポンス
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, index=True, comment="1=pending, 2=success, 3=failed, 4=rate_limited")

    response_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="APIレスポンスコード")
    response_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="APIレスポンスメッセージ")
    response_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, comment="APIレスポンスの生データ（JSON）")

    # API制限管理
    api_quota_remaining: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True, comment="API残回数（レスポンスヘッダーから取得）")
    api_quota_reset_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="API制限リセット日時")

    # リクエスト日時
    requested_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), index=True, comment="APIリクエスト日時")

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["Users"] = relationship("Users", back_populates="bank_request_histories")
