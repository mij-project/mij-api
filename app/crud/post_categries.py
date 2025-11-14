from sqlalchemy.orm import Session
from app.models.post_categories import PostCategories

def get_post_categories(db: Session, post_id: str) -> list[PostCategories]:
    category_records = db.query(PostCategories).filter(PostCategories.post_id == post_id).all()
    return category_records