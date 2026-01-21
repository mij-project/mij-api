from __future__ import annotations
from logging import Logger
from typing import Optional
from sqlalchemy.orm import Session
from app.core.logger import Logger as CoreLogger
from app.crud.social_crud import SocialCrud
from app.schemas.tracking import PostViewTrackingPayload, ProfileViewTrackingPayload
from app.models.user import Users

class TrackingDomain:

    def __init__(self, db: Session):
        self.db: Session = db
        self.logger: Logger = CoreLogger.get_logger()
        self.social_crud: SocialCrud = SocialCrud(db=self.db)

    def track_profile_view(self, payload: ProfileViewTrackingPayload, user: Optional[Users] = None):
        try:
            profile_user_id = payload.profile_user_id
            viewer_user_id = user.id if user else None
            result = self.social_crud.create_profile_view_tracking(profile_user_id, viewer_user_id)
            if not result:
                self.logger.error(f"Error tracking profile view: {result}")
                raise Exception(f"Error tracking profile view: {result}")
        except Exception as e:
            self.logger.error(f"Error tracking profile view: {e}")
            raise e

    def track_post_view(self, payload: PostViewTrackingPayload):
        try:
            post_id = payload.post_id
            viewer_user_id = payload.user_id
            watched_duration_sec = payload.watched_duration_sec
            video_duration_sec = payload.video_duration_sec

            result = self.social_crud.create_post_view_tracking(
                post_id=post_id,
                viewer_user_id=viewer_user_id,
                watched_duration_sec=watched_duration_sec,
                video_duration_sec=video_duration_sec,
            )
            if not result:
                self.logger.error(f"Error tracking post view: {result}")
                raise Exception(f"Error tracking post view: {result}")
        except Exception as e:
            self.logger.error(f"Error tracking post view: {e}")
            raise e