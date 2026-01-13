import os
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session, aliased
from models.posts import Posts
from common.db_session import get_db
from common.logger import Logger
from common.email_service import EmailService
from pathlib import Path
from models.social import Follows
from models.profiles import Profiles
from models.user import Users
from models.user_settings import UserSettings
from models.notifications import Notifications
from models.push_notifications import PushNotifications
from pywebpush import webpush, WebPushException


class NewPostArrivalDomain:
    def __init__(self, logger: Logger):
        self.db: Session = next(get_db())
        self.logger = logger
        self.thread_pool = []
        self.post_id = os.environ.get("POST_ID", "3f4063c4-a72a-453a-8934-f527e3a3fa31")
        self.creator_user_id = os.environ.get(
            "CREATOR_USER_ID", "0d3c6214-977a-456e-b93b-2e953da114b5"
        )
        self.email_service = EmailService(Path(__file__).parent / "mailtemplates")

    def _exec(self):
        self.logger.info(f"CREATOR_USER_ID {self.creator_user_id}")
        self.logger.info(f"POST_ID {self.post_id}")
        followers = self._creator_followers()
        for follower in followers:
            self._send_notification_to_follower(follower)

    def _creator_followers(self):
        CreatorProfile = aliased(Profiles)
        FollowerProfile = aliased(Profiles)
        followers = (
            self.db.query(
                Follows,
                CreatorProfile.username.label("creator_username"),
                CreatorProfile.avatar_url.label("creator_avatar_url"),
                FollowerProfile.username.label("follower_username"),
                Users.email.label("email"),
                UserSettings.settings.label("settings"),
            )
            .select_from(Follows)
            # follower user
            .join(Users, Users.id == Follows.follower_user_id)
            # follower profile
            .join(FollowerProfile, FollowerProfile.user_id == Follows.follower_user_id)
            # creator profile
            .join(CreatorProfile, CreatorProfile.user_id == Follows.creator_user_id)
            # settings of follower
            .outerjoin(UserSettings, UserSettings.user_id == Follows.follower_user_id)
            .filter(Follows.creator_user_id == self.creator_user_id)
            .all()
        )
        return followers

    def _send_notification_to_follower(self, follower: Follows):
        try:
            post = self.db.query(Posts).filter(Posts.id == self.post_id).first()
            if not post:
                self.logger.error(f"Post not found: {self.post_id}")
                return
            if post.scheduled_at and post.scheduled_at.replace(
                tzinfo=timezone.utc
            ) > datetime.now(timezone.utc):
                self.logger.error(f"Post is scheduled: {self.post_id}")
                return
            should_send = True
            if follower.settings:
                newpost_arrival_setting = follower.settings.get("newPostArrival", True)
                if not newpost_arrival_setting:
                    should_send = False
            if should_send:
                self._send_email_notification(follower)
                self._insert_notification(follower)
                self._send_push_notification(follower)
        except Exception as e:
            self.logger.exception(
                f"Error sending notification to follower {follower.follower_username}: {e}"
            )

        return

    def _send_email_notification(self, follower: Follows):
        self.email_service.send_templated(
            to=follower.email,
            subject="【mijfans】新着投稿のお知らせ",
            template_html="newpost_arrival.html",
            ctx={
                "brand": "mijfans",
                "follower_username": follower.follower_username,
                "creator_username": follower.creator_username,
                "post_url": f"{os.environ.get('FRONTEND_URL', 'http://localhost:3000')}/post/detail?post_id={self.post_id}",
                "support_email": "support@mijfans.jp",
            },
        )

    def _insert_notification(self, follower: Follows):
        notifi_user_id = follower.Follows.follower_user_id
        notification = Notifications(
            user_id=notifi_user_id,
            type=2,
            payload={
                "type": "newpost_arrival",
                "title": f"{follower.creator_username} が新しく投稿しました。",
                "subtitle": f"{follower.creator_username} が新しく投稿しました。",
                "message": f"{follower.creator_username} が新しく投稿しました。",
                "avatar": f"{os.environ.get('CDN_BASE_URL', 'https://cdn-dev.mijfans.jp')}/{follower.creator_avatar_url}",
                "redirect_url": f"/post/detail?post_id={self.post_id}",
            },
        )
        self.db.add(notification)
        self.db.commit()
        return

    def _push_notification_to_user(self, follower: Follows) -> None:
        try:
            title = f"{follower.creator_username} が新しく投稿しました。"
            body = f"{follower.creator_username} が新しく投稿しました。"
            url = f"{os.environ.get('FRONTEND_URL', 'http://localhost:3002')}/post/detail?post_id={self.post_id}"
            push_notifications = (
                self.db.query(PushNotifications)
                .filter(PushNotifications.user_id == follower.Follows.follower_user_id)
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
                        vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY"),
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
