from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.crud.user_providers_crud import get_user_providers_by_user_id
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