from common.logger import Logger
from common.db_session import get_db
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from models.creators import Creators
from models.events import Events
from models.events import UserEvents


class EndPreregistationEvent:
    def __init__(self):
        self.logger = Logger.get_logger()
        self.db: Session = next(get_db())
        self.now = datetime.now(timezone.utc)
        self.release_date = datetime(2025, 12, 15, tzinfo=timezone.utc)

    def exec(self):
        self.logger.info("Start End Preregistation Event")

        creators = self._query_preregistration_creators()
        if not creators:
            self.logger.info("No preregistration creators found")
            return
        for creator in creators:
            self._process_creator(creator[0])
        self.logger.info("End End Preregistation Event")

    def _query_preregistration_creators(self):
        return (
            self.db.query(
                Creators,
                Events,
                UserEvents,
            )
            .join(Events, UserEvents.event_id == Events.id)
            .join(Creators, UserEvents.user_id == Creators.user_id)
            .filter(
                Events.code == "pre-register",
            )
            .all()
        )

    def _process_creator(self, creator: Creators):
        try:
            end_date = None
            created_at = creator.created_at.replace(tzinfo=timezone.utc)
            if created_at < self.release_date:
                end_date = self.release_date + timedelta(days=30)
            else:
                end_date = created_at + timedelta(days=30)
            if end_date.date() > self.now.date():
                self.logger.info(
                    f"Creator {creator.user_id} still in preregistration event"
                )
                return
            creator = (
                self.db.query(Creators)
                .filter(Creators.user_id == creator.user_id)
                .first()
            )
            creator.platform_fee_percent = 10
            self.db.commit()
            self.logger.info(
                f"Creator {creator.user_id} platform fee percent updated to 10"
            )
            return
        except Exception as e:
            self.logger.error(f"Error processing creator {creator.user_id}: {e}")
            return
