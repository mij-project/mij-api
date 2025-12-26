from datetime import datetime, timezone
from typing import List, Optional
import os
from sqlalchemy.orm import Session
import json
from uuid import UUID
from pathlib import Path
from common.db_session import get_db
from common.logger import Logger
from common.email_service import EmailService
from models.conversation_messages import ConversationMessages
from models.conversation_participants import ConversationParticipants
from models.conversations import Conversations
from models.user import Users
from models.user_settings import UserSettings
from models.profiles import Profiles
from models.notifications import Notifications
from models.reservation_message import ReservationMessage

# 予約送信メッセージのステータス
CONVERSATION_MESSAGE_STATUS_PENDING = 2 # 予約中
CONVERSATION_MESSAGE_STATUS_SENT = 1 # 送信済み

class SendReservationMessage:
    """
    pending(予約中) のメッセージを対象に、
    reserved_at(予約送信予定時刻) <= now のものを送信し、statusを送信済みに更新する。
    """

    def __init__(self, logger: Logger):
        self.logger: Logger = logger
        self.db: Session = next(get_db())
        self.sender_user_id = os.environ.get("SENDER_USER_ID")
        # GROUP_BYの値を取得し、前後の空白と引用符を削除
        group_by_raw = os.environ.get("GROUP_BY")
        if group_by_raw:
            # 空白を削除
            group_by_raw = group_by_raw.strip()
            # 前後の引用符を削除（シェルでexport GROUP_BY="..."とした場合に対応）
            if group_by_raw.startswith('"') and group_by_raw.endswith('"'):
                group_by_raw = group_by_raw[1:-1]
            elif group_by_raw.startswith("'") and group_by_raw.endswith("'"):
                group_by_raw = group_by_raw[1:-1]
            self.group_by = group_by_raw
        else:
            self.group_by = None
        self.email_service = EmailService(Path(__file__).parent / "mailtemplates")


    def _get_messages_by_group_by(self) -> List[ConversationMessages]:
        """
        group_byで対象のメッセージを取得
        status=PENDING のメッセージを取得
        """
        if not self.group_by:
            self.logger.error("GROUP_BY is not set")
            return []

        try:
            # デバッグ: 環境変数の実際の値を確認
            self.logger.info(f"GROUP_BY from env: {repr(self.group_by)}, length={len(self.group_by) if self.group_by else 0}")
            self.logger.info(f"Searching messages with group_by={repr(self.group_by)}, status={CONVERSATION_MESSAGE_STATUS_PENDING}")
            
            # デバッグ: group_byで一致するメッセージを確認
            all_by_group = (
                self.db.query(ConversationMessages)
                .filter(ConversationMessages.group_by == self.group_by)
                .all()
            )
            self.logger.info(f"Messages with group_by={repr(self.group_by)}: {len(all_by_group)}")
            
            if all_by_group:
                for msg in all_by_group[:5]:  # 最初の5件をログ出力
                    self.logger.info(f"  - message_id={msg.id}, status={msg.status}, scheduled_at={msg.scheduled_at}, deleted_at={msg.deleted_at}, group_by={repr(msg.group_by)}")
            else:
                # group_byがNULLでないメッセージを確認（デバッグ用）
                sample_messages = (
                    self.db.query(ConversationMessages)
                    .filter(
                        ConversationMessages.group_by.isnot(None),
                        ConversationMessages.status == CONVERSATION_MESSAGE_STATUS_PENDING
                    )
                    .limit(5)
                    .all()
                )
                if sample_messages:
                    self.logger.info(f"Sample messages with group_by (first 5):")
                    for msg in sample_messages:
                        self.logger.info(f"  - message_id={msg.id}, group_by={repr(msg.group_by)}, status={msg.status}")
            
            # 実際のクエリ（status=PENDING かつ deleted_at=NULL）
            messages = (
                self.db.query(ConversationMessages)
                .filter(
                    ConversationMessages.group_by == self.group_by,
                    ConversationMessages.status == CONVERSATION_MESSAGE_STATUS_PENDING,
                    ConversationMessages.deleted_at.is_(None),
                )
                .all()
            )
            
            self.logger.info(f"Found {len(messages)} messages matching all conditions for group_by={self.group_by}")
            return messages
        except Exception as e:
            self.logger.error(f"Failed to get messages by group_by: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return [] 

    def _now(self) -> datetime:
        """
        DBがtimestamptzで保存されている前提ならUTCで統一が安全。
        DBがJST運用なら、ここをJSTに合わせる（timezone-aware推奨）。
        """
        return datetime.now(timezone.utc)

    def _send_one(self, msg: ConversationMessages) -> bool:
        """
        実際の送信処理はここに実装。
        通知を送信者以外の会話参加者に送る。
        """
        try:
            self.logger.info(f"[SEND] conversation_id={msg.conversation_id} message_id={msg.id}")

            # 送信者以外の会話参加者を取得
            recipients = self._get_recipients(msg.conversation_id)

            # 各参加者に通知を送信
            for recipient in recipients:
                self._send_notification_to_recipient(msg, recipient)

            return True
        except Exception as e:
            self.logger.error(f"Send failed: message_id={getattr(msg, 'id', None)} err={e}")
            return False

    def _mark_sent(self, msg: ConversationMessages) -> None:
        """
        送信済みに更新（冪等性：pendingのものだけ更新したいならロック/条件更新も可）
        """
        msg.status = CONVERSATION_MESSAGE_STATUS_SENT

        # 予約メッセージのスケジュール時間を更新
        reservation_message = self.db.query(ReservationMessage).filter(ReservationMessage.group_by == msg.group_by).first()
        msg.updated_at = reservation_message.scheduled_at
        
        # 会話のlast_message_idとlast_message_atを更新
        conversation = self.db.query(Conversations).filter(Conversations.id == msg.conversation_id).first()
        if conversation:
            conversation.last_message_id = msg.id
            conversation.last_message_at = self._now()


    def _exec(self) -> None:
        """
        バッチのメイン処理
        group_byで対象のメッセージを取得して送信処理を実行
        """
        try:
            if not self.group_by:
                self.logger.error("GROUP_BY is not set. Cannot proceed.")
                return

            # group_byで対象のメッセージを取得
            messages = self._get_messages_by_group_by()
            if not messages:
                self.logger.info(f"No messages to send for group_by={self.group_by}")
                return

            sent_count = 0
            failed_count = 0
            
            for msg in messages:
                try:
                    ok = self._send_one(msg)
                    if ok:
                        self._mark_sent(msg)
                        sent_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    self.db.rollback()
                    self.logger.error(f"Error processing message {msg.id}: {e}")
                    failed_count += 1
                    continue

            # 送信できた分だけコミット（失敗が混ざっても成功分は反映）
            self.db.commit()

            self.logger.info(f"Done. sent={sent_count}, failed={failed_count} for group_by={self.group_by}")

        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Failed to send reservation message: {e}")

        finally:
            self.db.close()

    def _get_recipients(self, conversation_id: UUID):
        """
        会話の参加者のうち、送信者以外を取得
        """
        query = (
            self.db.query(
                ConversationParticipants,
                Users.email.label("email"),
                UserSettings.settings.label("settings"),
                Profiles.username.label("username"),
            )
            .select_from(ConversationParticipants)
            .join(Users, Users.id == ConversationParticipants.participant_id)
            .outerjoin(UserSettings, UserSettings.user_id == ConversationParticipants.participant_id)
            .outerjoin(Profiles, Profiles.user_id == ConversationParticipants.participant_id)
            .filter(ConversationParticipants.conversation_id == conversation_id)
        )

        # 送信者IDが設定されている場合は送信者を除外
        if self.sender_user_id:
            try:
                sender_uuid = UUID(self.sender_user_id)
                query = query.filter(ConversationParticipants.participant_id != sender_uuid)
            except (ValueError, TypeError):
                self.logger.error(f"Invalid SENDER_USER_ID format: {self.sender_user_id}")

        return query.all()

    def _send_notification_to_recipient(self, msg: ConversationMessages, recipient):
        """
        個別の受信者に通知を送信
        """
        try:
            # user_settingsで「message」通知がONかチェック
            should_send = True
            if recipient.settings:
                message_setting = recipient.settings.get("message", True)
                if not message_setting:
                    should_send = False
                    self.logger.info(f"Message notification disabled for user: {recipient.username}")
                    return

            # 通知がミュートされている場合はスキップ
            if recipient.ConversationParticipants.notifications_muted:
                self.logger.info(f"Notifications muted for user: {recipient.username}")
                return

            if should_send:
                # 送信者情報を取得
                sender_profile = self._get_sender_profile()

                # DB通知を挿入
                self._insert_notification(msg, recipient, sender_profile)

                # メール通知を送信
                self._send_email_notification(msg, recipient, sender_profile)

        except Exception as e:
            self.logger.exception(f"Error sending notification to recipient {recipient.username}: {e}")

    def _get_sender_profile(self):
        """
        送信者のユーザー情報とプロフィール情報を取得
        """
        if not self.sender_user_id:
            return None

        try:
            sender_uuid = UUID(self.sender_user_id)
            result = (
                self.db.query(Users, Profiles)
                .outerjoin(Profiles, Users.id == Profiles.user_id)
                .filter(Users.id == sender_uuid)
                .first()
            )
            
            if not result:
                return None
            
            user, profile = result
            
            # 辞書形式で返す（既存コードとの互換性のため）
            return {
                "user": user,
                "profile": profile,
                "username": profile.username if profile else None,
                "avatar_url": profile.avatar_url if profile else None,
                "profile_name": user.profile_name if user else None,
            }
        except (ValueError, TypeError) as e:
            self.logger.error(f"Failed to get sender profile: {e}")
            return None

    def _insert_notification(self, msg: ConversationMessages, recipient, sender_profile):
        """
        通知をDBに挿入
        """
        recipient_user_id = recipient.ConversationParticipants.participant_id

        # 送信者情報の準備
        sender_profile_name = sender_profile.get("profile_name") if sender_profile else None
        if not sender_profile_name:
            sender_profile_name = sender_profile.get("username") if sender_profile else "送信者"
        sender_avatar = sender_profile.get("avatar_url") if sender_profile else ""
        cdn_base_url = os.environ.get("CDN_BASE_URL", "https://cdn-dev.mijfans.jp")
        avatar_url = f"{cdn_base_url}/{sender_avatar}" if sender_avatar else ""

        notification = Notifications(
            user_id=recipient_user_id,
            type=2,  # 2: users -> users
            payload={
                "type": "new_message",
                "title": f"{sender_profile_name}からメッセージが届きました",
                "subtitle": f"{sender_profile_name}からメッセージが届きました",
                "message": f"{sender_profile_name}からメッセージが届きました",
                "avatar": avatar_url,
                "redirect_url": f"/message/conversation/{msg.conversation_id}",
                "conversation_id": str(msg.conversation_id),
                "message_id": str(msg.id),
            },
        )
        self.db.add(notification)
        self.db.commit()
        self.logger.info(f"Notification inserted for user: {recipient.username}")

    def _send_email_notification(self, msg: ConversationMessages, recipient, sender_profile):
        """
        メール通知を送信
        """
        if not recipient.email:
            self.logger.warning(f"No email address for user: {recipient.username}")
            return

        sender_profile_name = sender_profile.get("profile_name") if sender_profile else None
        if not sender_profile_name:
            sender_profile_name = sender_profile.get("username") if sender_profile else "送信者"
        frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")

        self.email_service.send_templated(
            to=recipient.email,
            subject="【mijfans】新着メッセージのお知らせ",
            template_html="new_message.html",
            ctx={
                "brand": "mijfans",
                "recipient_username": recipient.username or "ユーザー",
                "sender_username": sender_profile_name,
                "conversation_url": f"{frontend_url}/message/conversation/{msg.conversation_id}",
                "support_email": "support@mijfans.jp",
            },
        )
        self.logger.info(f"Email sent to: {recipient.email}")
