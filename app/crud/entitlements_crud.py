from sqlalchemy.orm import Session
from app.models.entitlements import Entitlements
from uuid import UUID

def check_entitlement(db: Session, user_id: UUID, post_id: UUID) -> bool:
    """
    視聴権利を確認
    """
    entitlement = db.query(Entitlements).filter(
        Entitlements.user_id == user_id,
        Entitlements.post_id == post_id
    ).first()
    return entitlement is not None