from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, asc
from datetime import datetime, timezone
from uuid import UUID

from app.models.notifications import Notifications
from app.schemas.notification import NotificationCreateRequest, NotificationType
from app.core.logger import Logger
from app.constants.messages import IdentityVerificationMessage
from app.constants.enums import VerificationStatus
from app.models.profiles import Profiles


logger = Logger.get_logger()

def add_notification_for_identity_verification(db: Session, user_id: str, status: str) -> bool:
  """
  身分証明書の審査結果を通知する
  """
  try:
      profiles = db.query(Profiles).filter(Profiles.user_id == user_id).first()
      if not profiles:
          raise Exception("Profileが見つかりません")
      if status == "approved":
          try:
              message = IdentityVerificationMessage.IDENTITY_APPROVED_MESSAGE.replace("-name-", profiles.username)
              notification_list = _for_notification_list(db, user_id, status, message, profiles.username)
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
              db.commit()
          except Exception as e:
              logger.error(f"Add notification for identity verification error: {e}")
              db.rollback()
              pass
      elif status == "rejected":
          try:
              message = IdentityVerificationMessage.IDENTITY_REJECTED_MESSAGE.replace("-name-", profiles.username)
              notification_list = _for_notification_list(db, user_id, status, message, profiles.username)
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
              db.commit()
          except Exception as e:
              logger.error(f"Add notification for identity verification error: {e}")
              db.rollback()
              pass
  except Exception as e:
      logger.error(f"Add notification for identity verification error: {e}")
      pass

def _for_notification_list(db: Session, user_id: str, status: str, message: str, username: str) -> List[Dict[str, Any]]:
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
        notification_list.append({
            "user_id": user_id,
            "type": NotificationType.USERS,
            "payload": {
                "type": "identity",
                "title": "身分証明の審査が承認されました",
                "subtitle": "身分証明の審査が承認されました",
                "message": message,
                "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
                "redirect_url": f"/profile?username={username}",
            }
        })
    elif status == "rejected":
        notification_list.append({
            "user_id": user_id,
            "type": NotificationType.USERS,
            "payload": {
                "type": "identity",
                "title": "身分証明の審査が拒否されました",
                "subtitle": "身分証明の審査が拒否されました",
                "message": message,
                "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
                "redirect_url": "/creator/request",
            }
        })
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
    except Exception as e:
        logger.error(f"Add notification for selling info error: {e}")
        pass


def add_notification_for_message_asset_rejection(
    db: Session,
    user_id: UUID,
    reject_comments: str,
) -> None:
    """
    メッセージアセット拒否時の通知を追加

    Args:
        db: データベースセッション
        user_id: 通知先ユーザーID（メッセージ送信者）
        reject_comments: 拒否理由コメント
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
                "redirect_url": "/messages",
            },
            is_read=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(notification)
        db.commit()
        logger.info(f"Message asset rejection notification sent to user {user_id}")
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
        logger.info(f"New message notification sent to user {recipient_user_id} from {sender_profile_name}")
    except Exception as e:
        logger.error(f"Add notification for new message error: {e}")
        db.rollback()
        pass