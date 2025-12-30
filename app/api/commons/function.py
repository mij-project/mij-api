from sqlalchemy import and_, or_, func
from app.constants.enums import PostStatus
from app.models.posts import Posts
from app.schemas.user_settings import UserSettingsType
from sqlalchemy.orm import Session
from uuid import UUID
from app.crud.user_settings_curd import get_user_settings_by_user_id
class CommonFunction:
    @staticmethod
    def get_active_post_cond():
        """
        scheduled_atとexpiration_atを確認してアクティブな投稿を取得する条件を返す
        SQLAlchemyのクエリ内で使用するための条件式
        """
        now = func.now()
        active_post_cond = and_(
            Posts.status == PostStatus.APPROVED,
            Posts.deleted_at.is_(None),
            or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
            or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
        )
        return active_post_cond

    # @staticmethod
    @staticmethod
    def get_user_need_to_send_notification(db: Session, user_id: UUID, type: str) -> bool:
        """
        ユーザーの通知設定を取得し、通知を送信するかどうかを返す
        """
        need_to_send_notification = True
        user_settings = get_user_settings_by_user_id(db, user_id, UserSettingsType.EMAIL)
        if user_settings:
            user_setting = user_settings.settings.get(type, True)
            if not user_setting:
                need_to_send_notification = False
        return need_to_send_notification