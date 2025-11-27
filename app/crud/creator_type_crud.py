from sqlalchemy.orm import Session
from app.models.creator_type import CreatorType
from typing import List
from app.models.gender import Gender
from uuid import UUID

def create_creator_type(db: Session, creator_type: CreatorType) -> CreatorType:
    """
    クリエイタータイプを作成
    """
    db.add(creator_type)
    db.commit()
    db.refresh(creator_type)

def get_creator_type_by_user_id(db: Session, user_id: UUID) -> List[str]:
    """
    ユーザーIDに基づいてクリエイタータイプを取得
    """
    rows = (
        db.query(Gender.slug)
        .join(CreatorType, CreatorType.gender_id == Gender.id)
        .filter(CreatorType.user_id == user_id)
        .all()
    )
    return [slug for (slug,) in rows]

def delete_creator_type_by_user_id(db: Session, user_id: UUID) -> bool:
    """
    ユーザーIDに基づいてクリエイタータイプを削除
    """
    db.query(CreatorType).filter(CreatorType.user_id == user_id).delete()
    db.commit()
    return True