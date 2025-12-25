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
from app.crud import bulk_message_crud
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

        env = os.environ.get("ENV")

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