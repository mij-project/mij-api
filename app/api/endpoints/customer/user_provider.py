from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.db.base import get_db
from app.crud.user_providers_crud import (
    get_user_providers_by_user_id,
    set_main_card,
    delete_user_provider
)
from app.models.user_providers import UserProviders
from app.models.user import Users
from app.deps.auth import get_current_user

router = APIRouter()

@router.get("/")
def get_user_providers(
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    """
    ユーザープロバイダー情報を取得
    """
    try:
        user_providers = get_user_providers_by_user_id(db, current_user.id)
        return user_providers
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{provider_id}/set-main")
def set_main_card_endpoint(
    provider_id: UUID,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    """
    指定したプロバイダーをメインカードに設定
    """
    try:
        updated_provider = set_main_card(db, provider_id, current_user.id)
        return updated_provider
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{provider_id}")
def delete_user_provider_endpoint(
    provider_id: UUID,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    """
    指定したプロバイダーを削除
    """
    try:
        delete_user_provider(db, provider_id, current_user.id)
        return {"message": "プロバイダーが正常に削除されました"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))