from sqlalchemy.orm import Session
from app.models.events import UserEvents

def create_user_event(db: Session, user_id: str, event_id: str) -> UserEvents:
    """
    ユーザーイベントを作成
    """
    user_event = UserEvents(user_id=user_id, event_id=event_id)
    db.add(user_event)
    db.flush()
    return user_event

def check_user_event_exists(db: Session, user_id: str, event_id: str) -> bool:
    """
    イベント存在判定
    """
    return db.query(UserEvents).filter(UserEvents.user_id == user_id, UserEvents.event_id == event_id).first() is not None