from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.reservation_message import ReservationMessage

class ReservationMessageCrud:
    def __init__(self, db: Session):
        self.db = db

    def create_reservation_message(self, reservation_message: ReservationMessage) -> ReservationMessage:
        self.db.add(reservation_message)
        self.db.commit()
        self.db.refresh(reservation_message)
        return reservation_message