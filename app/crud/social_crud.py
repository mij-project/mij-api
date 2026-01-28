from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.models.social import (
    Follows,
    PostViewsTracking,
    ProfileViewsTracking,
    PostPurchasesTracking,
)
from app.core.logger import Logger as CoreLogger


class SocialCrud:
    def __init__(self, db: Session):
        self.db: Session = db
        self.logger = CoreLogger.get_logger()

    def create_profile_view_tracking(self, profile_user_id: str, viewer_user_id: Optional[str] = None) -> bool:
        now = datetime.now(timezone.utc)
        try:
            profile_view_tracking = ProfileViewsTracking(
                profile_user_id=profile_user_id,
                viewer_user_id=viewer_user_id,
                created_at=now,
            )
            self.db.add(profile_view_tracking)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error creating profile view tracking: {e}")
            raise False

    def create_post_view_tracking(
        self,
        post_id: str,
        viewer_user_id: Optional[str] = None,
        watched_duration_sec: Optional[float] = None,
        video_duration_sec: Optional[float] = None,
    ) -> bool:
        now = datetime.now(timezone.utc)
        try:
            post_view_tracking = PostViewsTracking(
                post_id=post_id,
                viewer_user_id=viewer_user_id,
                watched_duration_sec=watched_duration_sec,
                video_duration_sec=video_duration_sec,
                created_at=now,
            )
            self.db.add(post_view_tracking)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error creating post view tracking: {e}")
            raise False

    def create_post_purchase_tracking(
        self,
        post_id: str,
        user_id: str,
    ) -> bool:
        now = datetime.now(timezone.utc)
        try:
            post_purchase_tracking = PostPurchasesTracking(
                post_id=post_id,
                user_id=user_id,
                created_at=now,
            )
            self.db.add(post_purchase_tracking)
            self.db.commit()
            return True
        except Exception as e:
            self.logger.error(f"Error creating post purchase tracking: {e}")
            self.db.rollback()
            raise False

    def get_follows_by_user_id(self, user_id: str):
        follow_ids = []
        try:
            follows = self.db.query(Follows).filter(Follows.follower_user_id == user_id).all()
            follow_ids = [follow.creator_user_id for follow in follows]
        except Exception as e:
            self.logger.error(f"Error getting follows by user id: {e}")
        return follow_ids
