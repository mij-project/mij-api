from datetime import datetime, timezone
import os
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import Notifications, Profiles, UserSettings
from app.models.social import Follows
from app.models.user import Users
from uuid import UUID
from typing import List

from app.schemas.notification import NotificationType
from app.schemas.user_settings import UserSettingsType
from app.services.email.send_email import send_follow_notification_email

def get_follower_count(db: Session, user_id: UUID) -> dict:
    """
    フォロワー数を取得
    """
    followers_count = db.query(Follows).filter(Follows.creator_user_id == user_id).count()
    following_count = db.query(Follows).filter(Follows.follower_user_id == user_id).count()
    return {
        "followers_count": followers_count,
        "following_count": following_count
    }

def create_follow(db: Session, follower_user_id: UUID, creator_user_id: UUID) -> Follows:
    """
    フォロー関係を作成
    """
    follow = Follows(
        follower_user_id=follower_user_id,
        creator_user_id=creator_user_id
    )
    db.add(follow)
    db.commit()
    db.refresh(follow)
    return follow

def delete_follow(db: Session, follower_user_id: UUID, creator_user_id: UUID) -> bool:
    """
    フォロー関係を削除
    """
    follow = (
        db.query(Follows)
        .filter(
            and_(
                Follows.follower_user_id == follower_user_id,
                Follows.creator_user_id == creator_user_id
            )
        )
        .first()
    )
    
    if follow:
        db.delete(follow)
        db.commit()
        return True
    
    return False

def is_following(db: Session, follower_user_id: UUID, creator_user_id: UUID) -> bool:
    """
    フォロー関係があるかチェック
    """
    follow = (
        db.query(Follows)
        .filter(
            and_(
                Follows.follower_user_id == follower_user_id,
                Follows.creator_user_id == creator_user_id
            )
        )
        .first()
    )
    return follow is not None

def get_followers(
    db: Session, 
    user_id: UUID, 
    skip: int = 0, 
    limit: int = 20
) -> List[Users]:
    """
    フォロワー一覧を取得
    """
    return (
        db.query(Users)
        .join(Follows, Follows.follower_user_id == Users.id)
        .filter(Follows.creator_user_id == user_id)
        .order_by(Follows.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

def get_following(
    db: Session, 
    user_id: UUID, 
    skip: int = 0, 
    limit: int = 20
) -> List[Users]:
    """
    フォロー中のユーザー一覧を取得
    """
    return (
        db.query(Users)
        .join(Follows, Follows.creator_user_id == Users.id)
        .filter(Follows.follower_user_id == user_id)
        .order_by(Follows.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

def toggle_follow(db: Session, follower_user_id: UUID, creator_user_id: UUID) -> dict:
    """
    フォローのトグル（フォロー/フォロー解除）
    """
    if follower_user_id == creator_user_id:
        return {"following": False, "message": "自分自身をフォローすることはできません"}
    
    existing_follow = (
        db.query(Follows)
        .filter(
            and_(
                Follows.follower_user_id == follower_user_id,
                Follows.creator_user_id == creator_user_id
            )
        )
        .first()
    )
    
    if existing_follow:
        # フォロー解除
        db.delete(existing_follow)
        db.commit()
        return {"following": False, "message": "フォローを解除しました"}
    else:
        # フォロー
        follow = Follows(follower_user_id=follower_user_id, creator_user_id=creator_user_id)
        db.add(follow)
        db.commit()
        add_notification_follow(db, follower_user_id, creator_user_id)
        add_mail_notification_follow(db, follower_user_id, creator_user_id)
        return {"following": True, "message": "フォローしました"}

def add_notification_follow(db: Session, follower_user_id: UUID, creator_user_id: UUID) -> None:
    """
    フォロー通知を追加
    """
    try:
        follower_profile = db.query(Profiles).filter(Profiles.user_id == follower_user_id).first()
        
        notification = Notifications(
            user_id=creator_user_id,
            type=NotificationType.USERS,
            payload={
                "title": f"{follower_profile.username} があなたをフォローしました",
                "subtitle": f"{follower_profile.username} があなたをフォローしました",
                "avatar": follower_profile.avatar_url,
                "redirect_url": f"/profile/username={follower_profile.username}"
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
        print(f"Add notification follow error: {e}")
        pass

def add_mail_notification_follow(db: Session, follower_user_id: UUID, creator_user_id: UUID) -> None:
    """
    フォロー通知メールを追加
    """
    try:
        user = (
            db.query(
                Users,
                Profiles,
                UserSettings.settings
            )
            .join(Profiles, Users.id == Profiles.user_id)
            .outerjoin(
                UserSettings,
                and_(
                    Users.id == UserSettings.user_id,
                    UserSettings.type == UserSettingsType.EMAIL,
                ),
            )
            .filter(Users.id == creator_user_id)
            .first()
        )
        follower_profile = db.query(Profiles).filter(Profiles.user_id == follower_user_id).first()
        if (not user.settings) or (user.settings is None) or (user.settings.get("follow", True) == True):
            send_follow_notification_email(user.Users.email, user.Profiles.username, follower_profile.username, f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp')}/profile?username={follower_profile.username}")
    except Exception as e:
        db.rollback()
        print(f"Add mail notification follow error: {e}")
        pass