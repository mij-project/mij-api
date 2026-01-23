from __future__ import annotations
from logging import Logger
from sqlalchemy.orm import Session
from app.core.logger import Logger as CoreLogger
from app.crud import bulk_message_crud, user_crud, notifications_crud, profile_crud
from app.schemas.bulk_message import PresignedUrlRequest, BulkMessageSendRequest
from app.constants.enums import MessageAssetType
from typing import List
from datetime import datetime
from app.models.reservation_message import ReservationMessage
from app.models.user import Users
from app.crud.reservation_message_crud import ReservationMessageCrud
from app.services.s3 import presign, keygen
from app.services.s3.client import scheduler_client
import uuid
from uuid import UUID
from app.services.email.send_email import send_message_notification_email
from app.api.commons.function import CommonFunction
from app.models.profiles import Profiles
import os
import json
from datetime import timezone, timedelta
from app.core.logger import Logger as CoreLogger

class BulkMessageDomain:

    def __init__(self, db: Session):
        self.db: Session = db
        self.logger: Logger = CoreLogger.get_logger()
        self.reservation_message_crud: ReservationMessageCrud = ReservationMessageCrud(self.db)
        self.common_function: CommonFunction = CommonFunction()
    
    ########################################################
    # API関連のメソッド
    ########################################################
    def get_bulk_message_recipients(self, creator_user_id: UUID):
        return  bulk_message_crud.get_bulk_message_recipients(self.db, creator_user_id)

    def get_presigned_url_for_bulk_message(self, request: PresignedUrlRequest, current_user: Users):
        """
        Presigned URL生成
        - ファイルタイプの検証
        - 拡張子の検証
        - Presigned URL生成
        Args:
            request (PresignedUrlRequest): リクエスト
            current_user (Users): 現在のユーザー

        Returns:
            dict: Presigned URL
        """
        try:
            # ファイルタイプの検証
            self.__check_file_type(request)

            # 拡張子の検証
            self.__check_file_extension(request)

            # Presigned URL生成
            result = self.__get_presigned_url(request, current_user)
            return result
        except Exception as e:
            self.logger.error(f"一斉送信用Presigned URL取得エラー: {e}")
            raise Exception(status_code=500, detail=str(e))


    def send_bulk_message(self, request: BulkMessageSendRequest, current_user: Users):
        """
        一斉送信の処理
        - スケジュールを定義する前に、送信先とアセットのチェックを行う
        - スケジュール送信または即時送信の処理
        - 送信先が1つも選択されていない場合はエラー
        - アセットがある場合はasset_typeも必要
        - メッセージを送信先に送信
        Args:
            request (BulkMessageSendRequest): リクエスト
            current_user (Users): 現在のユーザー
        """
        try:
            # スケジュールを定義する前に、送信先とアセットのチェックを行う
            self.__check_schedule_name(request)

            sent_count, message_ids, group_by, target_user_ids = self._handle_message_sending(request, current_user)

            # スケジュール送信または即時送信の処理
            if request.scheduled_at:
                self._handle_scheduled_message(group_by, request.scheduled_at, current_user.id)
            else:
                self._handle_immediate_message(request, target_user_ids, current_user.id)


            return {
                "message": "一斉送信が完了しました",
                "sent_count": sent_count,
                "scheduled": False,
                "scheduled_at": None
            }
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"一斉送信エラー: {e}")
            raise Exception(status_code=500, detail=str(e))
     
    ########################################################
    # メイン処理
    ########################################################
    def _handle_message_sending(self, request: BulkMessageSendRequest, current_user: Users):
        """
        メッセージ送信の処理（クラス内完結）
        受信者へのメッセージ送信を制御

        Args:
            request: BulkMessageSendRequest
            current_user: Users

        Returns:
            tuple: (sent_count, message_ids, group_by, target_user_ids)
        """
        # 対象ユーザーIDリストを取得（DB接続）
        target_user_ids = bulk_message_crud.get_target_user_ids(
            db=self.db,
            creator_user_id=current_user.id,
            send_to_chip_senders=request.send_to_chip_senders,
            send_to_single_purchasers=request.send_to_single_purchasers,
            send_to_follower_users=request.send_to_follower_users,
            send_to_plan_subscribers=request.send_to_plan_subscribers
        )

        if not target_user_ids:
            raise Exception(status_code=400, detail="送信対象のユーザーが見つかりません")

        # メッセージ送信（DB接続）
        sent_count, message_ids, group_by = bulk_message_crud.send_bulk_messages(
            db=self.db,
            creator_user_id=current_user.id,
            message_text=request.message_text,
            target_user_ids=target_user_ids,
            asset_storage_key=request.asset_storage_key,
            asset_type=request.asset_type,
            scheduled_at=request.scheduled_at
        )

        return sent_count, message_ids, group_by, target_user_ids

    def _handle_scheduled_message(self, group_by: str, scheduled_at: datetime, sender_user_id: UUID):
        """
        スケジュール送信の処理（クラス内完結）
        - ECSタスクのスケジュールを定義
        - 予約メッセージを作成

        Args:
            group_by: グループ化キー
            scheduled_at: 予約送信日時
            sender_user_id: 送信者ユーザーID

        Raises:
            Exception: ECSタスクのスケジュール定義に失敗した場合
        """
        # 外部サービス（ECS）への接続
        result = self.__set_ecs_scheduler(group_by, scheduled_at, sender_user_id)
        if not result["result"]:
            self.db.rollback()
            raise Exception(status_code=500, detail="ECSタスクのスケジュールを定義できませんでした")
        
        # クラス内完結処理：予約メッセージオブジェクトの作成
        reservation_message_obj = self.__create_reservation_message_object(
            result["schedule_name"], group_by, scheduled_at
        )
        
        # DB接続：予約メッセージの保存
        self.__reservation_message(reservation_message_obj)

    def _handle_immediate_message(self, request: BulkMessageSendRequest, target_user_ids: List[UUID], sender_user_id: UUID):
        """
        即時送信の処理（クラス内完結）
        - 受信者に通知とメールを送信（ベストエフォート）

        Args:
            request: BulkMessageSendRequest
            target_user_ids: 送信先ユーザーIDリスト
            sender_user_id: 送信者ユーザーID
        """
        # 即時送信でアセットがない場合、受信者に通知とメールを送信（ベストエフォート）
        try:
            if request.asset_storage_key is None:
                # 外部サービス（通知・メール）への接続
                self.__notification_service(
                    sender_user_id=sender_user_id,
                    target_user_ids=target_user_ids,
                    message_text=request.message_text,
                )
        except Exception as e:
            # 通知送信エラーはログに記録するが、メッセージ送信は成功とする
            self.logger.error(f"Failed to send notifications for bulk message: {e}")

    ########################################################
    # 外部サービス接続
    ########################################################

    def __reservation_message(self, reservation_message_obj: ReservationMessage):
        """
        データベース接続：予約メッセージの保存

        Args:
            reservation_message_obj: ReservationMessage
        """
        self.reservation_message_crud.create_reservation_message(
            reservation_message=reservation_message_obj
        )

    def __set_ecs_scheduler(
        self,
        group_by: str,
        scheduled_at: datetime,
        sender_user_id: UUID
    ) -> dict:
        """
        外部サービス接続：ECSスケジューラーへの接続
        ECSタスクのスケジュールを定義

        Args:
            group_by: グループ化キー
            scheduled_at: 予約送信日時
            sender_user_id: 送信者ユーザーID

        Returns:
            dict: スケジュール情報
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

            self.logger.info(f"Creating schedule: {schedule_name} at {scheduled_at_jst.strftime('%Y-%m-%d %H:%M:%S %Z')} JST")

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
            self.logger.error(f"Failed to define ECS task schedule: {e}")
            return {
                "schedule_name": schedule_name,
                "result": False,
            }

    def __notification_service(
        self,
        sender_user_id: UUID,
        target_user_ids: List[UUID],
        message_text: str,
    ) -> None:
        """
        外部サービス接続：通知・メールサービスへの接続
        受信者に対して通知とメールを送信（即時送信時）
        send_conversation_messageの通知ロジックを参考に実装
        """
        # 送信者のプロフィール情報を取得
        sender_user = user_crud.get_user_by_id(self.db, sender_user_id)
        if not sender_user:
            self.logger.warning(f"Sender user not found: {sender_user_id}")
            return

        sender_profile = profile_crud.get_profile_by_user_id(self.db, sender_user_id)
        sender_avatar_url = f"{os.getenv('CDN_BASE_URL')}/{sender_profile.avatar_url}" if sender_profile and sender_profile.avatar_url else None

        # メッセージプレビューを生成
        if message_text:
            message_preview = message_text[:50] if len(message_text) > 50 else message_text

        # 各受信者に通知とメールを送信
        for recipient_user_id in target_user_ids:
            try:
                need_to_send_notification = self.common_function.get_user_need_to_send_notification(
                    self.db, recipient_user_id, "userMessages"
                )
                if not need_to_send_notification:
                    continue

                recipient_user = user_crud.get_user_by_id(self.db, recipient_user_id)
                if not recipient_user:
                    continue

                # アプリ内通知を作成（新しいメッセージ到着）
                # 一斉送信の場合は、会話IDがないため、generic notificationを作成
                notifications_crud.add_notification_for_bulk_message(
                    db=self.db,
                    recipient_user_id=recipient_user.id,
                    sender_profile_name=sender_user.profile_name or "Unknown User",
                    sender_avatar_url=sender_avatar_url,
                    message_preview=message_preview,
                )

                # メール通知を送信
                need_to_send_email_notification = self.common_function.get_user_need_to_send_notification(
                    db=self.db, user_id=recipient_user.id, notification_type="message"
                )
                if need_to_send_email_notification and recipient_user.email:
                    try:
                        recipient_profile = profile_crud.get_profile_by_user_id(self.db, recipient_user.id)
                        recipient_name = recipient_profile.username if recipient_profile and recipient_profile.username else recipient_user.profile_name

                        send_message_notification_email(
                            to=recipient_user.email,
                            sender_name=sender_user.profile_name or "Unknown User",
                            recipient_name=recipient_name or "User",
                            message_preview=message_preview,
                            conversation_url=f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/message/conversation-list",
                        )
                        self.logger.info(f"Bulk message notification email sent to {recipient_user.email}")
                    except Exception as e:
                        self.logger.error(f"Failed to send notification email to {recipient_user.email}: {e}")
            except Exception as e:
                self.logger.error(f"Failed to send notification to recipient {recipient_user_id}: {e}")

    ########################################################
    # クラス内完結処理
    ########################################################
    def __create_reservation_message_object(
        self, 
        event_bridge_name: str, 
        group_by: str, 
        scheduled_at: datetime
    ) -> ReservationMessage:
        """
        クラス内完結処理：予約メッセージオブジェクトの作成

        Args:
            event_bridge_name: イベントブリッジ名
            group_by: グループ化キー
            scheduled_at: 予約送信日時

        Returns:
            ReservationMessage: 予約メッセージオブジェクト
        """
        return ReservationMessage(
            event_bridge_name=event_bridge_name,
            group_by=group_by,
            scheduled_at=scheduled_at
        )

    ########################################################
    # ユーティリティ関数　
    ########################################################
    @staticmethod
    def __check_file_type(request: PresignedUrlRequest):
        """ファイルタイプの検証
        Args:
            request (PresignedUrlRequest): リクエスト

        Raises:
            Exception: ファイルタイプが不正な場合
        """
        allowed_image_types = ["image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp", "image/heic", "image/heif"]
        allowed_video_types = ["video/mp4", "video/quicktime"]  # mp4, mov

        if request.asset_type == MessageAssetType.IMAGE:
            if request.content_type not in allowed_image_types:
                raise Exception(status_code=400, detail=f"Invalid image content type. Allowed: {', '.join(allowed_image_types)}")
        elif request.asset_type == MessageAssetType.VIDEO:
            if request.content_type not in allowed_video_types:
                raise Exception(status_code=400, detail=f"Invalid video content type. Allowed: {', '.join(allowed_video_types)}")
        else:
            raise Exception(status_code=400, detail="Invalid asset type")

    @staticmethod
    def __check_file_extension(request: PresignedUrlRequest):
        """ファイル拡張子の検証

        Args:
            request (PresignedUrlRequest): リクエスト

        Raises:
            Exception: ファイル拡張子が不正な場合
        """
        allowed_extensions = {
            MessageAssetType.IMAGE: ["jpg", "jpeg", "png", "gif", "webp", "heic", "heif"],
            MessageAssetType.VIDEO: ["mp4", "mov"],
        }

        if request.file_extension.lower() not in allowed_extensions[request.asset_type]:
            raise Exception(status_code=400, detail=f"Invalid file extension for asset type. Allowed: {', '.join(allowed_extensions[request.asset_type])}")

    @staticmethod
    def __get_presigned_url(request: PresignedUrlRequest, current_user: Users):
        """Presigned URL生成

        Args:
            request (PresignedUrlRequest): リクエスト
            current_user (Users): 現在のユーザー

        Returns:
            dict: Presigned URL
        """
        bulk_message_id = str(uuid.uuid4())
        asset_type_str = "image" if request.asset_type == MessageAssetType.IMAGE else "video"

        storage_key = keygen.bulk_message_asset_key(
            user_id=str(current_user.id),
            bulk_message_id=bulk_message_id,
            asset_type=asset_type_str,
            ext=request.file_extension.lower(),
        )
        return presign.presign_put(resource="message-assets", key=storage_key, content_type=request.content_type, expires_in=3600)

    @staticmethod
    def __check_schedule_name(request: BulkMessageSendRequest) -> None:
        """
        スケジュールを定義する前に、送信先とアセットのチェックを行う

        Args:
            request: BulkMessageSendRequest

        Raises:
            Exception: 送信先が選択されていない場合、アセットがない場合
        """
        # 送信先が1つも選択されていない場合はエラー
        if not request.send_to_chip_senders and not request.send_to_single_purchasers and not request.send_to_plan_subscribers and not request.send_to_follower_users:
            raise Exception(status_code=400, detail="送信先を選択してください")

        # アセットがある場合はasset_typeも必要
        if request.asset_storage_key and not request.asset_type:
            raise Exception(status_code=400, detail="asset_typeが必要です")
