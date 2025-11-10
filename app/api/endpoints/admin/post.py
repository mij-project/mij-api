from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.deps.auth import get_current_admin_user
from app.schemas.admin import (
    AdminPostResponse,
    PaginatedResponse,
    PostRejectRequest,
    PostRejectResponse,
    AdminPostDetailResponse,
)
from app.models.admins import Admins
from app.crud.admin_crud import (
    get_posts_paginated,
    update_post_status,
    reject_post_with_comments,
)
from app.crud.post_crud import get_post_by_id
from app.api.commons.utils import resolve_media_asset_storage_key

router = APIRouter()

@router.get("/", response_model=PaginatedResponse[AdminPostResponse])
def get_posts(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[str] = None,
    sort: Optional[str] = "created_at_desc",
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """投稿一覧を取得"""
    
    posts, total = get_posts_paginated(
        db=db,
        page=page,
        limit=limit,
        search=search,
        status=status,
        sort=sort
    )
    
    return PaginatedResponse(
        data=[AdminPostResponse.from_orm(post) for post in posts],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit if total > 0 else 1
    )

@router.patch("/{post_id}/status")
def update_post_status(
    post_id: str,
    status: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """投稿のステータスを更新"""
    
    success = update_post_status(db, post_id, status)
    if not success:
        raise HTTPException(status_code=404, detail="投稿が見つかりません")
    
    return {"message": "投稿ステータスを更新しました"}

@router.post("/{post_id}/reject", response_model=PostRejectResponse)
def reject_post(
    post_id: str,
    reject_request: PostRejectRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """投稿を拒否し、拒否理由を保存"""

    success = reject_post_with_comments(
        db=db,
        post_id=post_id,
        post_reject_comment=reject_request.post_reject_comment,
        media_reject_comments=reject_request.media_reject_comments
    )

    if not success:
        raise HTTPException(status_code=404, detail="投稿が見つかりません")

    return PostRejectResponse(
        message="投稿を拒否しました",
        success=True
    )

@router.get("/{post_id}")
def get_post(
    post_id: str,
    db: Session = Depends(get_db),
    # current_admin: Users = Depends(get_current_admin_user)
):
    """投稿詳細を取得"""
    
    post_data = get_post_by_id(db, post_id)

    if not post_data:
        raise HTTPException(status_code=404, detail="投稿が見つかりません")

    for media_asset_id, media_asset_data in post_data['media_assets'].items():
        post_data['media_assets'][media_asset_id]['storage_key'] = resolve_media_asset_storage_key(
            media_asset_data
        )
        post_data['media_assets'][media_asset_id]['status'] = media_asset_data['status']

    return AdminPostDetailResponse(**post_data)