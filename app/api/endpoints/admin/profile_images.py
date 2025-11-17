from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
import math

from app.deps.auth import get_current_admin_user
from app.db.base import get_db
from app.models.admins import Admins
from app.crud import profile_image_crud
from app.schemas.profile_image import (
    ProfileImageSubmissionDetail,
    ProfileImageSubmissionListResponse,
    ProfileImageApprovalRequest,
    ProfileImageRejectionRequest
)

router = APIRouter()

@router.get("", response_model=ProfileImageSubmissionListResponse)
def get_profile_image_submissions(
    page: int = Query(1, ge=1, description="ページ番号"),
    limit: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    status: Optional[str] = Query(None, description="pending/approved/rejected"),
    search: Optional[str] = Query(None, description="検索クエリ（メール、ユーザー名等）"),
    sort: str = Query("created_at_desc", description="created_at_desc/created_at_asc/checked_at_desc/checked_at_asc"),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    画像申請一覧を取得（管理者用）

    - **page**: ページ番号（1から開始）
    - **limit**: 1ページあたりの件数（1-100）
    - **status**: ステータスフィルタ（pending/approved/rejected）
    - **search**: 検索クエリ（メール、ユーザー名、プロフィール名）
    - **sort**: ソート順（created_at_desc/created_at_asc/checked_at_desc/checked_at_asc）
    """
    submissions, total = profile_image_crud.get_submissions_paginated(
        db=db,
        page=page,
        limit=limit,
        status=status,
        search=search,
        sort=sort
    )

    total_pages = math.ceil(total / limit) if total > 0 else 0

    return ProfileImageSubmissionListResponse(
        items=submissions,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages
    )

@router.get("/{submission_id}", response_model=ProfileImageSubmissionDetail)
def get_profile_image_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    画像申請詳細を取得（管理者用）

    - **submission_id**: 申請ID
    """
    detail = profile_image_crud.get_submission_detail_by_id(db, submission_id)

    if not detail:
        raise HTTPException(status_code=404, detail="申請が見つかりません")

    return detail

@router.put("/{submission_id}/approve")
def approve_profile_image_submission(
    submission_id: UUID,
    request: ProfileImageApprovalRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    画像申請を承認（管理者用）

    承認すると該当ユーザーのプロフィール画像が自動的に更新されます。

    - **submission_id**: 申請ID
    """
    success = profile_image_crud.approve_submission(
        db=db,
        submission_id=submission_id,
        admin_id=current_admin.id
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail="承認に失敗しました。申請が存在しないか、既に処理済みです。"
        )

    db.commit()
    profile_image_crud.add_notification_for_profile_image_submission(
        db=db,
        submission_id=submission_id,
        type="approved"
    )
    return {
        "success": True,
        "message": "画像申請を承認しました。プロフィールが更新されました。"
    }

@router.put("/{submission_id}/reject")
def reject_profile_image_submission(
    submission_id: UUID,
    request: ProfileImageRejectionRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    画像申請を却下（管理者用）

    却下理由を記録し、ユーザーに通知されます。

    - **submission_id**: 申請ID
    - **rejection_reason**: 却下理由（必須、1-500文字）
    """
    success = profile_image_crud.reject_submission(
        db=db,
        submission_id=submission_id,
        admin_id=current_admin.id,
        rejection_reason=request.rejection_reason
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail="却下に失敗しました。申請が存在しないか、既に処理済みです。"
        )

    db.commit()
    profile_image_crud.add_notification_for_profile_image_submission(
        db=db,
        submission_id=submission_id,
        type="rejected"
    )
    return {
        "success": True,
        "message": "画像申請を却下しました。"
    }
