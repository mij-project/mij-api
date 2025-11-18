# app/crud/password_reset_crud.py
from sqlalchemy.orm import Session
from app.models.password_reset_token import PasswordResetToken
from datetime import datetime, timedelta, timezone
from uuid import UUID
import secrets


def create_password_reset_token(db: Session, user_id: UUID, expires_hours: int = 1) -> PasswordResetToken:
    """
    パスワードリセットトークンを作成

    Args:
        db: データベースセッション
        user_id: ユーザーID
        expires_hours: 有効期限（時間）

    Returns:
        PasswordResetToken: 作成されたトークン
    """
    # ランダムなトークンを生成（32バイト = 64文字の16進数文字列）
    token_string = secrets.token_urlsafe(32)

    # 有効期限を設定
    expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)

    # トークンを作成
    token = PasswordResetToken(
        user_id=user_id,
        token=token_string,
        expires_at=expires_at,
        used=False
    )

    db.add(token)
    db.commit()
    db.refresh(token)

    return token


def get_password_reset_token(db: Session, token_string: str) -> PasswordResetToken | None:
    """
    トークン文字列からPasswordResetTokenを取得

    Args:
        db: データベースセッション
        token_string: トークン文字列

    Returns:
        PasswordResetToken | None: トークン（存在しない場合はNone）
    """
    return db.query(PasswordResetToken).filter(
        PasswordResetToken.token == token_string
    ).first()


def is_token_valid(token: PasswordResetToken) -> bool:
    """
    トークンが有効かどうかを判定

    Args:
        token: パスワードリセットトークン

    Returns:
        bool: 有効な場合True
    """
    if token.used:
        return False
    if datetime.now(timezone.utc) > token.expires_at:
        return False
    return True


def mark_token_as_used(db: Session, token: PasswordResetToken) -> None:
    """
    トークンを使用済みとしてマーク

    Args:
        db: データベースセッション
        token: パスワードリセットトークン
    """
    token.used = True
    db.commit()


def delete_expired_tokens(db: Session) -> int:
    """
    期限切れのトークンを削除

    Args:
        db: データベースセッション

    Returns:
        int: 削除されたトークンの数
    """
    count = db.query(PasswordResetToken).filter(
        PasswordResetToken.expires_at < datetime.now(timezone.utc)
    ).delete()
    db.commit()
    return count
