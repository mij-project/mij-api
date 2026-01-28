from sqlalchemy.orm import Session
from logging import Logger
from uuid import UUID
from app.core.logger import Logger as CoreLogger
from app.models.social import UserRecommendations

class UserRecommendationsCrud:
    def __init__(self, db: Session):
        self.db: Session = db
        self.logger: Logger = CoreLogger.get_logger()

    def get_user_recommendations(self, user_id: UUID) -> dict:
        
        result = {
            "creators": [],
            "categories": [],
        }

        try:
            recs = self.db.query(UserRecommendations).filter(UserRecommendations.user_id == user_id).all()
            if not recs:
                return result
            for rec in recs:
                if rec.type == 1:
                    result["creators"].extend(rec.payload)
                elif rec.type == 2:
                    result["categories"].extend(rec.payload)
        except Exception as e:
            self.logger.error(f"Error getting user recommendations: {e}")
        return result