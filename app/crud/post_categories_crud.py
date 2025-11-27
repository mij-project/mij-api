from sqlalchemy.orm import Session
from uuid import UUID
from app.models.post_categories import PostCategories

def create_post_category(db: Session, post_category_data) -> PostCategories:
    """
    投稿に紐づくカテゴリを作成
    """
    db_post_category = PostCategories(**post_category_data)
    db.add(db_post_category)
    db.flush()
    return db_post_category

def delete_post_categories_by_post_id(db: Session, post_id: UUID):
    """
    投稿に紐づくカテゴリを投稿IDで削除
    """
    db.query(PostCategories).filter(PostCategories.post_id == post_id).delete()
    db.flush()
    return True