from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.db.base import get_db
from app.core.security import verify_password, create_access_token, create_refresh_token, new_csrf_token
from app.core.cookies import set_auth_cookies
from app.crud.admin_crud import get_admin_by_email
from app.schemas.admin import AdminLoginRequest, AdminLoginResponse, AdminResponse
from app.deps.auth import get_current_admin_user
from app.models.admins import Admins

router = APIRouter()
security = HTTPBearer()

@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(
    credentials: AdminLoginRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    """管理者ログイン - adminsテーブルを使用"""

    # 管理者を取得
    admin = get_admin_by_email(db, email=credentials.email)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    # パスワード確認
    if not verify_password(credentials.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    # ステータス確認 (1=有効)
    if admin.status != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is not active"
        )

    # ログイン時刻を更新
    admin.last_login_at = datetime.now(timezone.utc)
    db.commit()

    # JWTトークン生成
    access_token = create_access_token(sub=str(admin.id))
    refresh_token = create_refresh_token(sub=str(admin.id))
    csrf_token = new_csrf_token()

    # Cookieに認証情報を設定
    set_auth_cookies(response, access_token, refresh_token, csrf_token)

    return AdminLoginResponse(
        token=access_token,
        admin=AdminResponse.from_orm(admin)
    )

@router.post("/logout")
async def admin_logout(
    response: Response,
    current_admin: Admins = Depends(get_current_admin_user)
):
    """管理者ログアウト"""
    from app.core.cookies import clear_auth_cookies

    # Cookieから認証情報をクリア
    clear_auth_cookies(response)
    return {"message": "Successfully logged out"}

@router.get("/me", response_model=AdminResponse)
async def get_current_admin(
    current_admin: Admins = Depends(get_current_admin_user)
):
    """現在の管理者情報を取得"""
    return AdminResponse.from_orm(current_admin)