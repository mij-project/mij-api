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
from app.models.message_assets import MessageAssets
from app.models.profiles import Profiles
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
from app.services.email.send_email import send_message_content_approval_email, send_message_content_rejection_email
from app.api.commons.function import CommonFunction
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

MESSAGE_ASSETS_CDN_URL = os.getenv("MESSAGE_ASSETS_CDN_URL", "")
BASE_URL = os.getenv("CDN_BASE_URL")

@router.get("", response_model=dict)
def get_message_assets(
    status: Optional[int] = Query(None, description="0=審査中, 1=承認済み, 2=拒否"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    メッセージアセット一覧を取得（管理者用）
    - group_byでグループ化（1グループ = 1レスポンス）
    - フィルター対応
    - ページネーション対応
    - 送信者情報含む（受信者情報は含まない）
    """
    skip = (page - 1) * page_size

    # グループ化されたアセット一覧と総グループ数を取得
    grouped_data, total = message_assets_crud.get_message_assets_for_admin(
        db, status=status, skip=skip, limit=page_size
    )

    responses = []
    for group in grouped_data:
        message = group["message"]
        asset = group["asset"]
        
        if not message or not asset:
            continue

        # 送信者の詳細情報を取得
        detail = message_assets_crud.get_message_asset_detail_for_admin(db, asset.id)
        if not detail:
            continue

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

        # CDN URL設定（承認済みの場合のみ）
        cdn_url = f"{BASE_URL}/{asset.storage_key}"

        # グループ単位でレスポンスを作成（代表アセット1件のみ）
        responses.append(
            AdminMessageAssetListResponse(
                id=asset.id,
                group_by=group["group_by"],
                type=message.type,
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
            )
        )

    return {
        "items": responses,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/{group_by}", response_model=AdminMessageAssetDetailResponse)
def get_message_asset_detail(
    group_by: str,
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    メッセージアセット詳細を取得（管理者用）
    - group_byでグループ化されたアセット情報を取得
    - 送信者・メッセージ情報含む（受信者情報は含まない）
    """
    detail = message_assets_crud.get_message_asset_detail_by_group_by_for_admin(db, group_by)

    if not detail:
        raise HTTPException(status_code=404, detail="Message asset not found")

    asset = detail["asset"]
    message = detail["message"]
    sender_profile = detail["sender_profile"]

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

    return AdminMessageAssetDetailResponse(
        id=asset.id,
        group_by=message.group_by,
        type=message.type,
        status=asset.status,
        asset_type=asset.asset_type,
        storage_key=asset.storage_key,
        cdn_url=cdn_url,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        message_text=message.body_text,
        message_created_at=message.created_at,
        sender_user_id=sender_user_id,
        sender_username=sender_username,
        sender_profile_name=sender_profile_name,
        sender_avatar=sender_avatar,
    )


@router.post("/{group_by}/approve", response_model=MessageAssetResponse)
def approve_message_asset(
    group_by: str,
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    メッセージアセットを承認（管理者用）
    - group_byでグループ化されたすべてのアセットを承認
    - 送信者に通知とメールを送信
    """
    asset = message_assets_crud.approve_message_asset_by_group_by(db, group_by)

    if not asset:
        raise HTTPException(status_code=404, detail="Message asset not found")

    # メッセージ情報を取得（送信者ID取得のため）
    message = db.query(ConversationMessages).filter(
        ConversationMessages.id == asset.message_id
    ).first()

    if message and message.sender_user_id:
        sender_user_id = message.sender_user_id

        # 通知可否判定
        need_to_send_notification = CommonFunction.get_user_need_to_send_notification(
            db, sender_user_id, "messageContentApprove"
        )

        if need_to_send_notification:
            # ユーザー情報を取得
            sender_user = user_crud.get_user_by_id(db, sender_user_id)

            # アプリ内通知を作成
            notifications_crud.add_notification_for_message_content_approval(
                db=db,
                user_id=sender_user_id,
            )

            # メール送信
            if sender_user and sender_user.email:
                try:
                    send_message_content_approval_email(
                        to=sender_user.email,
                        display_name=sender_user.profile_name or "User",
                        redirect_url=f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/message/conversation-list",
                    )
                    logger.info(f"Approval email sent to {sender_user.email} for message asset {asset.id}")
                except Exception as e:
                    logger.error(f"Failed to send approval email to {sender_user.email}: {e}")

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


@router.post("/{group_by}/reject", response_model=MessageAssetResponse)
def reject_message_asset(
    group_by: str,
    request: MessageAssetRejectRequest,
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    メッセージアセットを拒否（管理者用）
    - group_byでグループ化されたすべてのアセットを拒否
    - 拒否理由をコメントとして保存
    - 送信者への通知とメール送信
    """
    # 代表的なアセットを取得（メッセージ情報取得のため）
    # ConversationMessages.group_byでフィルタリング
    asset = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.group_by == group_by)
        .order_by(MessageAssets.created_at.asc())
        .first()
    )

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

    # アセットを拒否状態に更新（同じgroup_byのすべてのアセット）
    asset = message_assets_crud.reject_message_asset_by_group_by(
        db, group_by, request.reject_comments
    )

    if not asset:
        raise HTTPException(status_code=404, detail="Failed to reject message asset")

    # 通知可否判定
    need_to_send_notification = CommonFunction.get_user_need_to_send_notification(
        db, sender_user_id, "messageContentApprove"
    )

    if need_to_send_notification:
        # ユーザー情報を取得
        sender_user = user_crud.get_user_by_id(db, sender_user_id)

        # アプリ内通知を作成
        notifications_crud.add_notification_for_message_asset_rejection(
            db=db,
            user_id=sender_user_id,
            reject_comments=request.reject_comments,
            group_by=group_by,
        )

        # メール送信
        if sender_user and sender_user.email:
            try:
                send_message_content_rejection_email(
                    to=sender_user.email,
                    display_name=sender_user.profile_name or "User",
                    reject_comments=request.reject_comments,
                    group_by=group_by,
                )
                logger.info(f"Rejection email sent to {sender_user.email} for message asset {asset.id}")
            except Exception as e:
                logger.error(f"Failed to send rejection email to {sender_user.email}: {e}")

    # レスポンスを保存
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
