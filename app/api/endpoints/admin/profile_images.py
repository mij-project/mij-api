from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
import math
import os

from app.deps.auth import get_current_admin_user
from app.db.base import get_db
from app.models.admins import Admins
from app.crud import profile_image_crud
from app.crud.generation_media_crud import upsert_generation_media_by_user
from app.schemas.profile_image import (
    ProfileImageSubmissionDetail,
    ProfileImageSubmissionListResponse,
    ProfileImageApprovalRequest,
    ProfileImageRejectionRequest
)
from app.services.s3.image_screening import generate_profile_ogp_image
from app.services.s3.client import upload_ogp_image_to_s3
from app.services.s3.keygen import account_asset_key
from app.models.profiles import Profiles
from app.models.user import Users

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

    # プロフィールOGP画像を生成（エラーが発生しても処理は継続）
    try:
        # 申請情報を取得
        submission = profile_image_crud.get_submission_by_id(db, submission_id)
        if submission:
            # ユーザー情報とプロフィール情報を取得
            user = db.query(Users).filter(Users.id == submission.user_id).first()
            profile = db.query(Profiles).filter(Profiles.user_id == submission.user_id).first()

            if user and profile:
                # 環境変数からCDN_BASE_URLを取得
                CDN_BASE_URL = os.getenv("CDN_BASE_URL")

                # カバー画像URLとアバターURLを生成
                cover_url = f"{CDN_BASE_URL}/{profile.cover_url}" if profile.cover_url else None
                avatar_url = f"{CDN_BASE_URL}/{profile.avatar_url}" if profile.avatar_url else None
                profile_name = user.profile_name if user.profile_name else user.email
                username = profile.username if profile.username else user.email

                # プロフィールOGP画像を生成
                ogp_image_data = generate_profile_ogp_image(
                    cover_url=cover_url,
                    avatar_url=avatar_url,
                    profile_name=profile_name,
                    username=username
                )

                # S3キーを生成
                s3_key = account_asset_key(
                    creator_id=str(user.id),
                    kind="profile-ogp",
                    ext="png"
                )

                # S3にアップロード
                upload_ogp_image_to_s3(s3_key, ogp_image_data)

                # generation_mediaに保存（既存がある場合は上書き）
                upsert_generation_media_by_user(db, str(user.id), s3_key)
                db.commit()

                print(f"Profile OGP image generated for user {user.id}: {s3_key}")

    except Exception as e:
        print(f"Failed to generate profile OGP image: {e}")
        # エラーが発生しても処理は継続（承認処理には影響させない）
        db.rollback()
        # 承認は完了しているので、再度commitだけ実行
        db.commit()

    # 通知送信
    profile_image_crud.add_mail_notification_for_profile_image_submission(
        db=db,
        submission_id=submission_id,
        type="approved"
    )
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
    profile_image_crud.add_mail_notification_for_profile_image_submission(
        db=db,
        submission_id=submission_id,
        type="rejected"
    )
    profile_image_crud.add_notification_for_profile_image_submission(
        db=db,
        submission_id=submission_id,
        type="rejected"
    )
    return {
        "success": True,
        "message": "画像申請を却下しました。"
    }
