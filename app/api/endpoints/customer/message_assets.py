# app/api/endpoints/customer/message_assets.py
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Tuple
from uuid import UUID
from datetime import datetime, timezone, timedelta
import json
from app.services.s3.presign import delete_object
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.models.conversation_messages import ConversationMessages
from app.models.conversations import Conversations
from app.models.conversation_participants import ConversationParticipants
from app.models.reservation_message import ReservationMessage
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
from app.services.s3.client import scheduler_client
import os

router = APIRouter()
logger = logging.getLogger(__name__)

MESSAGE_ASSETS_CDN_URL = os.getenv("MESSAGE_ASSETS_CDN_URL", "")
BASE_URL = os.getenv("CDN_BASE_URL")


def _update_ecs_task_schedule(schedule_name: str, scheduled_at: datetime, group_by: str, sender_user_id: UUID) -> dict:
    """
    EventBridge Schedulerのスケジュールを更新

    Args:
        schedule_name: 既存のスケジュール名
        scheduled_at: 新しい予約送信日時（UTC）
        group_by: グループ化キー
        sender_user_id: 送信者ユーザーID

    Returns:
        更新結果
    """
    try:
        scheduler = scheduler_client()

        # scheduled_atをJST (UTC+9) に変換
        jst_timezone = timezone(timedelta(hours=9))
        scheduled_at_jst = scheduled_at.astimezone(jst_timezone) if scheduled_at.tzinfo else scheduled_at.replace(tzinfo=timezone.utc).astimezone(jst_timezone)

        # at() 式には JST時刻を渡す
        schedule_expression = f"at({scheduled_at_jst.strftime('%Y-%m-%dT%H:%M:%S')})"

        logger.info(f"Updating schedule: {schedule_name} to {scheduled_at_jst.strftime('%Y-%m-%d %H:%M:%S %Z')} JST")

        # ネットワーク設定
        ECS_SUBNETS = (
            os.environ.get("ECS_SUBNETS", "").split(",")
            if os.environ.get("ECS_SUBNETS")
            else []
        )
        ECS_SECURITY_GROUPS = (
            os.environ.get("ECS_SECURITY_GROUPS", "").split(",")
            if os.environ.get("ECS_SECURITY_GROUPS")
            else []
        )
        ECS_ASSIGN_PUBLIC_IP = os.environ.get("ECS_ASSIGN_PUBLIC_IP", "ENABLED")
        network_configuration = {
            "awsvpcConfiguration": {
                "Subnets": ECS_SUBNETS,
                "SecurityGroups": ECS_SECURITY_GROUPS,
                "AssignPublicIp": ECS_ASSIGN_PUBLIC_IP,
            }
        }

        task_definition = os.environ["ECS_SEND_RESERVATION_MESSAGE_TASK_ARN"]

        # ECS RunTask の overrides
        overrides = {
            "containerOverrides": [
                {
                    "name": os.environ["ECS_SEND_RESERVATION_MESSAGE_CONTAINER"],
                    "environment": [
                        {"name": "GROUP_BY", "value": str(group_by)},
                        {"name": "SENDER_USER_ID", "value": str(sender_user_id)},
                    ],
                }
            ]
        }

        # スケジュールを更新
        scheduler.update_schedule(
            Name=schedule_name,
            ScheduleExpression=schedule_expression,
            ScheduleExpressionTimezone="Asia/Tokyo",
            FlexibleTimeWindow={"Mode": "OFF"},
            State="ENABLED",
            Target={
                "Arn": os.environ["ECS_SEND_RESERVATION_MESSAGE_CLUSTER_ARN"],
                "RoleArn": os.environ["SCHEDULER_ROLE_ARN"],
                "EcsParameters": {
                    "TaskDefinitionArn": task_definition,
                    "LaunchType": "FARGATE",
                    "NetworkConfiguration": network_configuration,
                },
                "Input": json.dumps(overrides),
            },
        )

        logger.info(f"Schedule updated successfully: {schedule_name}")
        return {
            "schedule_name": schedule_name,
            "result": True,
        }

    except Exception as e:
        logger.error(f"Failed to update schedule {schedule_name}: {e}")
        raise


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
    processed_reserved_group_bys = set()  # 既に処理した予約メッセージのgroup_byを記録

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

        # アセットのステータスに基づいて分類
        is_pending_asset = asset.status == MessageAssetStatus.PENDING or asset.status == MessageAssetStatus.RESUBMIT
        is_approved_asset = asset.status == MessageAssetStatus.APPROVED
        is_rejected_asset = asset.status == MessageAssetStatus.REJECTED
        is_scheduled = message.scheduled_at is not None

        # 審査中（PENDING または RESUBMIT）の場合は「審査中」タブに表示（予約送信の有無は関係ない）
        if is_pending_asset:
            pending_responses.append(
                UserMessageAssetResponse(
                    id=asset.id,
                    message_id=asset.message_id,
                    type=message.type,
                    group_by=message.group_by if message.group_by else str(message.id),
                    conversation_id=message.conversation_id,
                    asset_type=asset.asset_type,
                    storage_key=asset.storage_key,
                    cdn_url=cdn_url,
                    reject_comments=asset.reject_comments,
                    created_at=asset.created_at,
                    updated_at=asset.updated_at,
                    message_text=message.body_text,
                    scheduled_at=message.scheduled_at if is_scheduled else None,
                    partner_user_id=partner_user_id,
                    partner_username=partner_username,
                    partner_profile_name=partner_profile_name,
                    partner_avatar=partner_avatar,
                )
            )
        # 承認済み（APPROVED）で予約送信が設定されている場合は「予約中」タブに表示
        elif is_approved_asset and is_scheduled:
            reserved_responses.append(
                UserMessageAssetResponse(
                    id=asset.id,
                    message_id=asset.message_id,
                    type=message.type,
                    group_by=message.group_by if message.group_by else str(message.id),
                    conversation_id=message.conversation_id,
                    asset_type=asset.asset_type,
                    storage_key=asset.storage_key,
                    cdn_url=cdn_url,
                    reject_comments=asset.reject_comments,
                    created_at=asset.created_at,
                    updated_at=asset.updated_at,
                    message_text=message.body_text,
                    scheduled_at=message.scheduled_at,
                    partner_user_id=partner_user_id,
                    partner_username=partner_username,
                    partner_profile_name=partner_profile_name,
                    partner_avatar=partner_avatar,
                )
            )
            processed_reserved_group_bys.add(message.group_by if message.group_by else str(message.id))
        # 拒否（REJECTED）の場合は「拒否」タブに表示
        elif is_rejected_asset:
            reject_responses.append(
                UserMessageAssetResponse(
                    id=asset.id,
                    message_id=asset.message_id,
                    type=message.type,
                    group_by=message.group_by if message.group_by else str(message.id),
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

    # 予約送信メッセージを別途取得（テキストのみ含む、既に処理済みのものは除外）
    reserved_messages = message_assets_crud.get_reserved_bulk_messages(
        db, current_user.id, skip, limit
    )

    for reserved_msg_data in reserved_messages:
        message = reserved_msg_data["message"]
        asset = reserved_msg_data.get("asset")  # assetがない場合はNone
        recipient_count = reserved_msg_data.get("recipient_count", 1)  # 送信先数

        if not message or message.deleted_at is not None:
            continue

        # assetがある場合、既に処理済みならスキップ
        message_group_by = message.group_by if message.group_by else str(message.id)
        if asset and message_group_by in processed_reserved_group_bys:
            continue

        # assetがない場合のgroup_by
        group_by = message_group_by

        # CDN URLを設定（assetがある場合のみ）
        cdn_url = f"{BASE_URL}/{asset.storage_key}" if asset else None

        reserved_responses.append(
            UserMessageAssetResponse(
                id=asset.id if asset else message.id,  # assetがない場合はmessage.idを使用
                message_id=message.id,
                type=message.type,
                group_by=group_by,
                conversation_id=message.conversation_id,
                asset_type=asset.asset_type if asset else None,
                storage_key=asset.storage_key if asset else None,
                cdn_url=cdn_url,
                reject_comments=asset.reject_comments if asset else None,
                created_at=asset.created_at if asset else message.created_at,
                updated_at=asset.updated_at if asset else message.updated_at,
                message_text=message.body_text,
                scheduled_at=message.scheduled_at,  # 予約送信時刻
                recipient_count=recipient_count,  # 送信先数
                partner_user_id=None,  # 一斉送信なので不要
                partner_username=None,
                partner_profile_name=None,
                partner_avatar=None,
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

    asset = detail.get("asset")  # Noneの可能性あり
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

    # CDN URL設定（assetがある場合のみ）
    cdn_url = f"{MESSAGE_ASSETS_CDN_URL}/{asset.storage_key}" if asset else None

    # conversation_messageのステータスを取得（Noneの場合はデフォルト値1を設定）
    message_status = message.status if message.status is not None else ConversationMessageStatus.ACTIVE

    return UserMessageAssetDetailResponse(
        id=asset.id if asset else message.id,
        message_id=message.id,
        group_by=message.group_by if message.group_by else str(message.id),
        type=message.type,
        conversation_id=message.conversation_id,
        status=asset.status if asset else MessageAssetStatus.APPROVED,  # assetがない場合は承認済みとみなす
        message_status=message_status,
        asset_type=asset.asset_type if asset else None,
        storage_key=asset.storage_key if asset else None,
        cdn_url=cdn_url,
        reject_comments=asset.reject_comments if asset else None,
        created_at=asset.created_at if asset else message.created_at,
        updated_at=asset.updated_at if asset else message.updated_at,
        message_text=message.body_text,
        message_created_at=message.created_at,
        scheduled_at=message.scheduled_at,  # 予約送信時刻
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

@router.delete("/{group_by}")
def delete_message_asset_by_group_by(
    group_by: str,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    予約中のメッセージを削除（物理削除）
    - conversation_messages (group_byに紐づく全レコード)
    - message_assets (group_byに紐づく全レコード + S3ファイル)
    - reservation_message (group_byに紐づくレコード + EventBridge Schedule)
    """

    try:
        # 1. CRUD関数を使用してDB削除とreservation_message/storage_keysを取得
        reservation_message, storage_keys = message_assets_crud.delete_reserved_message_by_group_by(
            db, group_by, current_user.id
        )

        # 2. EventBridge Scheduleの削除
        if reservation_message and reservation_message.event_bridge_name:
            try:
                scheduler = scheduler_client()
                scheduler.delete_schedule(
                    Name=reservation_message.event_bridge_name
                )
                logger.info(f"EventBridge schedule deleted: {reservation_message.event_bridge_name}")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to delete EventBridge schedule: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"EventBridge削除に失敗しました: {str(e)}"
                )

        # 3. S3ファイルの削除
        for storage_key in storage_keys:
            try:
                delete_object(resource="message-assets", key=storage_key)
                logger.info(f"S3 file deleted: {storage_key}")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to delete S3 file: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"S3ファイル削除に失敗しました: {str(e)}"
                )

        # 4. コミット
        db.commit()
        logger.info(f"Reserved message deleted successfully: {group_by}")

        return {"message": "Reserved message deleted successfully"}

    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete reserved message: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"予約メッセージ削除に失敗しました: {str(e)}"
        )

def _update_reservation_schedule(
    db: Session,
    group_by: str,
    scheduled_at: datetime,
    sender_user_id: UUID
) -> None:
    """
    予約送信スケジュールを更新

    Args:
        db: データベースセッション
        group_by: グループ化キー
        scheduled_at: 新しい予約送信日時
        sender_user_id: 送信者ユーザーID

    Raises:
        HTTPException: スケジュール更新に失敗した場合
    """
    
    reservation_message = (
        db.query(ReservationMessage)
        .filter(ReservationMessage.group_by == group_by)
        .first()
    )

    if not reservation_message:
        return

    try:
        _update_ecs_task_schedule(
            schedule_name=reservation_message.event_bridge_name,
            scheduled_at=scheduled_at,
            group_by=group_by,
            sender_user_id=sender_user_id
        )

        reservation_message.scheduled_at = scheduled_at

        db.query(ConversationMessages).filter(
            ConversationMessages.group_by == group_by,
            ConversationMessages.sender_user_id == sender_user_id
        ).update({"scheduled_at": scheduled_at})

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update EventBridge schedule: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"予約送信スケジュールの更新に失敗しました: {str(e)}"
        )


def _delete_old_asset_file(asset) -> None:
    """
    古いS3ファイルを削除

    Args:
        asset: 削除対象のアセット（Noneの場合は何もしない）
    """
    if not asset:
        return

    try:
        delete_object(resource="message-assets", key=asset.storage_key)
    except Exception as e:
        logger.warning(f"Failed to delete old S3 object: {asset.storage_key}, error: {e}")


def _get_message_for_response(
    db: Session,
    updated_asset,
    group_by: str,
    user_id: UUID,
    is_new_file_selected: bool
) -> ConversationMessages:
    """
    レスポンス用のメッセージ情報を取得

    Args:
        db: データベースセッション
        updated_asset: 更新されたアセット（Noneの可能性あり）
        group_by: グループ化キー
        user_id: ユーザーID
        is_new_file_selected: 新しいファイルが選択されたかどうか

    Returns:
        メッセージ情報

    Raises:
        HTTPException: メッセージが見つからない場合
    """
    if updated_asset:
        message = (
            db.query(ConversationMessages)
            .filter(ConversationMessages.id == updated_asset.message_id)
            .first()
        )
        if message:
            return message

    if is_new_file_selected:
        raise HTTPException(status_code=500, detail="Failed to resubmit message asset")

    message = (
        db.query(ConversationMessages)
        .filter(
            ConversationMessages.group_by == group_by,
            ConversationMessages.sender_user_id == user_id
        )
        .order_by(ConversationMessages.created_at.asc())
        .first()
    )

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    return message


def _get_partner_info(
    db: Session,
    message: ConversationMessages,
    conversation: Conversations,
    current_user_id: UUID
) -> Tuple[Optional[UUID], Optional[str], Optional[str], Optional[str]]:
    """
    パートナー情報を取得（DMの場合のみ）

    Args:
        db: データベースセッション
        message: メッセージ情報
        conversation: 会話情報
        current_user_id: 現在のユーザーID

    Returns:
        (partner_user_id, partner_username, partner_profile_name, partner_avatar)
    """
    if message.type != ConversationMessageType.USER:
        return None, None, None, None

    partner_participant = (
        db.query(ConversationParticipants)
        .filter(
            ConversationParticipants.conversation_id == conversation.id,
            ConversationParticipants.user_id != current_user_id,
        )
        .first()
    )

    if not partner_participant:
        return None, None, None, None

    partner_user_id = partner_participant.user_id
    partner_user = user_crud.get_user_by_id(db, partner_user_id)
    
    if not partner_user:
        return partner_user_id, None, None, None

    partner_profile = profile_crud.get_profile_by_user_id(db, partner_user_id)
    partner_avatar = (
        f"{BASE_URL}/{partner_profile.avatar_url}"
        if partner_profile and partner_profile.avatar_url
        else None
    )

    return (
        partner_user_id,
        partner_user.profile_name,
        partner_user.profile_name,
        partner_avatar
    )


def _build_resubmit_response(
    updated_asset,
    message: ConversationMessages,
    partner_user_id: Optional[UUID],
    partner_username: Optional[str],
    partner_profile_name: Optional[str],
    partner_avatar: Optional[str]
) -> UserMessageAssetDetailResponse:
    """
    再申請レスポンスを構築

    Args:
        updated_asset: 更新されたアセット（Noneの可能性あり）
        message: メッセージ情報
        partner_user_id: パートナーユーザーID
        partner_username: パートナーユーザー名
        partner_profile_name: パートナープロフィール名
        partner_avatar: パートナーアバターURL

    Returns:
        レスポンスオブジェクト
    """
    message_status = (
        message.status
        if message.status is not None
        else ConversationMessageStatus.ACTIVE
    )

    return UserMessageAssetDetailResponse(
        id=updated_asset.id if updated_asset else message.id,
        message_id=updated_asset.message_id if updated_asset else message.id,
        group_by=message.group_by if message.group_by else str(message.id),
        type=message.type,
        conversation_id=message.conversation_id,
        status=updated_asset.status if updated_asset else MessageAssetStatus.APPROVED,
        message_status=message_status,
        asset_type=updated_asset.asset_type if updated_asset else None,
        storage_key=updated_asset.storage_key if updated_asset else None,
        cdn_url=None,  # 再申請後は審査中なのでnull
        reject_comments=updated_asset.reject_comments if updated_asset else None,
        created_at=updated_asset.created_at if updated_asset else message.created_at,
        updated_at=updated_asset.updated_at if updated_asset else message.updated_at,
        message_text=message.body_text,
        message_created_at=message.created_at,
        scheduled_at=message.scheduled_at,
        partner_user_id=partner_user_id,
        partner_username=partner_username,
        partner_profile_name=partner_profile_name,
        partner_avatar=partner_avatar,
    )


@router.put("/{group_by}/resubmit", response_model=UserMessageAssetDetailResponse)
def resubmit_message_asset_by_group_by(
    group_by: str,
    request: MessageAssetResubmitRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    拒否されたメッセージアセットまたは予約メッセージをgroup_byで一括再申請/更新
    - 古いS3ファイルを削除
    - 同じgroup_byの全アセットを一括更新
    - ステータスを再申請（RESUBMIT=3）に変更
    - 予約送信の場合、scheduled_atを更新してEventBridgeスケジュールを更新
    """
    try:
        # 権限チェック：group_byでアセット詳細を取得
        detail = message_assets_crud.get_message_asset_detail_by_group_by_for_user(
            db, group_by, current_user.id
        )

        if not detail:
            raise HTTPException(status_code=404, detail="Message asset not found")

        asset = detail["asset"]
        conversation = detail["conversation"]

        # 予約送信スケジュールの更新
        if request.scheduled_at is not None:
            # フロントエンドから送られてきたscheduled_atは既にUTC
            # タイムゾーン情報がない場合は明示的にUTCとして扱う
            scheduled_at_utc = request.scheduled_at
            if scheduled_at_utc.tzinfo is None:
                scheduled_at_utc = scheduled_at_utc.replace(tzinfo=timezone.utc)

            _update_reservation_schedule(
                db=db,
                group_by=group_by,
                scheduled_at=scheduled_at_utc,
                sender_user_id=current_user.id
            )

        # ファイル更新またはテキストのみ更新
        if request.is_new_file_selected:
            _delete_old_asset_file(asset)
            updated_asset = message_assets_crud.resubmit_message_asset_by_group_by_with_file(
                db=db,
                group_by=group_by,
                user_id=current_user.id,
                new_storage_key=request.asset_storage_key,
                new_asset_type=request.asset_type,
                message_text=request.message_text,
            )
        else:
            updated_asset = message_assets_crud.update_message_text_by_group_by(
                db=db,
                group_by=group_by,
                user_id=current_user.id,
                message_text=request.message_text,
            )

        # メッセージ情報を取得
        message = _get_message_for_response(
            db=db,
            updated_asset=updated_asset,
            group_by=group_by,
            user_id=current_user.id,
            is_new_file_selected=request.is_new_file_selected
        )

        # パートナー情報を取得
        partner_user_id, partner_username, partner_profile_name, partner_avatar = (
            _get_partner_info(
                db=db,
                message=message,
                conversation=conversation,
                current_user_id=current_user.id
            )
        )

        # レスポンスを構築
        return _build_resubmit_response(
            updated_asset=updated_asset,
            message=message,
            partner_user_id=partner_user_id,
            partner_username=partner_username,
            partner_profile_name=partner_profile_name,
            partner_avatar=partner_avatar
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resubmit message asset: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resubmit message asset: {e}")
