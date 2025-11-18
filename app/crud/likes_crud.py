from datetime import datetime, timezone
import os
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import Notifications, Profiles, UserSettings, Users
from app.models.social import Likes
from app.models.posts import Posts
from uuid import UUID
from typing import List

from app.schemas.notification import NotificationType
from app.schemas.user_settings import UserSettingsType
from app.services.email.send_email import send_like_notification_email

def get_likes_count(db: Session, post_id: UUID) -> int:
    """
    いいね数を取得
    """
    likes_count = db.query(Likes).filter(Likes.post_id == post_id).count()
    return likes_count

def create_like(db: Session, user_id: UUID, post_id: UUID) -> Likes:
    """
    いいねを作成
    """
    like = Likes(
        user_id=user_id,
        post_id=post_id
    )
    db.add(like)
    db.commit()
    db.refresh(like)
    return like

def delete_like(db: Session, user_id: UUID, post_id: UUID) -> bool:
    """
    いいねを削除
    """
    like = (
        db.query(Likes)
        .filter(
            and_(
                Likes.user_id == user_id,
                Likes.post_id == post_id
            )
        )
        .first()
    )
    
    if like:
        db.delete(like)
        db.commit()
        return True
    
    return False

def is_liked(db: Session, user_id: UUID, post_id: UUID) -> bool:
    """
    ユーザーが投稿をいいねしているかチェック
    """
    like = (
        db.query(Likes)
        .filter(
            and_(
                Likes.user_id == user_id,
                Likes.post_id == post_id
            )
        )
        .first()
    )
    return like is not None

def get_liked_posts_by_user_id(
    db: Session, 
    user_id: UUID, 
    skip: int = 0, 
    limit: int = 20
) -> List[Posts]:
    """
    ユーザーがいいねした投稿一覧を取得
    """
    return (
        db.query(Posts)
        .join(Likes)
        .filter(Likes.user_id == user_id)
        .order_by(Likes.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

def toggle_like(db: Session, user_id: UUID, post_id: UUID) -> dict:
    """
    いいねのトグル（追加/削除）
    """
    existing_like = (
        db.query(Likes)
        .filter(
            and_(
                Likes.user_id == user_id,
                Likes.post_id == post_id
            )
        )
        .first()
    )
    
    if existing_like:
        # いいね削除
        db.delete(existing_like)
        db.commit()
        return {"liked": False, "message": "いいねを取り消しました"}
    else:
        # いいね追加
        like = Likes(user_id=user_id, post_id=post_id)
        db.add(like)
        db.commit()
        add_notification_like(db, user_id, post_id)
        add_mail_notification_like(db, user_id, post_id)
        return {"liked": True, "message": "いいねしました"}

def add_notification_like(db: Session, user_id: UUID, post_id: UUID) -> None:
    """
    いいね通知を追加
    """
    try:
        post = db.query(Posts).filter(Posts.id == post_id).first()
        liked_user_profile = db.query(Profiles).filter(Profiles.user_id == user_id).first()
        notification = Notifications(
            user_id=post.creator_user_id,
            type=NotificationType.USERS,
            payload={
                "title": f"{liked_user_profile.username} があなたの投稿をいいねしました",
                "subtitle": f"{liked_user_profile.username} があなたの投稿をいいねしました",
                "avatar": liked_user_profile.avatar_url,
                "redirect_url": f"/post/detail?post_id={post.id}"
            },
            is_read=False,
            read_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(notification)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Add notification like error: {e}")
        pass

def add_mail_notification_like(db: Session, user_id: UUID, post_id: UUID) -> None:
    """
    いいね通知メールを追加
    """
    try:
        user = (
            db.query(
                Users,
                Profiles,
                Posts,
                UserSettings.settings
            )
            .join(Profiles, Users.id == Profiles.user_id)
            .join(Posts, Users.id == Posts.creator_user_id)
            .outerjoin(
                UserSettings,
                and_(
                    Users.id == UserSettings.user_id,
                    UserSettings.type == UserSettingsType.EMAIL,
                ),
            )
            .filter(Posts.id == post_id)
            .first()
        )
        liked_user_profile = db.query(Profiles).filter(Profiles.user_id == user_id).first()
        if (not user.settings) or (user.settings is None) or (user.settings.get("like", True) == True):
            send_like_notification_email(
                user.Users.email, 
                user.Profiles.username, 
                liked_user_profile.username, 
                f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp')}/post/detail?post_id={post_id}"
            )
    except Exception as e:
        print(f"Add mail notification like error: {e}")
        pass