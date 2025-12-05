from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, func, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users


class BankRequestHistories(Base):
    """銀行口座取得APIリクエスト履歴"""

    __tablename__ = "bank_request_histories"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    # リクエスト者
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
        comment="APIリクエストを実行したユーザー",
    )

    # リクエスト種別
    request_type: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        comment="1=bank_search(銀行検索), 2=branch_search(支店検索), 3=account_verify(口座確認)",
    )

    # リクエスト内容
    bank_code: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="銀行コード（検索時）"
    )
    branch_code: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="支店コード（検索時）"
    )
    account_number: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="口座番号（確認時）"
    )

    # リクエスト結果
    response_data: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, comment="APIレスポンスデータ"
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["Users"] = relationship(
        "Users", back_populates="bank_request_histories"
    )
