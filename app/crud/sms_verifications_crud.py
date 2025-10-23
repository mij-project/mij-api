from sqlalchemy.orm import Session
from app.models.sms_verifications import SMSVerifications
from app.constants.enums import SMSStatus, SMSPurpose
from datetime import datetime
def get_latest_sms_verification(db: Session, phone_e164: str, purpose: int, user_id: str) -> SMSVerifications:
    """
    SMS認証を取得する
    """
    return db.query(SMSVerifications).filter(
        SMSVerifications.user_id == user_id,
        SMSVerifications.phone_e164 == phone_e164,
        SMSVerifications.purpose == purpose,
        SMSVerifications.status != SMSStatus.PENDING,
        SMSVerifications.expires_at > datetime.now()
    ).order_by(SMSVerifications.created_at.desc()).first()


def invalidate_sms_verification(db: Session, phone_e164: str, purpose: int) -> int:
    """
    SMS認証を無効化する
    """
    return db.query(SMSVerifications).filter(
        SMSVerifications.phone_e164 == phone_e164,
        SMSVerifications.purpose == purpose,
        SMSVerifications.status == SMSStatus.PENDING
    ).update({
        "status": SMSStatus.INVALIDATED
    })


def insert_sms_verification(db: Session, sms_verification: SMSVerifications) -> SMSVerifications:
    """SMS認証を挿入する

    Args:
        db (Session): データベースセッション
        sms_verification (SMSVerifications): SMS認証情報

    Returns:
        SMSVerifications: SMS認証情報
    """
    db.add(sms_verification)
    db.commit()
    db.refresh(sms_verification)
    return sms_verification

def get_sms_verification_by_phone_e164_and_purpose(db: Session, phone_e164: str, purpose: int) -> SMSVerifications:
    """
    SMS認証を取得する
    """
    return db.query(SMSVerifications).filter(
        SMSVerifications.phone_e164 == phone_e164,
        SMSVerifications.purpose == purpose,
    ).order_by(SMSVerifications.created_at.desc()).first()


def update_sms_verification_status(db: Session, sms_verification_id: str, status: int, attempts: int = 0) -> SMSVerifications:
    """
    SMS認証を更新する
    """
    # まず更新を実行
    db.query(SMSVerifications).filter(
        SMSVerifications.id == sms_verification_id
    ).update({
        "status": status,
        "attempts": attempts,
        "updated_at": datetime.now()
    })
    
    # 更新されたオブジェクトを取得して返す
    return db.query(SMSVerifications).filter(
        SMSVerifications.id == sms_verification_id
    ).first()