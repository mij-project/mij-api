"""
User Providers CRUD操作
"""
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.user_providers import UserProviders
from datetime import datetime
from app.core.logger import Logger
from typing import Optional
logger = Logger.get_logger()


def get_user_provider(
    db: Session,
    user_id: UUID,
    provider_id: UUID
) -> UserProviders | None:
    """
    ユーザープロバイダー情報取得（最新の有効なレコードを取得）
    """
    result = db.query(UserProviders).filter(
        UserProviders.user_id == user_id,
        UserProviders.provider_id == provider_id,
        UserProviders.is_valid == True
    ).order_by(UserProviders.last_used_at.desc()).first()

    
    return result


def create_user_provider(
    db: Session,
    user_id: UUID,
    provider_id: UUID,
    sendid: str,
    cardbrand: Optional[str],
    cardnumber: Optional[str],
    yuko: Optional[str],
) -> UserProviders:
    """ユーザープロバイダー情報作成"""
    user_provider = UserProviders(
        user_id=user_id,
        provider_id=provider_id,
        sendid=sendid,
        is_valid=True,
        last_used_at=datetime.utcnow(),
        cardbrand=cardbrand,
        cardnumber=cardnumber,
        yuko=yuko,
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