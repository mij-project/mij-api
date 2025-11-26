from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db.base import get_db
from app.schemas.banners import ActiveBannersResponse, BannerResponse, PreRegisterUserResponse
from app.crud.banners_crud import get_active_banners, get_pre_register_users_random

router = APIRouter()


@router.get("/active", response_model=ActiveBannersResponse)
def get_active_banners_endpoint(db: Session = Depends(get_db)) -> ActiveBannersResponse:
    """
    現在有効なバナー一覧とpre-registerイベント参加ユーザーを取得

    Returns:
        ActiveBannersResponse: 有効なバナー一覧とユーザー情報
    """
    try:
        banners = get_active_banners(db)
        pre_register_users = get_pre_register_users_random(db, limit=5)

        return ActiveBannersResponse(
            banners=[BannerResponse(**banner) for banner in banners],
            pre_register_users=[PreRegisterUserResponse(**user) for user in pre_register_users]
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"バナー取得に失敗しました: {str(e)}"
        )


@router.get("/pre-register-users", response_model=List[PreRegisterUserResponse])
def get_pre_register_users_endpoint(db: Session = Depends(get_db)) -> List[PreRegisterUserResponse]:
    """
    イベント"pre-register"に参加しているユーザーをランダムで最大5件取得

    Returns:
        List[PreRegisterUserResponse]: ユーザーリスト
    """
    try:
        users = get_pre_register_users_random(db, limit=5)

        return [PreRegisterUserResponse(**user) for user in users]
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ユーザー取得に失敗しました: {str(e)}"
        )
