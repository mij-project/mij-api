from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from app.models.social import Comments
from app.models.user import Users
from uuid import UUID
from typing import Optional, List
from datetime import datetime, timezone

def create_comment(
    db: Session, 
    post_id: UUID, 
    user_id: UUID, 
    body: str,
    parent_comment_id: Optional[UUID] = None
) -> Comments:
    """
    コメントを作成
    """
    comment = Comments(
        post_id=post_id,
        user_id=user_id,
        body=body,
        parent_comment_id=parent_comment_id,
        status=1
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment

def get_comments_by_post_id(
    db: Session, 
    post_id: UUID, 
    skip: int = 0, 
    limit: int = 50
) -> List[Comments]:
    """
    投稿のコメント一覧を取得（親コメントのみ）
    """
    return (
        db.query(Comments)
        .filter(
            and_(
                Comments.post_id == post_id,
                Comments.parent_comment_id.is_(None),
                Comments.deleted_at.is_(None)
            )
        )
        .order_by(desc(Comments.created_at))
        .offset(skip)
        .limit(limit)
        .all()
    )

def get_replies_by_parent_id(
    db: Session, 
    parent_comment_id: UUID,
    skip: int = 0,
    limit: int = 20
) -> List[Comments]:
    """
    返信コメントを取得
    """
    return (
        db.query(Comments)
        .filter(
            and_(
                Comments.parent_comment_id == parent_comment_id,
                Comments.deleted_at.is_(None)
            )
        )
        .order_by(Comments.created_at)
        .offset(skip)
        .limit(limit)
        .all()
    )

def get_comment_by_id(db: Session, comment_id: UUID) -> Optional[Comments]:
    """
    コメントをIDで取得
    """
    return (
        db.query(Comments)
        .filter(
            and_(
                Comments.id == comment_id,
                Comments.deleted_at.is_(None)
            )
        )
        .first()
    )

def update_comment(
    db: Session, 
    comment_id: UUID, 
    body: str,
    user_id: UUID
) -> Optional[Comments]:
    """
    コメントを更新（自分のコメントのみ）
    """
    comment = (
        db.query(Comments)
        .filter(
            and_(
                Comments.id == comment_id,
                Comments.user_id == user_id,
                Comments.deleted_at.is_(None)
            )
        )
        .first()
    )
    
    if comment:
        comment.body = body
        comment.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(comment)
    
    return comment

def delete_comment(
    db: Session, 
    comment_id: UUID, 
    user_id: UUID
) -> bool:
    """
    コメントを削除（論理削除）
    """
    comment = (
        db.query(Comments)
        .filter(
            and_(
                Comments.id == comment_id,
                Comments.user_id == user_id,
                Comments.deleted_at.is_(None)
            )
        )
        .first()
    )
    
    if comment:
        comment.deleted_at = datetime.now(timezone.utc)
        db.commit()
        return True
    
    return False

def get_comments_count_by_post_id(db: Session, post_id: UUID) -> int:
    """
    投稿のコメント数を取得
    """
    return (
        db.query(Comments)
        .filter(
            and_(
                Comments.post_id == post_id,
                Comments.deleted_at.is_(None)
            )
        )
        .count()
    )