from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.schemas.user_settings import UserSettingsResponse, UserSettingsType
from app.crud.user_settings_curd import get_user_settings_by_user_id, update_user_settings_by_user_id

router = APIRouter()

@router.get("/", response_model=UserSettingsResponse)
async def get_user_settings(
    type: UserSettingsType = Query(..., description="ユーザー設定タイプ"),
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    settings = get_user_settings_by_user_id(db, current_user.id, type)
    if not settings:
        raise HTTPException(status_code=404, detail="ユーザー設定が見つかりません")
    return UserSettingsResponse(
        id=settings.id,
        user_id=settings.user_id,
        type=settings.type,
        settings=settings.settings,
        created_at=settings.created_at,
        updated_at=settings.updated_at
    )

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