# app/api/endpoints/customer/message_assets.py
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.models.conversation_messages import ConversationMessages
from app.models.conversations import Conversations
from app.models.conversation_participants import ConversationParticipants
from app.models.profiles import Profiles
from app.crud import message_assets_crud, user_crud, profile_crud
from app.schemas.message_asset import (
    UserMessageAssetResponse,
    UserMessageAssetDetailResponse,
    UserMessageAssetsListResponse,
    MessageAssetResubmitRequest,
)
from app.constants.enums import MessageAssetStatus
from app.services.s3 import client as s3_client
import os

router = APIRouter()

MESSAGE_ASSETS_CDN_URL = os.getenv("MESSAGE_ASSETS_CDN_URL", "")
BASE_URL = os.getenv("CDN_BASE_URL")


@router.get("/", response_model=UserMessageAssetsListResponse)
def get_my_message_assets(
    status: Optional[int] = Query(None, description="0=審査中, 1=承認済み, 2=拒否"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    自分が送信したメッセージアセット一覧を取得
    """
    # カウント取得（PENDING と REJECTED）
    counts = message_assets_crud.get_user_message_assets_counts(db, current_user.id)
    pending_count = counts['pending_count']
    reject_count = counts['reject_count']

    assets = message_assets_crud.get_user_message_assets(
        db, current_user.id, status, skip, limit
    )

    reject_responses = []
    pending_responses = []
    for asset in assets:
        # メッセージ情報を取得
        message = (
            db.query(ConversationMessages)
            .filter(ConversationMessages.id == asset.message_id)
            .filter(ConversationMessages.deleted_at.is_(None))
            .first()
        )

        if not message:
            continue

        # 会話情報を取得
        conversation = (
            db.query(Conversations)
            .filter(Conversations.id == message.conversation_id)
            .first()
        )

        if not conversation:
            continue

        # 相手の情報を取得
        partner_participant = (
            db.query(ConversationParticipants)
            .filter(
                ConversationParticipants.conversation_id == conversation.id,
                ConversationParticipants.user_id != current_user.id,
            )
            .first()
        )

        partner_user_id = None
        partner_username = None
        partner_profile_name = None
        partner_avatar = None

        if partner_participant:
            partner_user_id = partner_participant.user_id
            # 相手のユーザー情報とプロフィールを取得
            partner_user = user_crud.get_user_by_id(db, partner_user_id)
            if partner_user:
                partner_username = partner_user.profile_name
                partner_profile_name = partner_user.profile_name
                # プロフィールから相手のアバターを取得
                partner_profile = profile_crud.get_profile_by_user_id(db, partner_user_id)
                if partner_profile and partner_profile.avatar_url:
                    partner_avatar = f"{BASE_URL}/{partner_profile.avatar_url}"

        # CDN URL設定
        cdn_url = f"{BASE_URL}/{asset.storage_key}"

        if asset.status == MessageAssetStatus.PENDING or asset.status == MessageAssetStatus.RESUBMIT:
            pending_responses.append(
                UserMessageAssetResponse(
                    id=asset.id,
                    message_id=asset.message_id,
                    conversation_id=message.conversation_id,
                    asset_type=asset.asset_type,
                    storage_key=asset.storage_key,
                    cdn_url=cdn_url,
                    reject_comments=asset.reject_comments,
                    created_at=asset.created_at,
                    updated_at=asset.updated_at,
                    message_text=message.body_text,
                    partner_user_id=partner_user_id,
                    partner_username=partner_username,
                    partner_profile_name=partner_profile_name,
                    partner_avatar=partner_avatar,
                )
            )
        elif asset.status == MessageAssetStatus.REJECTED:
            reject_responses.append(
                UserMessageAssetResponse(
                    id=asset.id,
                    message_id=asset.message_id,
                    conversation_id=message.conversation_id,
                    asset_type=asset.asset_type,
                    storage_key=asset.storage_key,
                    cdn_url=cdn_url,
                    reject_comments=asset.reject_comments,
                    created_at=asset.created_at,
                    updated_at=asset.updated_at,
                    message_text=message.body_text,
                    partner_user_id=partner_user_id,
                    partner_username=partner_username,
                    partner_profile_name=partner_profile_name,
                    partner_avatar=partner_avatar,
                )
            )


    return UserMessageAssetsListResponse(
        pending_message_assets=pending_responses,
        reject_message_assets=reject_responses,
        pending_count=pending_count,
        reject_count=reject_count,
    )


@router.get("/{asset_id}", response_model=UserMessageAssetDetailResponse)
def get_my_message_asset_detail(
    asset_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    自分が送信したメッセージアセットの詳細を取得
    """
    # アセットを取得
    asset = message_assets_crud.get_message_asset_by_id(db, asset_id)

    if not asset:
        raise HTTPException(status_code=404, detail="Message asset not found")

    # メッセージ情報を取得
    message = (
        db.query(ConversationMessages)
        .filter(ConversationMessages.id == asset.message_id)
        .first()
    )

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    # 自分が送信したメッセージかチェック
    if message.sender_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # 会話情報を取得
    conversation = (
        db.query(Conversations)
        .filter(Conversations.id == message.conversation_id)
        .first()
    )

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 相手の情報を取得
    partner_participant = (
        db.query(ConversationParticipants)
        .filter(
            ConversationParticipants.conversation_id == conversation.id,
            ConversationParticipants.user_id != current_user.id,
        )
        .first()
    )

    partner_user_id = None
    partner_username = None
    partner_profile_name = None
    partner_avatar = None

    if partner_participant:
        partner_user_id = partner_participant.user_id
        # 相手のユーザー情報とプロフィールを取得
        partner_user = user_crud.get_user_by_id(db, partner_user_id)
        if partner_user:
            partner_username = partner_user.profile_name
            partner_profile_name = partner_user.profile_name
            # プロフィールから相手のアバターを取得
            partner_profile = profile_crud.get_profile_by_user_id(db, partner_user_id)
            if partner_profile and partner_profile.avatar_url:
                partner_avatar = f"{BASE_URL}/{partner_profile.avatar_url}"

    # CDN URL設定（承認済みの場合のみ）
    cdn_url = f"{MESSAGE_ASSETS_CDN_URL}/{asset.storage_key}"

    return UserMessageAssetDetailResponse(
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
        partner_user_id=partner_user_id,
        partner_username=partner_username,
        partner_profile_name=partner_profile_name,
        partner_avatar=partner_avatar,
    )


@router.put("/{asset_id}/resubmit", response_model=UserMessageAssetDetailResponse)
def resubmit_message_asset(
    asset_id: UUID,
    request: MessageAssetResubmitRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    拒否されたメッセージアセットを再申請
    - 古いS3ファイルを削除
    - 新しいアセット情報で更新
    - ステータスを再申請（RESUBMIT=3）に変更
    """
    # アセットを取得
    asset = message_assets_crud.get_message_asset_by_id(db, asset_id)

    if not asset:
        raise HTTPException(status_code=404, detail="Message asset not found")

    # メッセージ情報を取得
    message = (
        db.query(ConversationMessages)
        .filter(ConversationMessages.id == asset.message_id)
        .first()
    )

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    # 自分が送信したメッセージかチェック
    if message.sender_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # ステータスが拒否（REJECTED=2）でない場合はエラー
    if asset.status != MessageAssetStatus.REJECTED:
        raise HTTPException(
            status_code=400,
            detail="Only rejected assets can be resubmitted"
        )

    # 古いS3ファイルを削除
    try:
        from app.services.s3.presign import delete_object
        delete_object(resource="message-assets", key=asset.storage_key)
    except Exception as e:
        # S3削除失敗してもログに記録してDB更新は続行
        print(f"Failed to delete old S3 object: {asset.storage_key}, error: {e}")

    # アセットを再申請
    updated_asset = message_assets_crud.resubmit_message_asset(
        db=db,
        asset_id=asset_id,
        new_storage_key=request.asset_storage_key,
        new_asset_type=request.asset_type,
        message_text=request.message_text,
    )

    if not updated_asset:
        raise HTTPException(status_code=500, detail="Failed to resubmit message asset")

    # 会話情報を取得
    conversation = (
        db.query(Conversations)
        .filter(Conversations.id == message.conversation_id)
        .first()
    )

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 相手の情報を取得
    partner_participant = (
        db.query(ConversationParticipants)
        .filter(
            ConversationParticipants.conversation_id == conversation.id,
            ConversationParticipants.user_id != current_user.id,
        )
        .first()
    )

    partner_user_id = None
    partner_username = None
    partner_profile_name = None
    partner_avatar = None

    if partner_participant:
        partner_user_id = partner_participant.user_id
        partner_user = user_crud.get_user_by_id(db, partner_user_id)
        if partner_user:
            partner_username = partner_user.profile_name
            partner_profile_name = partner_user.profile_name
            partner_profile = profile_crud.get_profile_by_user_id(db, partner_user_id)
            if partner_profile and partner_profile.avatar_url:
                partner_avatar = f"{BASE_URL}/{partner_profile.avatar_url}"

    # CDN URL（再申請後は審査中なのでnull）
    cdn_url = None

    return UserMessageAssetDetailResponse(
        id=updated_asset.id,
        message_id=updated_asset.message_id,
        conversation_id=message.conversation_id,
        status=updated_asset.status,
        asset_type=updated_asset.asset_type,
        storage_key=updated_asset.storage_key,
        cdn_url=cdn_url,
        reject_comments=updated_asset.reject_comments,
        created_at=updated_asset.created_at,
        updated_at=updated_asset.updated_at,
        message_text=message.body_text,
        message_created_at=message.created_at,
        partner_user_id=partner_user_id,
        partner_username=partner_username,
        partner_profile_name=partner_profile_name,
        partner_avatar=partner_avatar,
    )
