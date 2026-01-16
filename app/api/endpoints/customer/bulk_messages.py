# app/api/endpoints/customer/bulk_messages.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
import logging
import os
import json
from typing import List
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.models.profiles import Profiles
from app.crud import bulk_message_crud
from app.crud import notifications_crud
from app.schemas.bulk_message import (
    BulkMessageRecipientsResponse,
    PresignedUrlRequest,
    PresignedUrlResponse,
    BulkMessageSendRequest,
    BulkMessageSendResponse,
)
from app.services.s3 import presign, keygen
from app.constants.enums import MessageAssetType
from app.services.s3.client import scheduler_client
from datetime import datetime, timezone, timedelta
from app.crud.reservation_message_crud import ReservationMessageCrud
from app.models.reservation_message import ReservationMessage
from app.api.commons.function import CommonFunction
from app.services.email.send_email import send_message_notification_email

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/recipients", response_model=BulkMessageRecipientsResponse)
def get_bulk_message_recipients(
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    一斉送信の送信先リスト情報を取得
    - クリエイターのみアクセス可能
    - チップ送信者数、単品購入者数、プラン別加入者数を返す
    """

    recipients = bulk_message_crud.get_bulk_message_recipients(db, current_user.id)

    return BulkMessageRecipientsResponse(
        chip_senders_count=recipients['chip_senders_count'],
        single_purchasers_count=recipients['single_purchasers_count'],
        plan_subscribers=recipients['plan_subscribers']
    )


@router.post("/upload-url", response_model=PresignedUrlResponse)
def get_bulk_message_upload_url(
    request: PresignedUrlRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    一斉送信用メッセージアセットのPresigned URL取得
    - クリエイターのみアクセス可能
    - 画像または動画のアップロード用URL生成
    """
    try:
        # ファイルタイプの検証
        allowed_image_types = ["image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp", "image/heic", "image/heif"]
        allowed_video_types = ["video/mp4", "video/quicktime"]  # mp4, mov

        if request.asset_type == MessageAssetType.IMAGE:
            if request.content_type not in allowed_image_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid image content type. Allowed: {', '.join(allowed_image_types)}"
                )
        elif request.asset_type == MessageAssetType.VIDEO:
            if request.content_type not in allowed_video_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid video content type. Allowed: {', '.join(allowed_video_types)}"
                )
        else:
            raise HTTPException(status_code=400, detail="Invalid asset type")

        # 拡張子の検証
        allowed_extensions = {
            MessageAssetType.IMAGE: ["jpg", "jpeg", "png", "gif", "webp", "heic", "heif"],
            MessageAssetType.VIDEO: ["mp4", "mov"],
        }

        if request.file_extension.lower() not in allowed_extensions[request.asset_type]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file extension for asset type. Allowed: {', '.join(allowed_extensions[request.asset_type])}"
            )

        # ストレージキー生成（一斉送信用の固有キー）
        import uuid
        bulk_message_id = str(uuid.uuid4())
        asset_type_str = "image" if request.asset_type == MessageAssetType.IMAGE else "video"

        storage_key = keygen.bulk_message_asset_key(
            user_id=str(current_user.id),
            bulk_message_id=bulk_message_id,
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
        logger.error(f"一斉送信用Presigned URL取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=BulkMessageSendResponse)
def send_bulk_message(
    request: BulkMessageSendRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    一斉メッセージ送信
    - クリエイターのみアクセス可能
    - 選択された送信先に対してメッセージを一斉送信
    - 予約送信にも対応
    """
    try:
        # クリエイター権限チェック

        # 送信先が1つも選択されていない場合はエラー
        if not request.send_to_chip_senders and not request.send_to_single_purchasers and not request.send_to_plan_subscribers:
            raise HTTPException(status_code=400, detail="送信先を選択してください")

        # アセットがある場合はasset_typeも必要
        if request.asset_storage_key and not request.asset_type:
            raise HTTPException(status_code=400, detail="asset_typeが必要です")

        # 対象ユーザーIDリストを取得
        target_user_ids = bulk_message_crud.get_target_user_ids(
            db=db,
            creator_user_id=current_user.id,
            send_to_chip_senders=request.send_to_chip_senders,
            send_to_single_purchasers=request.send_to_single_purchasers,
            send_to_plan_subscribers=request.send_to_plan_subscribers
        )

        if not target_user_ids:
            raise HTTPException(status_code=400, detail="送信対象のユーザーが見つかりません")

        # 即時送信
        sent_count, message_ids, group_by = bulk_message_crud.send_bulk_messages(
            db=db,
            creator_user_id=current_user.id,
            message_text=request.message_text,
            target_user_ids=target_user_ids,
            asset_storage_key=request.asset_storage_key,
            asset_type=request.asset_type,
            scheduled_at=request.scheduled_at
        )

        if request.scheduled_at:
            result = _define_ecs_task_schedule(db, group_by, request.scheduled_at, current_user.id)
            if not result["result"]:
                db.rollback()
                raise HTTPException(status_code=500, detail="ECSタスクのスケジュールを定義できませんでした")
            else:
                reservation_message_obj = ReservationMessage(
                    event_bridge_name=result["schedule_name"],
                    group_by=group_by,
                    scheduled_at=request.scheduled_at
                )
                reservation_message = ReservationMessageCrud(db).create_reservation_message(
                    reservation_message=reservation_message_obj
                )
        else:
            # 即時送信でアセットがない場合、受信者に通知とメールを送信（ベストエフォート）
            try:
                if request.asset_storage_key is None:
                    _send_notifications_to_recipients(
                        db=db,
                        sender_user_id=current_user.id,
                        target_user_ids=target_user_ids,
                        message_text=request.message_text,
                    )
            except Exception as e:
                # 通知送信エラーはログに記録するが、メッセージ送信は成功とする
                logger.error(f"Failed to send notifications for bulk message: {e}")


        return BulkMessageSendResponse(
            message="一斉送信が完了しました",
            sent_count=sent_count,
            scheduled=False,
            scheduled_at=None
        )
    except Exception as e:
        db.rollback()
        logger.error(f"一斉送信エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ecsタスクのスケジュールを定義する関数
def _define_ecs_task_schedule(db: Session, group_by: str, scheduled_at: datetime, sender_user_id: UUID) -> None:
    """
    ECSタスクのスケジュールを定義
    """
    try:
        scheduler = scheduler_client()

        # (A) スケジュール名（ユニークに）
        schedule_name = f"send-resv-msg-{sender_user_id}-{int(scheduled_at.timestamp())}"

        # (B) 単発 at() 形式（秒まで）
        # scheduled_at は UTC で受け取るため、JST (UTC+9) に変換
        jst_timezone = timezone(timedelta(hours=9))
        scheduled_at_jst = scheduled_at.astimezone(jst_timezone) if scheduled_at.tzinfo else scheduled_at.replace(tzinfo=timezone.utc).astimezone(jst_timezone)

        # at() 式には JST時刻を渡す（ScheduleExpressionTimezone="Asia/Tokyo"と合わせる）
        schedule_expression = f"at({scheduled_at_jst.strftime('%Y-%m-%dT%H:%M:%S')})"

        logger.info(f"Creating schedule: {schedule_name} at {scheduled_at_jst.strftime('%Y-%m-%d %H:%M:%S %Z')} JST")

        # (C) ネットワーク設定
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

        # env = os.environ.get("ENV")

        task_definition = os.environ["ECS_SEND_RESERVATION_MESSAGE_TASK_ARN"]
        
        # (D) ★ここが肝：ECS RunTask の overrides を Target.Input に入れる
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

        scheduler.create_schedule(
            Name=schedule_name,
            ScheduleExpression=schedule_expression,
            ScheduleExpressionTimezone="Asia/Tokyo",
            FlexibleTimeWindow={"Mode": "OFF"},
            State="ENABLED",
            ActionAfterCompletion="DELETE",
            Target={
                # ECS RunTask ターゲット
                "Arn": os.environ["ECS_SEND_RESERVATION_MESSAGE_CLUSTER_ARN"],      # ※クラスターARNを入れる
                "RoleArn": os.environ["SCHEDULER_ROLE_ARN"],           # SchedulerがRunTaskできるロール
                "EcsParameters": {
                    "TaskDefinitionArn": task_definition,              # ARN推奨（名前だけだと環境でズレることがある）
                    "LaunchType": "FARGATE",
                    "NetworkConfiguration": network_configuration,
                    # 必要なら PlatformVersion / CapacityProviderStrategy など
                },
                "Input": json.dumps(overrides),
            },
            # 可能なら実行後削除（ActionAfterCompletion はSDK/バージョンで差分が出ることがあるので注意）
        )
        return {
            "schedule_name": schedule_name,
            "result": True,
        }
    except Exception as e:
        logger.error(f"Failed to define ECS task schedule: {e}")
        return {
            "schedule_name": schedule_name,
            "result": False,
        }


def _send_notifications_to_recipients(
    db: Session,
    sender_user_id: UUID,
    target_user_ids: List[UUID],
    message_text: str,
) -> None:
    """
    受信者に対して通知とメールを送信（即時送信時）
    send_conversation_messageの通知ロジックを参考に実装
    """
    # 送信者のプロフィール情報を取得
    sender_user = db.query(Users).filter(Users.id == sender_user_id).first()
    if not sender_user:
        logger.warning(f"Sender user not found: {sender_user_id}")
        return

    sender_profile = db.query(Profiles).filter(Profiles.user_id == sender_user_id).first()
    sender_avatar_url = f"{os.getenv('CDN_BASE_URL')}/{sender_profile.avatar_url}" if sender_profile and sender_profile.avatar_url else None

    # メッセージプレビューを生成
    if message_text:
        message_preview = message_text[:50] if len(message_text) > 50 else message_text

    # 各受信者に通知とメールを送信
    for recipient_user_id in target_user_ids:
        try:
            need_to_send_notification = CommonFunction.get_user_need_to_send_notification(
                db, recipient_user_id, "userMessages"
            )
            if not need_to_send_notification:
                continue

            recipient_user = db.query(Users).filter(Users.id == recipient_user_id).first()
            if not recipient_user:
                continue

            # アプリ内通知を作成（新しいメッセージ到着）
            # 一斉送信の場合は、会話IDがないため、generic notificationを作成
            notifications_crud.add_notification_for_bulk_message(
                db=db,
                recipient_user_id=recipient_user.id,
                sender_profile_name=sender_user.profile_name or "Unknown User",
                sender_avatar_url=sender_avatar_url,
                message_preview=message_preview,
            )

            # メール通知を送信
            need_to_send_email_notification = CommonFunction.get_user_need_to_send_notification(
                db, recipient_user.id, "message"
            )
            if need_to_send_email_notification and recipient_user.email:
                try:
                    recipient_profile = db.query(Profiles).filter(Profiles.user_id == recipient_user.id).first()
                    recipient_name = recipient_profile.username if recipient_profile and recipient_profile.username else recipient_user.profile_name

                    send_message_notification_email(
                        to=recipient_user.email,
                        sender_name=sender_user.profile_name or "Unknown User",
                        recipient_name=recipient_name or "User",
                        message_preview=message_preview,
                        conversation_url=f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/message/conversation-list",
                    )
                    logger.info(f"Bulk message notification email sent to {recipient_user.email}")
                except Exception as e:
                    logger.error(f"Failed to send notification email to {recipient_user.email}: {e}")
        except Exception as e:
            logger.error(f"Failed to send notification to recipient {recipient_user_id}: {e}")