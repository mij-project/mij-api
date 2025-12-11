import os
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Response
from app.db.base import get_db
from sqlalchemy.orm import Session
from app.constants.event_code import EventCode
from app.crud.companies_crud import get_company_by_code, add_company_user
from app.crud.email_verification_crud import (
    issue_verification_token, 
    remake_email_verification_token, 
    get_verification_token,
    update_verification_token
)
from app.models.events import UserEvents
from app.crud.user_crud import update_user_email_verified_at, get_user_by_id
from app.crud.preregistrations_curd import get_preregistration_by_email
from app.services.email.send_email import send_email_verification
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.user import Users
import hashlib
from datetime import datetime, timezone
from app.core.config import settings
from app.constants.number import CompanyFeePercent
from app.schemas.user import UserCreate, EmailVerificationIn
from app.crud.user_crud import resend_email_verification
from app.schemas.auth_email_verify import VerifyIn
from app.crud.events_crud import get_event_by_code
from app.crud.user_events_crud import create_user_event
from app.core.security import create_access_token, create_refresh_token, new_csrf_token
from app.core.cookies import set_auth_cookies
from app.api.commons.utils import generate_email_verification_url
from app.core.logger import Logger

router = APIRouter()

logger = Logger.get_logger()
@router.post("/verify/")
def verify(body: VerifyIn, response: Response, db: AsyncSession = Depends(get_db)):
    """メールアドレスの認証

    Args:
        body (VerifyIn): 認証情報
        db (AsyncSession, optional): データベースセッション. Defaults to Depends(get_db).

    Raises:
        HTTPException: リンクが無効か、期限切れです。
        HTTPException: メールアドレスの認証に失敗しました

    Returns:
        dict: メールアドレスの認証結果
    """
    try:
        token_hash = hashlib.sha256(body.token.encode()).hexdigest()
        rec = get_verification_token(db, token_hash)
        if not rec or rec.consumed_at is not None or rec.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="リンクが無効か、期限切れです。")

        # 事前登録判定
        user = get_user_by_id(db, rec.user_id)
        result = get_preregistration_by_email(db, user.email)

        # 事前登録イベントを挿入
        if result:
            _insert_user_event(db, rec.user_id, EventCode.PRE_REGISTRATION)

        # 企業登録判定
        if body.code:
            _insert_company_user(db, body.code, rec.user_id)


        # 成功: ユーザーを検証済みに
        update_user_email_verified_at(db, rec.user_id, result)
        # トークン全無効化
        update_verification_token(db, rec.user_id)

        access = create_access_token(str(rec.user_id))
        refresh = create_refresh_token(str(rec.user_id))
        csrf = new_csrf_token()

        set_auth_cookies(response, access, refresh, csrf)
        db.commit()
        return {"result": True , "csrf_token": csrf}
    except Exception as e:
        db.rollback()
        logger.exception("メールアドレスの認証エラーが発生しました", e)
        raise HTTPException(500, f"Failed to verify: {e}")

@router.post("/resend/")
def verify_email(
    email_verification_in: EmailVerificationIn, 
    db: Session = Depends(get_db),     background: BackgroundTasks = BackgroundTasks()
):
    """
    メールアドレスの再送信

    Args:
        user_create (UserCreate): ユーザー登録情報
        db (Session, optional): データベースセッション
        background (BackgroundTasks, optional): バックグラウンドタスク

    Returns:
        dict: メールアドレスの再送信結果

    Raises:
        HTTPException: メールアドレスの再送信に失敗した場合
    """
    try:
        user = resend_email_verification(db, email_verification_in.email)

        if user and not user.is_email_verified:
            raw, _ = remake_email_verification_token(db, user.id)

            if email_verification_in.code:
                verify_url = generate_email_verification_url(raw, email_verification_in.code)
            else:
                verify_url = generate_email_verification_url(raw)
            background.add_task(
                send_email_verification, 
                user.email, 
                verify_url, 
                user.profile_name if hasattr(user, "profile_name") else None,
            )
            db.commit()
            db.refresh(user)
        return {"message": "email resend"}
    except Exception as e:
        logger.error("メールアドレスの再送信エラーが発生しました", e)
        raise HTTPException(500, f"Failed to resend: {e}")


def _insert_user_event(db: Session, user_id: str, event_code: str) -> bool:
    """
    ユーザーイベントを挿入
    """
    event = get_event_by_code(db, event_code)
    if event:
        return create_user_event(db, user_id, event.id)
    return False

def _insert_company_user(db: Session, company_id: str, user_id: str) -> bool:
    """企業にユーザーを追加

    Args:
        db (Session): データベースセッション
        company_id (str): 企業ID
        user_id (str): ユーザーID

    Raises:
        HTTPException: 企業が見つかりません

    Returns:
        bool: 企業にユーザーを追加
    """
    company = get_company_by_code(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="企業が見つかりません")

    # 親会社と子会社の設定値を追加
    targets = (
        [
            (company.parent_company_id, CompanyFeePercent.PARENT_DEFAULT, False),
            (company.id, CompanyFeePercent.CHILD_DEFAULT, True),
        ]
        # 親会社がない場合は通常の設定値を追加
        if company.parent_company_id
        else [(company.id, CompanyFeePercent.DEFAULT, True)]
    )

    for company_id, fee_percent, is_referrer in targets:
        add_company_user(db, company_id, user_id, fee_percent, is_referrer)

    return True