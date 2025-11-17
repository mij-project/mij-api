# app/schemas/password_reset.py
from pydantic import BaseModel, EmailStr, Field


class PasswordResetRequest(BaseModel):
    """パスワードリセット申請リクエスト"""
    email: EmailStr = Field(..., description="メールアドレス")


class PasswordResetRequestResponse(BaseModel):
    """パスワードリセット申請レスポンス"""
    message: str = Field(..., description="メッセージ")


class PasswordResetConfirm(BaseModel):
    """パスワードリセット確認リクエスト"""
    token: str = Field(..., description="リセットトークン")
    new_password: str = Field(..., min_length=6, description="新しいパスワード（6文字以上）")


class PasswordResetConfirmResponse(BaseModel):
    """パスワードリセット確認レスポンス"""
    message: str = Field(..., description="メッセージ")
