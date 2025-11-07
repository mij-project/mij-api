from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.schemas.banners import ActiveBannersResponse, BannerResponse
from app.crud.banners_crud import get_active_banners

router = APIRouter()


@router.get("/active", response_model=ActiveBannersResponse)
def get_active_banners_endpoint(db: Session = Depends(get_db)) -> ActiveBannersResponse:
    """
    現在有効なバナー一覧を取得（表示期間内 & status=1）

    Returns:
        ActiveBannersResponse: 有効なバナー一覧
    """
    try:
        banners = get_active_banners(db)

        return ActiveBannersResponse(
            banners=[BannerResponse(**banner) for banner in banners]
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"バナー取得に失敗しました: {str(e)}"
        )
