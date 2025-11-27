import os
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql.functions import now
from app.models.sms_verifications import SMSVerifications
from app.db.base import get_db
from app.models.creators import Creators
from app.schemas.sms_verifications import SMSVerificationRequest, SMSVerificationResponse, SMSVerificationVerifyRequest
from app.api.commons.utils import generate_sms_code, generete_hash, check_sms_verify
from app.deps.auth import get_current_user
from app.crud.sms_verifications_crud import (
    get_latest_sms_verification, 
    invalidate_sms_verification, 
    insert_sms_verification, 
    get_sms_verification_by_phone_e164_and_purpose,
    update_sms_verification_status
)
from app.crud.creater_crud import create_creator
from app.crud.user_crud import update_user_phone_verified_at
from app.services.s3.sms_auth import send_sms
from app.constants.enums import SMSStatus, CreatorStatus
from app.constants.limits import SMSVerificationLimits  
from datetime import datetime, timedelta, timezone
from app.core.logger import Logger
from app.constants.number import PlatformFeePercent
logger = Logger.get_logger()
router = APIRouter()

RESEND_COOLDOWN = int(os.getenv("SMS_RESEND_COOLDOWN_SECONDS", "60"))
SMS_TTL = int(os.getenv("SMS_CODE_TTL_SECONDS", "300"))
MAX_ATTEMPTS = int(os.getenv("SMS_MAX_ATTEMPTS", "3"))

@router.post("/send")
def send_sms_verification(
    sms_verification_request: SMSVerificationRequest,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """SMS認証を送信する

    Args:
        sms_verification_request (SMSVerificationRequest): 認証情報
        db (Session): データベースセッション

    Returns:
        dict: 送信結果
    """
    try:

        user_id = user.id

        phone_e164_count = db.query(Creators).filter(Creators.phone_number == sms_verification_request.phone_e164).count()
        if phone_e164_count >= SMSVerificationLimits.PHONE_NUMBER_MAX_COUNT:
            return Response(content="電話番号の登録上限に達しました。", status_code=400)

        latest_sms_verification = get_latest_sms_verification(db, sms_verification_request.phone_e164, sms_verification_request.purpose, user_id)

        # クールダウン
        if latest_sms_verification and (datetime.now(timezone.utc) - latest_sms_verification.last_sent_at.replace(tzinfo=timezone.utc)).total_seconds() < RESEND_COOLDOWN:
            raise Response(status_code=429, detail="送信間隔が短すぎます。しばらくしてから再試行してください。")

        # 既存PENDINGは無効化（同一目的で並行利用させない）
        if latest_sms_verification and latest_sms_verification.status == SMSStatus.PENDING:
            invalidate_sms_verification(db, sms_verification_request.phone_e164, sms_verification_request.purpose)
            db.commit()
        
        # コード生成
        code = generate_sms_code(5)

        logger.info(f"[LOCAL SMS] code: {code}")
        message = f"mijfans SMS認証コード: {code}（{SMS_TTL//60}分以内に入力してください。）"

        send_sms(sms_verification_request.phone_e164, message)

        db_sms_verification = _insert_sms_verification(db, sms_verification_request.phone_e164, user_id, code, sms_verification_request.purpose)


        if not db_sms_verification:
            raise HTTPException(status_code=500, detail="SMS認証情報の挿入に失敗しました。")

        return True
    except Exception as e:
        db.rollback()
        logger.error("SMS認証エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/verify")
def verify_sms_verification(
    sms_verification_request: SMSVerificationVerifyRequest,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """SMS認証を検証する

    Args:
        sms_verification_request (SMSVerificationVerifyRequest): 認証情報
        db (Session): データベースセッション

    Returns:
        dict: 認証結果
    """
    try:

        now = datetime.now(timezone.utc)

        db_sms_verification = get_sms_verification_by_phone_e164_and_purpose(db, sms_verification_request.phone_e164, sms_verification_request.purpose)

        if not db_sms_verification:
            raise HTTPException(status_code=400, detail="コードが見つかりません。再送してください。")

        if db_sms_verification.expires_at.replace(tzinfo=timezone.utc) < now:
            raise HTTPException(status_code=400, detail="コードの有効期限が切れています。再送してください。")

        if db_sms_verification.attempts >= MAX_ATTEMPTS:
            raise HTTPException(status_code=400, detail="認証試行回数が最大値を超えました。再送してください。")

        if check_sms_verify(sms_verification_request.code, db_sms_verification.code_hash):
            db_sms_verification.attempts += 1
            sms_verification = update_sms_verification_status(db, db_sms_verification.id, SMSStatus.VERIFIED, db_sms_verification.attempts)

            # クリエイター情報を作成
            creator = _insert_creator(db, db_sms_verification.user_id, sms_verification_request.phone_e164)

            # ユーザーの電話番号を検証済みに更新
            users = update_user_phone_verified_at(db, db_sms_verification.user_id)

            if not creator or not users:
                raise HTTPException(status_code=500, detail="クリエイターステータスの更新に失敗しました。")
            db.commit()
            return True
        else:
            db_sms_verification.attempts += 1
            sms_verification = update_sms_verification_status(db, db_sms_verification.id, SMSStatus.FAILED, db_sms_verification.attempts)
            db.commit()
            raise HTTPException(status_code=400, detail="コードが間違っています。再送してください。")
    except Exception as e:
        db.rollback()
        logger.error("SMS認証エラーが発生しました", e)

def _insert_sms_verification(db: Session, phone_e164: str, user_id: str, code: str, purpose: int) -> SMSVerifications:
    """
    SMS認証を挿入する
    """
    db_sms_verification = SMSVerifications(
        phone_e164=phone_e164,
        purpose=purpose,
        user_id=user_id,
        code_hash=generete_hash(str(code)),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=SMS_TTL),
    )

    return insert_sms_verification(db, db_sms_verification)

def _insert_creator(db: Session, user_id: str, phone_e164: str) -> Creators:
    """
    クリエイター情報を作成する
    """
    creator_create = {
        "user_id": user_id,
        "phone_number": phone_e164,
        "status": CreatorStatus.PHONE_NUMBER_ENTERED,
        "platform_fee_percent": PlatformFeePercent.DEFAULT
    }
    return create_creator(db, creator_create)