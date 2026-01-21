from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.models.social import PostViewsTracking, ProfileViewsTracking


class SocialCrud:
    def __init__(self, db: Session):
        self.db: Session = db

    def create_profile_view_tracking(
        self, profile_user_id: str, viewer_user_id: Optional[str] = None
    ) -> bool:
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
            raise False
