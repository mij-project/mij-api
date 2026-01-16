"""
User Providers CRUD操作
"""
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.user_providers import UserProviders
from datetime import datetime
from app.core.logger import Logger
from typing import Optional
from app.models.providers import Providers
logger = Logger.get_logger()


def get_user_provider(
    db: Session,
    user_id: UUID,
    provider_id: UUID
) -> UserProviders | None:
    """
    ユーザープロバイダー情報取得（最新の有効なレコードを取得）
    is_main_cardがTrueのものを優先し、同じ場合はlast_used_atで降順にソート
    """
    result = db.query(UserProviders).filter(
        UserProviders.user_id == user_id,
        UserProviders.provider_id == provider_id,
        UserProviders.is_valid == True
    ).order_by(
        UserProviders.is_main_card.desc(),  # Trueを優先
        UserProviders.last_used_at.desc()   # 同じ場合は最新のものを優先
    ).first()    
    return result


def create_user_provider(
    db: Session,
    user_id: UUID,
    provider_id: UUID,
    sendid: str,
    cardbrand: Optional[str],
    cardnumber: Optional[str],
    yuko: Optional[str],
    main_card: bool,
) -> UserProviders:
    """CREDIXユーザープロバイダー情報作成"""
    user_provider = UserProviders(
        user_id=user_id,
        provider_id=provider_id,
        sendid=sendid,
        is_valid=True,
        last_used_at=datetime.utcnow(),
        cardbrand=cardbrand,
        cardnumber=cardnumber,
        yuko=yuko,
        is_main_card=main_card,
    )
    db.add(user_provider)
    db.commit()
    db.refresh(user_provider)
    return user_provider


def create_albatal_user_provider(
    db: Session,
    user_id: UUID,
    provider_id: UUID,
    provider_email: str,
    is_valid: bool,
) -> UserProviders:
    """Albatalユーザープロバイダー情報作成"""
    user_provider = UserProviders(
        user_id=user_id,
        provider_id=provider_id,
        provider_email=provider_email,
        is_valid=is_valid,
    )
    db.add(user_provider)
    db.commit()
    db.refresh(user_provider)
    return user_provider

def update_last_used_at(
    db: Session,
    user_provider_id: UUID
) -> UserProviders:
    """最終利用日時更新"""
    user_provider = db.query(UserProviders).filter(UserProviders.id == user_provider_id).first()
    if user_provider:
        user_provider.last_used_at = datetime.utcnow()
        db.commit()
        db.refresh(user_provider)
    return user_provider

def get_user_provider_by_sendid(
    db: Session,
    sendid: str
) -> UserProviders | None:
    """sendidからユーザープロバイダー情報取得"""
    result = db.query(UserProviders).filter(UserProviders.sendid == sendid).first()
    return result

def get_user_providers_by_user_id(
    db: Session,
    user_id: UUID
) -> list[UserProviders]:
    """
    ユーザーIDから全てのプロバイダー情報を取得
    """
    result = db.query(UserProviders).filter(
        UserProviders.user_id == user_id,
        UserProviders.is_valid == True
    ).order_by(UserProviders.last_used_at.desc()).all()
    return result


def set_main_card(
    db: Session,
    provider_id: UUID,
    user_id: UUID
) -> UserProviders:
    """
    指定したプロバイダーをメインカードに設定
    同じユーザーの他のカードは全てis_main_card=Falseに設定する
    """
    # 対象のプロバイダーを取得
    target_provider = db.query(UserProviders).filter(
        UserProviders.id == provider_id,
        UserProviders.user_id == user_id,
        UserProviders.is_valid == True
    ).first()

    if not target_provider:
        raise ValueError("指定されたプロバイダーが見つかりません")

    # 同じユーザーの全てのカードのis_main_cardをFalseに設定
    db.query(UserProviders).filter(
        UserProviders.user_id == user_id,
        UserProviders.is_valid == True
    ).update({"is_main_card": False})

    # 対象のカードをメインカードに設定
    target_provider.is_main_card = True
    target_provider.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(target_provider)

    logger.info(f"Set main card: user_id={user_id}, provider_id={provider_id}")
    return target_provider


def delete_user_provider(
    db: Session,
    provider_id: UUID,
    user_id: UUID
) -> bool:
    """
    指定したプロバイダーを物理削除
    """
    # 対象のプロバイダーを取得
    target_provider = db.query(UserProviders).filter(
        UserProviders.id == provider_id,
        UserProviders.user_id == user_id
    ).first()

    if not target_provider:
        raise ValueError("指定されたプロバイダーが見つかりません")

    # 物理削除
    db.delete(target_provider)
    db.commit()

    logger.info(f"Deleted user provider: user_id={user_id}, provider_id={provider_id}")
    return True

def get_albatal_provider_email(db: Session, user_id: str) -> Optional[str]:
    """
    プロバイダーのメールアドレスを取得
    """
    try:
        user_provider = (
            db.query(UserProviders)
            .join(Providers, Providers.id == UserProviders.provider_id)
            .filter(
                Providers.code == "albatal",
                UserProviders.is_valid == True,
                UserProviders.user_id == user_id,
            ).first()
            
        )
        return user_provider.provider_email if user_provider else None
    except Exception as e:
        logger.error(f"Get provider email error: {e}")
        return None
