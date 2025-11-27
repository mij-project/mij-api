from datetime import datetime, timezone
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.core.logger import Logger
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models import UserSettings
from app.models.user import Users
from app.schemas.user_settings import UserSettingsResponse, UserSettingsType
from app.crud.user_settings_curd import get_user_settings_by_user_id, update_user_settings_by_user_id

logger = Logger.get_logger()
router = APIRouter()

@router.get("", response_model=UserSettingsResponse)
async def get_user_settings(
    type: UserSettingsType = Query(..., description="ユーザー設定タイプ"),
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    try:
        settings = get_user_settings_by_user_id(db, current_user.id, type)
        if not settings:
            new_settings = UserSettings(
                user_id=current_user.id,
                type=type,
                settings={"follow": True, "postLike": True, "postApprove": True, "profileApprove": True, "identityApprove": True},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            db.add(new_settings)
            db.commit()
            db.refresh(new_settings)
            settings = new_settings
        return UserSettingsResponse(
            id=settings.id,
            user_id=settings.user_id,
            type=settings.type,
            settings=settings.settings,
            created_at=settings.created_at,
            updated_at=settings.updated_at
        )
    except Exception as e:
        db.rollback()
        logger.error(f"ユーザー設定取得エラーが発生しました: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{type:int}")
async def update_user_settings(
    type: UserSettingsType,
    settings: dict = Body(..., description="ユーザー設定"),
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    updated = update_user_settings_by_user_id(db, current_user.id, type, settings)
    if not updated:
        raise HTTPException(status_code=500, detail="ユーザー設定更新エラーが発生しました")
    return {"message": "Ok"}