"""
User Providers CRUD操作
"""
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.user_providers import UserProviders
from datetime import datetime
from app.core.logger import Logger

logger = Logger.get_logger()


async def get_user_provider(
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


async def create_user_provider(
    db: Session,
    user_id: UUID,
    provider_id: UUID,
    sendid: str
) -> UserProviders:
    """ユーザープロバイダー情報作成"""
    user_provider = UserProviders(
        user_id=user_id,
        provider_id=provider_id,
        sendid=sendid,
        is_valid=True,
        last_used_at=datetime.utcnow()
    )
    db.add(user_provider)
    await db.commit()
    await db.refresh(user_provider)
    return user_provider


async def update_last_used_at(
    db: Session,
    user_provider_id: UUID
) -> UserProviders:
    """最終利用日時更新"""
    result = await db.execute(
        select(UserProviders).where(UserProviders.id == user_provider_id)
    )
    user_provider = result.scalar_one()
    user_provider.last_used_at = datetime.utcnow()
    await db.commit()
    await db.refresh(user_provider)
    return user_provider
