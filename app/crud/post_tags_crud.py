from sqlalchemy.orm import Session
from uuid import UUID
from app.models.tags import PostTags

def create_post_tag(db: Session, post_tag_data) -> PostTags:
    """
    投稿に紐づくタグを作成
    """
    db_post_tag = PostTags(**post_tag_data)
    db.add(db_post_tag)
    db.flush()
    return db_post_tag

def delete_post_tags_by_post_id(db: Session, post_id: UUID):
    """
    投稿に紐づくタグを投稿IDで削除
    """
    db.query(PostTags).filter(PostTags.post_id == post_id).delete()
    db.flush()
    return True