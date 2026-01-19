from typing import Optional
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
from app.crud.post_crud import add_mail_notification_for_post, add_notification_for_post, get_post_and_categories_by_id, update_post_status as update_post_status_crud, get_post_by_id
from app.crud.media_assets_crud import get_media_assets_by_post_id_and_kind, update_media_asset
from app.models.media_assets import MediaAssets
from app.api.commons.utils import resolve_media_asset_storage_key
from app.constants.enums import MediaAssetKind, AuthenticatedFlag, PostType, PostStatus, MediaAssetStatus
from app.services.s3.presign import get_bucket_name
from app.core.logger import Logger
import boto3
import os
from app.utils.trigger_batch_notification_newpost_arrival import trigger_batch_notification_newpost_arrival
logger = Logger.get_logger()
router = APIRouter()

# S3設定
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")


def check_media_uploading(db: Session, post) -> bool:
    """
    投稿のメディアがS3にアップロード中かチェック

    Returns:
        bool: True=送信中（S3にファイルがない）, False=アップロード完了
    """
    try:
        # 動画投稿でない場合はチェック不要
        if post.post_type != PostType.VIDEO:
            return False

        # メイン動画とサンプル動画のアセットを取得
        main_video_asset = get_media_assets_by_post_id_and_kind(
            db, str(post.id), MediaAssetKind.MAIN_VIDEO
        )
        sample_video_asset = get_media_assets_by_post_id_and_kind(
            db, str(post.id), MediaAssetKind.SAMPLE_VIDEO
        )

        # アセットがない場合は送信中
        if not main_video_asset and not sample_video_asset:
            return True

        # S3クライアントを初期化
        s3_client = boto3.client(
            's3',
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )

        # バケット名を決定（authenticated_flgに基づく）
        if post.authenticated_flg == AuthenticatedFlag.AUTHENTICATED:
            resource = "media"
        else:
            resource = "ingest"
        bucket_name = get_bucket_name(resource)

        # メイン動画のS3存在確認
        main_exists = False
        if main_video_asset and main_video_asset.storage_key:
            try:
                s3_client.head_object(Bucket=bucket_name, Key=main_video_asset.storage_key)
                main_exists = True
            except s3_client.exceptions.ClientError:
                main_exists = False

        # サンプル動画のS3存在確認
        sample_exists = False
        if sample_video_asset and sample_video_asset.storage_key:
            try:
                s3_client.head_object(Bucket=bucket_name, Key=sample_video_asset.storage_key)
                sample_exists = True
            except s3_client.exceptions.ClientError:
                sample_exists = False

        # どちらか一方でも存在しない場合は送信中
        is_uploading = not (main_exists and sample_exists)

        return is_uploading

    except Exception as e:
        logger.error(f"メディアアップロード状態チェックエラー: {e}")
        # エラー時は送信中として扱わない
        return False

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

    # 各投稿にS3アップロード状態を追加
    post_responses = []
    for post in posts:
        post_response = AdminPostResponse.from_orm(post)
        # S3にメディアがアップロード中かチェック
        is_uploading = check_media_uploading(db, post)
        # is_uploadingフィールドを更新
        post_response.is_uploading = is_uploading
        # 送信中の場合はステータスを"uploading"に変更
        if is_uploading:
            post_response.status = "uploading"
        post_responses.append(post_response)

    return PaginatedResponse(
        data=post_responses,
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit if total > 0 else 1
    )

@router.patch("/{post_id}/status")
def update_post_status_admin(
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

    # Email通知を追加
    add_mail_notification_for_post(db, post_id=post_id, type="rejected")
    # 投稿に対する通知を追加
    add_notification_for_post(db, post_id=post_id, type="rejected")
    
    return PostRejectResponse(
        message="投稿を拒否しました",
        success=True
    )

@router.post("/{post_id}/approve")
def approve_post(
    post_id: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """
    投稿を承認する

    authenticated_flg=1（認証済み）の場合:
        - 投稿ステータスをAPPROVEDに更新
        - 紐づくメディアアセットのステータスをAPPROVEDに更新
        - MediaConvert処理は実行しない（既に変換済みのため）

    authenticated_flg=0（未認証）の場合:
        - transcode_mc エンドポイントを使用してMediaConvert処理を実行
    """
    try:
        # 投稿を取得
        post = get_post_by_id(db, post_id)
        if not post:
            raise HTTPException(status_code=404, detail="投稿が見つかりません")

        # authenticated_flg=1（認証済み）の場合
        if post.get('authenticated_flg') == AuthenticatedFlag.AUTHENTICATED:
            logger.info(f"認証済み投稿を承認: post_id={post_id}")

            # 投稿ステータスをAPPROVEDに更新
            updated_post = update_post_status_crud(
                db,
                post_id,
                PostStatus.APPROVED,
                AuthenticatedFlag.AUTHENTICATED
            )

            if not updated_post:
                raise HTTPException(status_code=500, detail="投稿ステータスの更新に失敗しました")

            # 紐づく全てのメディアアセットを取得してステータスを更新
            media_assets = db.query(MediaAssets).filter(
                MediaAssets.post_id == post_id
            ).all()

            if media_assets:
                for asset in media_assets:
                    update_media_asset(db, str(asset.id), {
                        "status": MediaAssetStatus.APPROVED
                    })
                    logger.info(f"メディアアセットのステータスを更新: asset_id={asset.id}, kind={asset.kind}, status=APPROVED")
                logger.info(f"全メディアアセットのステータスを更新完了: post_id={post_id}, count={len(media_assets)}")
            else:
                logger.warning(f"メディアアセットが見つかりません: post_id={post_id}")

            db.commit()

            # Email通知を追加
            add_mail_notification_for_post(db, post_id=post_id, type="approved")
            # 投稿に対する通知を追加
            add_notification_for_post(db, updated_post, post.get('creator_user_id'), type="approved")

            # 新着投稿通知をトリガー
            trigger_batch_notification_newpost_arrival(post_id=post_id, creator_user_id=str(post.get('creator_user_id')))

            return {
                "message": "投稿を承認しました（認証済み）",
                "success": True,
                "post_id": post_id,
                "status": "approved"
            }
        else:
            # authenticated_flg=0の場合は、MediaConvert処理が必要
            # フロントエンドでtranscode_mcエンドポイントを呼ぶ必要がある
            raise HTTPException(
                status_code=400,
                detail="未認証の投稿はMediaConvert処理が必要です。transcode_mcエンドポイントを使用してください。"
            )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"投稿承認エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{post_id}")
def get_post(
    post_id: str,
    db: Session = Depends(get_db),
    # current_admin: Users = Depends(get_current_admin_user)
):
    """投稿詳細を取得"""

    post_data = get_post_and_categories_by_id(db, post_id)

    if not post_data:
        raise HTTPException(status_code=404, detail="投稿が見つかりません")

    for media_asset_id, media_asset_data in post_data['media_assets'].items():
        post_data['media_assets'][media_asset_id]['storage_key'] = resolve_media_asset_storage_key(
            media_asset_data
        )
        post_data['media_assets'][media_asset_id]['status'] = media_asset_data['status']

    return AdminPostDetailResponse(**post_data)