from typing import Optional
from fastapi import APIRouter, Depends, Query
from app.deps.auth import get_current_user_optional
from app.models.user import Users
from app.deps.initial_domain import initial_shorts_domain
from app.domain.shorts.shorts_domain import ShortsDomain

router = APIRouter()


@router.get("/recommend")
async def get_shorts_recommend(
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Cursor"),
    current_user: Optional[Users] = Depends(get_current_user_optional),
    shorts_domain: ShortsDomain = Depends(initial_shorts_domain),
):
    return shorts_domain.get_shorts_recommend(user=current_user, limit=limit, cursor=cursor)


@router.get("/follows")
async def get_shorts_follows(
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Cursor"),
    current_user: Optional[Users] = Depends(get_current_user_optional),
    shorts_domain: ShortsDomain = Depends(initial_shorts_domain),
):
    return shorts_domain.get_shorts_follows(user=current_user, limit=limit, cursor=cursor)
