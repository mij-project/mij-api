from sqlalchemy.orm import Session
from app.models.creator_type import CreatorType
from typing import List

def create_creator_type(db: Session, creator_type: CreatorType) -> CreatorType:
    """
    クリエイタータイプを作成
    """
    db.add(creator_type)
    db.commit()
    db.refresh(creator_type)