from sqlalchemy.orm import Session
from uuid import UUID
from sqlalchemy import func

def get_total_sales(db: Session, user_id: UUID) -> int:
    """
    ユーザーの総売上を取得
    """
    
    return 0
