# app/api/endpoints/admin/message_assets.py
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from uuid import UUID

from app.db.base import get_db
from app.deps.auth import get_current_admin_user
from app.models.admins import Admins
from app.models.conversation_messages import ConversationMessages
from app.crud import message_assets_crud
from app.crud import notifications_crud, user_crud
from app.schemas.message_asset import (
    MessageAssetResponse,
    MessageAssetRejectRequest,
    AdminMessageAssetListResponse,
    AdminMessageAssetDetailResponse,
)
from app.constants.enums import MessageAssetStatus
from app.services.s3 import client as s3_client
import os

router = APIRouter()

MESSAGE_ASSETS_CDN_URL = os.getenv("MESSAGE_ASSETS_CDN_URL", "")
BASE_URL = os.getenv("CDN_BASE_URL")

@router.get("/", response_model=dict)
def get_message_assets(
    status: Optional[int] = Query(None, description="0=審査中, 1=承認済み, 2=拒否"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    メッセージアセット一覧を取得（管理者用）
    - フィルター対応
    - ページネーション対応
    - 送信者・受信者情報含む
    """
    skip = (page - 1) * page_size

    # アセット一覧と総件数を取得
    assets, total = message_assets_crud.get_message_assets_for_admin(
        db, status=status, skip=skip, limit=page_size
    )

    responses = []
    for asset in assets:
        # メッセージ情報を取得
        message = (
            db.query(ConversationMessages)
            .filter(ConversationMessages.id == asset.message_id)
            .first()
        )

        if not message:
            continue

        # 送信者・受信者の詳細情報を取得
        detail = message_assets_crud.get_message_asset_detail_for_admin(db, asset.id)
        if not detail:
            continue

        # CDN URL設定（承認済みの場合のみ）
        cdn_url = f"{BASE_URL}/{asset.storage_key}"

        # 送信者情報
        sender_profile = detail.get("sender_profile")
        sender_user_id = message.sender_user_id if message else None
        sender_username = None
        sender_profile_name = None
        sender_avatar = None
        
        if sender_profile:
            sender_username = sender_profile.username
            sender_avatar = f"{BASE_URL}/{sender_profile.avatar_url}" if sender_profile.avatar_url else None
            # profile_nameはUsersテーブルから取得
            if sender_user_id:
                sender_user = user_crud.get_user_by_id(db, sender_user_id)
                if sender_user:
                    sender_profile_name = sender_user.profile_name

        # 受信者情報
        recipient_profile = detail.get("recipient_profile")
        recipient_user_id = None
        recipient_username = None
        recipient_profile_name = None
        recipient_avatar = None
        
        if recipient_profile:
            recipient_user_id = recipient_profile.user_id
            recipient_username = recipient_profile.username
            recipient_avatar = f"{BASE_URL}/{recipient_profile.avatar_url}" if recipient_profile.avatar_url else None
            # profile_nameはUsersテーブルから取得
            recipient_user = user_crud.get_user_by_id(db, recipient_profile.user_id)
            if recipient_user:
                recipient_profile_name = recipient_user.profile_name

        responses.append(
            AdminMessageAssetListResponse(
                id=asset.id,
                message_id=asset.message_id,
                conversation_id=message.conversation_id,
                status=asset.status,
                asset_type=asset.asset_type,
                storage_key=asset.storage_key,
                cdn_url=cdn_url,
                created_at=asset.created_at,
                updated_at=asset.updated_at,
                message_text=message.body_text,
                sender_user_id=sender_user_id,
                sender_username=sender_username,
                sender_profile_name=sender_profile_name,
                sender_avatar=sender_avatar,
                recipient_user_id=recipient_user_id,
                recipient_username=recipient_username,
                recipient_profile_name=recipient_profile_name,
                recipient_avatar=recipient_avatar,
            )
        )

    return {
        "items": responses,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/{asset_id}", response_model=AdminMessageAssetDetailResponse)
def get_message_asset_detail(
    asset_id: UUID,
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    メッセージアセット詳細を取得（管理者用）
    - 送信者・受信者・メッセージ情報含む
    """
    detail = message_assets_crud.get_message_asset_detail_for_admin(db, asset_id)

    if not detail:
        raise HTTPException(status_code=404, detail="Message asset not found")

    asset = detail["asset"]
    message = detail["message"]
    sender_profile = detail["sender_profile"]
    recipient_profile = detail["recipient_profile"]

    # CDN URL設定（承認済みの場合のみ）
    cdn_url = f"{MESSAGE_ASSETS_CDN_URL}/{asset.storage_key}"

    # 送信者情報
    sender_user_id = message.sender_user_id if message else None
    sender_username = None
    sender_profile_name = None
    sender_avatar = None
    
    if sender_profile:
        sender_username = sender_profile.username
        sender_avatar = f"{BASE_URL}/{sender_profile.avatar_url}" if sender_profile.avatar_url else None
        # profile_nameはUsersテーブルから取得
        if sender_user_id:
            sender_user = user_crud.get_user_by_id(db, sender_user_id)
            if sender_user:
                sender_profile_name = sender_user.profile_name

    # 受信者情報
    recipient_user_id = None
    recipient_username = None
    recipient_profile_name = None
    recipient_avatar = None
    
    if recipient_profile:
        recipient_user_id = recipient_profile.user_id
        recipient_username = recipient_profile.username
        recipient_avatar = f"{BASE_URL}/{recipient_profile.avatar_url}" if recipient_profile.avatar_url else None
        # profile_nameはUsersテーブルから取得
        recipient_user = user_crud.get_user_by_id(db, recipient_profile.user_id)
        if recipient_user:
            recipient_profile_name = recipient_user.profile_name

    return AdminMessageAssetDetailResponse(
        id=asset.id,
        message_id=asset.message_id,
        conversation_id=message.conversation_id,
        status=asset.status,
        asset_type=asset.asset_type,
        storage_key=asset.storage_key,
        cdn_url=cdn_url,
        reject_comments=asset.reject_comments,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        message_text=message.body_text,
        message_created_at=message.created_at,
        sender_user_id=sender_user_id,
        sender_username=sender_username,
        sender_profile_name=sender_profile_name,
        sender_avatar=sender_avatar,
        recipient_user_id=recipient_user_id,
        recipient_username=recipient_username,
        recipient_profile_name=recipient_profile_name,
        recipient_avatar=recipient_avatar,
    )


@router.post("/{asset_id}/approve", response_model=MessageAssetResponse)
def approve_message_asset(
    asset_id: UUID,
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    メッセージアセットを承認（管理者用）
    """
    asset = message_assets_crud.approve_message_asset(db, asset_id)

    if not asset:
        raise HTTPException(status_code=404, detail="Message asset not found")

    # 承認済みなのでCDN URLを設定
    cdn_url = f"{MESSAGE_ASSETS_CDN_URL}/{asset.storage_key}"

    return MessageAssetResponse(
        id=asset.id,
        status=asset.status,
        asset_type=asset.asset_type,
        storage_key=asset.storage_key,
        cdn_url=cdn_url,
        reject_comments=asset.reject_comments,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


@router.post("/{asset_id}/reject", response_model=MessageAssetResponse)
def reject_message_asset(
    asset_id: UUID,
    request: MessageAssetRejectRequest,
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    メッセージアセットを拒否（管理者用）
    - 拒否理由をコメントとして保存
    - 送信者への通知を送信
    - メッセージを削除
    """
    # アセットを取得
    asset = message_assets_crud.get_message_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Message asset not found")

    # メッセージ情報を取得（通知送信のため）
    message = db.query(ConversationMessages).filter(
        ConversationMessages.id == asset.message_id
    ).first()

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    # 送信者のユーザーIDを取得
    sender_user_id = message.sender_user_id
    if not sender_user_id:
        raise HTTPException(status_code=400, detail="Message has no sender user")

    # アセットを拒否状態に更新
    asset = message_assets_crud.reject_message_asset(db, asset_id, request.reject_comments)

    # 送信者への通知を作成
    notifications_crud.add_notification_for_message_asset_rejection(
        db=db,
        user_id=sender_user_id,
        reject_comments=request.reject_comments,
    )

    # レスポンスを保存（メッセージ削除前に）
    response = MessageAssetResponse(
        id=asset.id,
        status=asset.status,
        asset_type=asset.asset_type,
        storage_key=asset.storage_key,
        cdn_url=None,  # 拒否されたのでnull
        reject_comments=asset.reject_comments,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )

    db.commit()

    return response


@router.delete("/{asset_id}")
def delete_message_asset(
    asset_id: UUID,
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    メッセージアセットを削除（管理者用）
    - データベースレコードとS3オブジェクトを削除
    """
    # アセット情報を取得
    asset = message_assets_crud.get_message_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Message asset not found")

    # S3からオブジェクトを削除
    try:
        from app.services.s3.presign import delete_object
        delete_object(resource="message-assets", key=asset.storage_key)
    except Exception as e:
        # S3削除失敗してもログに記録してDBレコードは削除
        print(f"Failed to delete S3 object: {asset.storage_key}, error: {e}")

    # DBレコードを削除
    success = message_assets_crud.delete_message_asset(db, asset_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete message asset")

    return {"status": "ok", "message": "Message asset deleted successfully"}
