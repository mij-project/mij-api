# app/api/endpoints/customer/password_reset.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.schemas.password_reset import (
    PasswordResetRequest,
    PasswordResetRequestResponse,
    PasswordResetConfirm,
    PasswordResetConfirmResponse,
)
from app.crud.user_crud import get_user_by_email
from app.crud.password_reset_crud import (
    create_password_reset_token,
    get_password_reset_token,
    is_token_valid,
    mark_token_as_used,
)
from app.services.email.send_email import send_password_reset_email
from app.core.security import hash_password
from app.core.config import settings
import os
from app.core.logger import Logger

logger = Logger.get_logger()
router = APIRouter()


@router.post("/request", response_model=PasswordResetRequestResponse)
def request_password_reset(
    payload: PasswordResetRequest,
    db: Session = Depends(get_db)
):
    """
    パスワードリセット申請

    Args:
        payload: メールアドレス
        db: データベースセッション

    Returns:
        PasswordResetRequestResponse: 成功メッセージ
    """
    # ユーザーを検索
    user = get_user_by_email(db, payload.email)

    # セキュリティのため、ユーザーが存在しない場合でも同じメッセージを返す
    if not user:
        return PasswordResetRequestResponse(
            message="パスワードリセットメールを送信しました。メールをご確認ください。"
        )

    # パスワードリセットトークンを作成
    reset_token = create_password_reset_token(db, user.id, expires_hours=1)

    # リセットURLを生成
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    reset_url = f"{frontend_url}/auth/reset-password?token={reset_token.token}"

    # メールを送信
    try:
        send_password_reset_email(
            to=user.email,
            reset_url=reset_url,
            display_name=user.profile_name or ""
        )
    except Exception as e:
        logger.error(f"[password_reset] Failed to send email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="メール送信に失敗しました"
        )

    return PasswordResetRequestResponse(
        message="パスワードリセットメールを送信しました。メールをご確認ください。"
    )


@router.post("/confirm", response_model=PasswordResetConfirmResponse)
def confirm_password_reset(
    payload: PasswordResetConfirm,
    db: Session = Depends(get_db)
):
    """
    パスワードリセット確認・パスワード更新

    Args:
        payload: トークンと新しいパスワード
        db: データベースセッション

    Returns:
        PasswordResetConfirmResponse: 成功メッセージ

    Raises:
        HTTPException: トークンが無効または期限切れの場合
    """
    # トークンを取得
    reset_token = get_password_reset_token(db, payload.token)

    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無効なトークンです"
        )

    # トークンの有効性を確認
    if not is_token_valid(reset_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="トークンが期限切れまたは使用済みです"
        )

    # ユーザーを取得
    user = reset_token.user
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ユーザーが見つかりません"
        )

    # パスワードをハッシュ化して更新
    user.password_hash = hash_password(payload.new_password)
    db.commit()

    # トークンを使用済みにマーク
    mark_token_as_used(db, reset_token)

    return PasswordResetConfirmResponse(
        message="パスワードを更新しました"
    )
