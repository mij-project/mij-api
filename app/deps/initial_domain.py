from app.domain.tracking.tracking_domain import TrackingDomain
from app.domain.bulk_message.bulk_message import BulkMessageDomain
from app.domain.shorts.shorts_domain import ShortsDomain
from app.db.base import get_db
from sqlalchemy.orm import Session
from fastapi import Depends


def initial_tracking_domain(db: Session = Depends(get_db)) -> TrackingDomain:
    return TrackingDomain(db=db)


def initial_bulk_message_domain(db: Session = Depends(get_db)) -> BulkMessageDomain:
    return BulkMessageDomain(db=db)


def initial_shorts_domain(db: Session = Depends(get_db)) -> ShortsDomain:
    return ShortsDomain(db=db)
