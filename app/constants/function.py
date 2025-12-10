from sqlalchemy import and_, or_, func
from app.constants.enums import PostStatus
from app.models.posts import Posts

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