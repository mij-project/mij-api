import os
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from uuid import UUID

from app.models.conversation_participants import ConversationParticipants
from app.models.notifications import Notifications
from app.schemas.notification import NotificationType
from app.core.logger import Logger
from app.constants.messages import IdentityVerificationMessage
from app.models.profiles import Profiles
from app.crud.push_noti_crud import push_notification_to_user


logger = Logger.get_logger()


def add_notification_for_identity_verification(
    db: Session, user_id: str, status: str
) -> bool:
    """
    身分証明書の審査結果を通知する
    """
    try:
        profiles = db.query(Profiles).filter(Profiles.user_id == user_id).first()
        if not profiles:
            raise Exception("Profileが見つかりません")
        if status == "approved":
            try:
                message = IdentityVerificationMessage.IDENTITY_APPROVED_MESSAGE.replace(
                    "-name-", profiles.username
                )
                notification_list = _for_notification_list(
                    db, user_id, status, message, profiles.username
                )
                for notification_dict in notification_list:
                    notification = Notifications(
                        user_id=notification_dict["user_id"],
                        type=notification_dict["type"],
                        payload=notification_dict["payload"],
                        is_read=False,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                    db.add(notification)
                    payload_push_noti = {
                        "title": notification_dict["payload"]["title"],
                        "body": notification_dict["payload"]["subtitle"],
                        "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/notifications",
                    }
                    push_notification_to_user(
                        db, notification_dict["user_id"], payload_push_noti
                    )
                db.commit()
            except Exception as e:
                logger.error(f"Add notification for identity verification error: {e}")
                db.rollback()
                pass
        elif status == "rejected":
            try:
                message = IdentityVerificationMessage.IDENTITY_REJECTED_MESSAGE.replace(
                    "-name-", profiles.username
                )
                notification_list = _for_notification_list(
                    db, user_id, status, message, profiles.username
                )
                for notification_dict in notification_list:
                    notification = Notifications(
                        user_id=notification_dict["user_id"],
                        type=notification_dict["type"],
                        payload=notification_dict["payload"],
                        is_read=False,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                    db.add(notification)
                    payload_push_noti = {
                        "title": notification_dict["payload"]["title"],
                        "body": notification_dict["payload"]["subtitle"],
                        "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/notifications",
                    }
                    push_notification_to_user(
                        db, notification_dict["user_id"], payload_push_noti
                    )
                db.commit()
            except Exception as e:
                logger.error(f"Add notification for identity verification error: {e}")
                db.rollback()
                pass
    except Exception as e:
        logger.error(f"Add notification for identity verification error: {e}")
        pass


def _for_notification_list(
    db: Session, user_id: str, status: str, message: str, username: str
) -> List[Dict[str, Any]]:
    """
    通知リストを生成
    Args:
        db: データベースセッション
        user_id: ユーザーID
        status: ステータス
        message: メッセージ
        username: ユーザー名
    Returns:
        list[dict]: 通知リスト
    """
    notification_list = []
    if status == "approved":
        notification_list.append(
            {
                "user_id": user_id,
                "type": NotificationType.USERS,
                "payload": {
                    "type": "identity",
                    "title": "身分証明の審査が承認されました",
                    "subtitle": "身分証明の審査が承認されました",
                    "message": message,
                    "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
                    "redirect_url": f"/profile?username={username}",
                },
            }
        )
    elif status == "rejected":
        notification_list.append(
            {
                "user_id": user_id,
                "type": NotificationType.USERS,
                "payload": {
                    "type": "identity",
                    "title": "身分証明の審査が拒否されました",
                    "subtitle": "身分証明の審査が拒否されました",
                    "message": message,
                    "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
                    "redirect_url": "/creator/request",
                },
            }
        )
    return notification_list


def add_notification_for_payment_succuces(
    db: Session,
    notification: dict,
) -> None:
    """
    決済成功時の通知を追加
    """
    try:
        notification = Notifications(**notification)
        db.add(notification)
        db.commit()

        notification_payload = notification.payload
        payload_push_noti = {
            "title": notification_payload["title"],
            "body": notification_payload["subtitle"],
            "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/notifications",
        }
        push_notification_to_user(db, notification.user_id, payload_push_noti)
    except Exception as e:
        logger.error(f"Add notification for payment succuces error: {e}")
        pass


def add_notification_for_cancel_subscription(
    db: Session,
    notification: dict,
) -> None:
    """
    プラン解約の通知を追加
    """
    try:
        notification = Notifications(**notification)
        db.add(notification)
        db.commit()
        notification_payload = notification.payload
        payload_push_noti = {
            "title": notification_payload["title"],
            "body": notification_payload["subtitle"],
            "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/notifications",
        }
        push_notification_to_user(db, notification.user_id, payload_push_noti)
    except Exception as e:
        logger.error(f"Add notification for cancel subscription error: {e}")
        pass


def add_notification_for_selling_info(
    db: Session,
    notification: dict,
) -> None:
    """
    販売情報の通知を追加
    """
    try:
        notification = Notifications(**notification)
        db.add(notification)
        db.commit()
        notification_payload = notification.payload
        payload_push_noti = {
            "title": notification_payload["title"],
            "body": notification_payload["subtitle"],
            "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/notifications",
        }
        push_notification_to_user(db, notification.user_id, payload_push_noti)
    except Exception as e:
        logger.error(f"Add notification for selling info error: {e}")
        pass


def add_notification_for_message_asset_rejection(
    db: Session,
    user_id: UUID,
    reject_comments: str,
    group_by: str,
) -> None:
    """
    メッセージアセット拒否時の通知を追加

    Args:
        db: データベースセッション
        user_id: 通知先ユーザーID（メッセージ送信者）
        reject_comments: 拒否理由コメント
        group_by: メッセージグループID
    """
    try:
        notification = Notifications(
            user_id=user_id,
            type=NotificationType.ADMIN,
            payload={
                "type": "message_asset_rejection",
                "title": "送信したメッセージが拒否されました",
                "subtitle": "メッセージに含まれる画像/動画が審査で拒否されました",
                "message": f"拒否理由: {reject_comments}",
                "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
                "redirect_url": f"/account/message/edit/{group_by}",
            },
            is_read=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(notification)
        db.commit()
        logger.info(f"Message asset rejection notification sent to user {user_id}")
        payload_push_noti = {
            "title": notification.payload["title"],
            "body": notification.payload["subtitle"],
            "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/notifications",
        }
        push_notification_to_user(db, user_id, payload_push_noti)
    except Exception as e:
        logger.error(f"Add notification for message asset rejection error: {e}")
        db.rollback()
        pass


def add_notification_for_new_message(
    db: Session,
    recipient_user_id: UUID,
    sender_profile_name: str,
    sender_avatar_url: Optional[str],
    message_preview: str,
    conversation_id: UUID,
) -> None:
    """
    新しいメッセージ受信時の通知を追加

    Args:
        db: データベースセッション
        recipient_user_id: 通知先ユーザーID（受信者）
        sender_profile_name: 送信者の表示名
        sender_avatar_url: 送信者のアバターURL
        message_preview: メッセージのプレビューテキスト
        conversation_id: 会話ID
    """
    try:
        notification = Notifications(
            user_id=recipient_user_id,
            type=NotificationType.USERS,
            payload={
                "type": "message",
                "title": "新しいメッセージが届きました",
                "subtitle": f"{sender_profile_name}さんからメッセージが届きました",
                "message": message_preview,
                "avatar": sender_avatar_url or "https://logo.mijfans.jp/bimi/logo.svg",
                "redirect_url": f"/message/conversation/{conversation_id}",
            },
            is_read=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(notification)
        db.commit()
        logger.info(
            f"New message notification sent to user {recipient_user_id} from {sender_profile_name}"
        )
        payload_push_noti = {
            "title": notification.payload["title"],
            "body": notification.payload["subtitle"],
            "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}{notification.payload['redirect_url']}",
        }
        push_notification_to_user(db, notification.user_id, payload_push_noti)
    except Exception as e:
        logger.error(f"Add notification for new message error: {e}")
        db.rollback()
        pass


def add_notification_for_message_content_approval(
    db: Session,
    user_id: UUID,
) -> None:
    """
    メッセージコンテンツ承認時の通知を追加

    Args:
        db: データベースセッション
        user_id: 通知先ユーザーID（メッセージ送信者）
    """
    try:
        notification = Notifications(
            user_id=user_id,
            type=NotificationType.USERS,
            payload={
                "type": "message_content_approval",
                "title": "送信したメッセージが承認されました",
                "subtitle": "メッセージに含まれる画像/動画が審査で承認されました",
                "message": "メッセージが承認されました",
                "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
                "redirect_url": "/message/conversation-list",
            },
            is_read=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(notification)
        db.commit()
        logger.info(f"Message content approval notification sent to user {user_id}")
        payload_push_noti = {
            "title": notification.payload["title"],
            "body": notification.payload["subtitle"],
            "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/notifications",
        }
        push_notification_to_user(db, user_id, payload_push_noti)
    except Exception as e:
        logger.error(f"Add notification for message content approval error: {e}")
        db.rollback()
        pass


def add_notification_for_bulk_message(
    db: Session,
    recipient_user_id: UUID,
    sender_profile_name: str,
    sender_avatar_url: Optional[str],
    message_preview: str,
) -> None:
    """
    一斉メッセージ受信時の通知を追加（会話IDがない場合）

    Args:
        db: データベースセッション
        recipient_user_id: 通知先ユーザーID（受信者）
        sender_profile_name: 送信者の表示名
        sender_avatar_url: 送信者のアバターURL
        message_preview: メッセージのプレビューテキスト
    """
    try:
        notification = Notifications(
            user_id=recipient_user_id,
            type=NotificationType.USERS,
            payload={
                "type": "bulk_message",
                "title": "新しいメッセージが届きました",
                "subtitle": f"{sender_profile_name}さんからメッセージが届きました",
                "message": message_preview,
                "avatar": sender_avatar_url or "https://logo.mijfans.jp/bimi/logo.svg",
                "redirect_url": "/message/conversation-list",
            },
            is_read=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(notification)
        db.commit()
        logger.info(
            f"Bulk message notification sent to user {recipient_user_id} from {sender_profile_name}"
        )
        payload_push_noti = {
            "title": notification.payload["title"],
            "body": notification.payload["subtitle"],
            "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/message/conversation-list",
        }
        push_notification_to_user(db, recipient_user_id, payload_push_noti)
    except Exception as e:
        logger.error(f"Add notification for bulk message error: {e}")
        db.rollback()
        pass

def add_notification_for_delusion_message(
    db: Session,
    conversation_id: UUID,
) -> None:
    """
    妄想メッセージ受信時の通知を追加
    """
    try:
        conversation_participant = db.query(ConversationParticipants).filter(ConversationParticipants.conversation_id == conversation_id).first()
        if conversation_participant is None:
            return
        user_id = conversation_participant.user_id
        notification = Notifications(
            user_id=user_id,
            type=NotificationType.ADMIN,
            payload={
                "type": "message",
                "title": "新しい妄想メッセージが届きました",
                "subtitle": "新しい妄想メッセージが届きました",
                "message": "新しい妄想メッセージが届きました",
                "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
                "redirect_url": "/message/delusion",
            },
            is_read=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(notification)
        db.commit()
        logger.info(f"Delusion message notification sent to user {user_id}")
        payload_push_noti = {
            "title": notification.payload["title"],
            "body": notification.payload["subtitle"],
            "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/message/delusion",
        }
        push_notification_to_user(db, user_id, payload_push_noti)
    except Exception as e:
        logger.error(f"Add notification for delusion message error: {e}")
        db.rollback()
        pass