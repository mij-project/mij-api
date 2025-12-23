# app/api/endpoints/customer/message_assets.py
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from app.services.s3.presign import delete_object
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
    PresignedUrlRequest,
    PresignedUrlResponse,
)
import logging
from app.constants.enums import MessageAssetStatus, ConversationMessageType, MessageAssetType, ConversationMessageStatus
from app.services.s3 import keygen, presign
import os

router = APIRouter()
logger = logging.getLogger(__name__)

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
    # カウント取得（PENDING と REJECTED、group_byでグループ化）
    counts = message_assets_crud.get_user_message_assets_counts(db, current_user.id)
    pending_count = counts['pending_count']
    reject_count = counts['reject_count']
    reserved_count = counts['reserved_count']

    # グループ化されたアセット情報を取得
    grouped_data = message_assets_crud.get_user_message_assets(
        db, current_user.id, status, skip, limit
    )

    reject_responses = []
    pending_responses = []
    reserved_responses = []
    for group in grouped_data:
        asset = group["asset"]
        message = group["message"]
        
        if not message or not asset:
            continue

        # メッセージが削除されていないか確認
        if message.deleted_at is not None:
            continue

        # 会話情報を取得
        conversation = (
            db.query(Conversations)
            .filter(Conversations.id == message.conversation_id)
            .first()
        )

        if not conversation:
            continue

        # 相手の情報を取得（一斉送信メッセージ（type=3）の場合は不要）
        partner_user_id = None
        partner_username = None
        partner_profile_name = None
        partner_avatar = None

        if message.type != ConversationMessageType.BULK:
            # 一斉送信メッセージ以外の場合のみパートナー情報を取得
            partner_participant = (
                db.query(ConversationParticipants)
                .filter(
                    ConversationParticipants.conversation_id == conversation.id,
                    ConversationParticipants.user_id != current_user.id,
                )
                .first()
            )

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

        # 予約送信（status=2）かつ審査中（PENDINGまたはRESUBMIT）の場合はpending_responsesに入れる
        is_reserved = message.status == ConversationMessageStatus.PENDING
        is_pending_asset = asset.status == MessageAssetStatus.PENDING or asset.status == MessageAssetStatus.RESUBMIT

        if is_reserved and is_pending_asset:
            # 予約送信で審査中の場合
            pending_responses.append(
                UserMessageAssetResponse(
                    id=asset.id,
                    message_id=asset.message_id,
                    type=message.type,
                    group_by=asset.group_by,
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
        elif is_reserved and not is_pending_asset:
            # 予約送信で審査中でない場合
            reserved_responses.append(
                UserMessageAssetResponse(
                    id=asset.id,
                    message_id=asset.message_id,
                    type=message.type,
                    group_by=asset.group_by,
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
        elif asset.status == MessageAssetStatus.PENDING or asset.status == MessageAssetStatus.RESUBMIT:
            # 通常の審査中（予約送信でない）
            pending_responses.append(
                UserMessageAssetResponse(
                    id=asset.id,
                    message_id=asset.message_id,
                    type=message.type,
                    group_by=asset.group_by,
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
            # 拒否されたもの
            reject_responses.append(
                UserMessageAssetResponse(
                    id=asset.id,
                    message_id=asset.message_id,
                    type=message.type,
                    group_by=asset.group_by,
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
        reserved_message_assets=reserved_responses,
        pending_count=pending_count,
        reject_count=reject_count,
        reserved_count=reserved_count,
    )


@router.get("/{group_by}", response_model=UserMessageAssetDetailResponse)
def get_my_message_asset_detail(
    group_by: str,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    自分が送信したメッセージアセットの詳細を取得（group_byでグループ化）
    - message.typeがDM（個別メッセージ）の場合は送信先情報を取得
    """
    # group_byでグループ化されたアセット情報を取得
    detail = message_assets_crud.get_message_asset_detail_by_group_by_for_user(
        db, group_by, current_user.id
    )

    if not detail:
        raise HTTPException(status_code=404, detail="Message asset not found")

    asset = detail["asset"]
    message = detail["message"]
    conversation = detail["conversation"]

    # 相手の情報を取得（DM（type=1）の場合のみ）
    partner_user_id = None
    partner_username = None
    partner_profile_name = None
    partner_avatar = None

    if message.type == ConversationMessageType.USER:
        # 個別メッセージ（DM）の場合のみ送信先情報を取得
        partner_participant = (
            db.query(ConversationParticipants)
            .filter(
                ConversationParticipants.conversation_id == conversation.id,
                ConversationParticipants.user_id != current_user.id,
            )
            .first()
        )

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

    # conversation_messageのステータスを取得（Noneの場合はデフォルト値1を設定）
    # status = 3 の場合が予約中を表す
    message_status = message.status if message.status is not None else ConversationMessageStatus.ACTIVE

    return UserMessageAssetDetailResponse(
        id=asset.id,
        message_id=asset.message_id,
        group_by=asset.group_by,
        type=message.type,
        conversation_id=message.conversation_id,
        status=asset.status,
        message_status=message_status,  # conversation_messageのステータス（1=送信済み, 3=予約中など）
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


@router.post("/{group_by}/upload-url", response_model=PresignedUrlResponse)
def get_message_asset_upload_url_by_group_by(
    group_by: str,
    request: PresignedUrlRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    group_byベースでメッセージアセット用のPresigned URL取得
    - ユーザーがこのgroup_byのアセットの所有者であることを確認
    - 画像または動画のアップロード用URL生成
    """
    try:
        # group_byでアセット詳細を取得
        detail = message_assets_crud.get_message_asset_detail_by_group_by_for_user(
            db, group_by, current_user.id
        )

        if not detail:
            raise HTTPException(status_code=404, detail="Message asset not found or access denied")

        # ファイルタイプの検証
        allowed_image_types = ["image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"]
        allowed_video_types = ["video/mp4", "video/quicktime"]

        if request.asset_type == 1:  # 画像
            if request.content_type not in allowed_image_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid image type. Allowed: {', '.join(allowed_image_types)}"
                )
        elif request.asset_type == 2:  # 動画
            if request.content_type not in allowed_video_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid video type. Allowed: {', '.join(allowed_video_types)}"
                )
        else:
            raise HTTPException(status_code=400, detail="Invalid asset type")

        # Presigned URL生成
        asset_type_str = "image" if request.asset_type == MessageAssetType.IMAGE else "video"

        try:
            conversation_id = detail["conversation"].id
            message_id = detail["message"].id   
            storage_key = keygen.message_asset_key(
                conversation_id=str(conversation_id),
                message_id=str(message_id),
                asset_type=asset_type_str,
                ext=request.file_extension.lower(),
            )

            # Presigned URL生成
            result = presign.presign_put(
                resource="message-assets",
                key=storage_key,
                content_type=request.content_type,
                expires_in=3600,  # 1時間
            )

            return PresignedUrlResponse(
                storage_key=result["key"],
                upload_url=result["upload_url"],
                expires_in=result["expires_in"],
                required_headers=result["required_headers"],
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to generate upload URL: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")


@router.put("/{group_by}/resubmit", response_model=UserMessageAssetDetailResponse)
def resubmit_message_asset_by_group_by(
    group_by: str,
    request: MessageAssetResubmitRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    拒否されたメッセージアセットをgroup_byで一括再申請
    - 古いS3ファイルを削除
    - 同じgroup_byの全アセットを一括更新
    - ステータスを再申請（RESUBMIT=3）に変更
    """
    # group_byでアセット詳細を取得（権限チェック）
    detail = message_assets_crud.get_message_asset_detail_by_group_by_for_user(
        db, group_by, current_user.id
    )

    if not detail:
        raise HTTPException(status_code=404, detail="Message asset not found")

    asset = detail["asset"]
    message = detail["message"]
    conversation = detail["conversation"]

    # ステータスが拒否（REJECTED=2）でない場合はエラー
    if asset.status != MessageAssetStatus.REJECTED:
        raise HTTPException(
            status_code=400,
            detail="Only rejected assets can be resubmitted"
        )

    # 古いS3ファイルを削除
    try:
        delete_object(resource="message-assets", key=asset.storage_key)
    except Exception as e:
        # S3削除失敗してもログに記録してDB更新は続行
        print(f"Failed to delete old S3 object: {asset.storage_key}, error: {e}")

    # group_byで同じグループの全アセットを一括再申請
    updated_asset = message_assets_crud.resubmit_message_asset_by_group_by(
        db=db,
        group_by=group_by,
        user_id=current_user.id,
        new_storage_key=request.asset_storage_key,
        new_asset_type=request.asset_type,
        message_text=request.message_text,
    )

    if not updated_asset:
        raise HTTPException(status_code=500, detail="Failed to resubmit message asset")

    # メッセージ情報を再取得（本文が更新された可能性があるため）
    message = (
        db.query(ConversationMessages)
        .filter(ConversationMessages.id == updated_asset.message_id)
        .first()
    )

    # 相手の情報を取得（DM（type=1）の場合のみ）
    partner_user_id = None
    partner_username = None
    partner_profile_name = None
    partner_avatar = None

    if message.type == ConversationMessageType.USER:
        partner_participant = (
            db.query(ConversationParticipants)
            .filter(
                ConversationParticipants.conversation_id == conversation.id,
                ConversationParticipants.user_id != current_user.id,
            )
            .first()
        )

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
        group_by=updated_asset.group_by,
        type=message.type,
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
