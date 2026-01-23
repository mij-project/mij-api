from app.domain.tracking.tracking_domain import TrackingDomain
from app.db.base import get_db
from sqlalchemy.orm import Session
from fastapi import Depends

def initial_tracking_domain(db: Session = Depends(get_db)) -> TrackingDomain:
    return TrackingDomain(db=db)