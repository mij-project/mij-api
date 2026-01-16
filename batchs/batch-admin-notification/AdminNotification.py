import json
import os
from threading import Thread
from uuid import UUID
from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session
from models.notifications import Notifications
from models.user import Users
from models.push_notifications import PushNotifications
from common.logger import Logger
from common.db_session import get_db
from common.email_service import EmailService
from pathlib import Path

class AdminNotification:

    def __init__(self, logger: Logger):
        self.logger = logger
        self.db: Session = next(get_db())
        self.email_service = EmailService(Path(__file__).parent / "mailtemplates")
        self.thread_pool = []
        self.notification_id = os.environ.get(
            "NOTIFICATION_ID", "cdf0b860-4680-4981-962b-70060110a640"
        )
        self.frontend_url = os.environ.get("FRONTEND_URL", "http://192.168.1.6:3002")
        self.webpush_private_key = os.environ.get("VAPID_PRIVATE_KEY")

    def _exec(self):
        self.logger.info(f"NOTIFICATION_ID {self.notification_id}")
        self.logger.info(f"FRONTEND_URL {self.frontend_url}")
        notification = self._get_notification()
        if not notification:
            self.logger.error(f"Notification not found: {self.notification_id}")
            return
        target_user = self._get_target_user(notification)
        if not target_user:
            self.logger.error(f"Target user not found: {self.notification_id}")
            return

        for user in target_user:
            thread = Thread(
                target=self._send_notification_task, args=(user, notification)
            )
            self.thread_pool.append(thread)
            thread.start()

        for thread in self.thread_pool:
            thread.join()
        return

    def _get_notification(self):
        try:
            notification_id = UUID(self.notification_id)
            return (
                self.db.query(Notifications)
                .filter(Notifications.id == notification_id)
                .first()
            )
        except Exception as e:
            self.logger.error(f"Error getting notification: {e}")
            return None

    def _get_target_user(self, notification: Notifications):
        target_user = []
        if notification.target_role == 0:
            target_user = self.db.query(Users).all()
        elif notification.target_role == 2:
            target_user = self.db.query(Users).filter(Users.role == 2).all()
        return target_user

    def _send_notification_task(self, user: Users, notification: Notifications):
        self._send_email_notification(user, notification)
        self._push_notification_to_user(user)

    def _send_email_notification(self, user: Users, notification: Notifications):
        try:
            self.email_service.send_templated(
                to=user.email,
                subject="【mijfans】運営からのお知らせ",
                template_html="admin_notification.html",
                ctx={
                    "brand": "mijfans",
                    "message": notification.payload.get("title", "mijfans 運営からのお知らせ"),
                    "notification_url": f"{self.frontend_url}/notifications?tab=system",
                    "support_email": "support@mijfans.jp",
                },
            )
        except Exception as e:
            self.logger.error(f"Error sending email notification to user: {e}")
            return

    def _push_notification_to_user(self, user: Users):
        try:
            title = "mijfans 運営からのお知らせ"
            body = "mijfans 運営からのお知らせ"
            url = f"{self.frontend_url}/notifications?tab=system"
            push_notifications = (
                self.db.query(PushNotifications)
                .filter(PushNotifications.user_id == user.id)
                .filter(PushNotifications.is_active.is_(True))
                .all()
            )
            for push_notification in push_notifications:
                try:
                    sub = {
                        "endpoint": push_notification.endpoint,
                        "keys": {
                            "p256dh": push_notification.p256dh,
                            "auth": push_notification.auth,
                        },
                    }
                    webpush(
                        subscription_info=sub,
                        data=json.dumps(
                            {
                                "title": title,
                                "body": body,
                                "url": url,
                            }
                        ),
                        vapid_private_key=self.webpush_private_key,
                        vapid_claims={
                            "sub": "mailto:support@mijfans.jp",
                        },
                    )
                except WebPushException as e:
                    self.logger.error(f"Error pushing notification to user: {e}")
                    continue
        except Exception as e:
            self.logger.error(f"Error pushing notification to user: {e}")
            return
