from datetime import datetime
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.user_settings import UserSettings
from app.schemas.user_settings import UserSettingsType


def get_user_settings_by_user_id(db: Session, user_id: UUID, type: UserSettingsType) -> UserSettings:
    return db.query(UserSettings).filter(UserSettings.user_id == user_id, UserSettings.type == type).first()

def update_user_settings_by_user_id(db: Session, user_id: UUID, type: UserSettingsType, settings: dict) -> UserSettings:
    try:
        user_settings = get_user_settings_by_user_id(db, user_id, type)
        if not user_settings:
            user_settings = UserSettings(
                user_id=user_id, 
                type=type, 
                settings=settings,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            db.add(user_settings)
            db.commit()
            db.refresh(user_settings)
            return user_settings
        else:
            user_settings.settings = settings
            user_settings.updated_at = datetime.now()
            db.commit()
            db.refresh(user_settings)
            return user_settings
    except Exception as e:
        print("ユーザー設定更新エラーが発生しました", e)
        db.rollback()
        return None