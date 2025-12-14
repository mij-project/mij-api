from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, asc
from datetime import datetime, timezone

from app.models.notifications import Notifications
from app.models.user import Users
from app.models.creators import Creators
from app.models.identity import IdentityVerifications
from app.models.posts import Posts
from app.models.profiles import Profiles
from app.models.media_assets import MediaAssets
from app.models.admins import Admins
from app.models.profile_image_submissions import ProfileImageSubmissions
from app.constants.enums import PostStatus, MediaAssetStatus
import os

from app.schemas.notification import NotificationType
from app.core.logger import Logger
logger = Logger.get_logger()

CDN_URL = os.getenv("CDN_BASE_URL")

"""管理機能用のCRUD操作クラス"""


# ==================== Admin CRUD Functions ====================

def get_admin_by_id(db: Session, admin_id: str) -> Optional[Admins]:
    """
    IDで管理者を取得

    Args:
        db: データベースセッション
        admin_id: 管理者ID

    Returns:
        Optional[Admins]: 管理者情報
    """
    try:
        admin = db.query(Admins).filter(
            Admins.id == admin_id,
            Admins.deleted_at.is_(None)
        ).first()
        return admin
    except Exception as e:
        logger.error(f"Get admin by id error: {e}")
        return None


def get_admin_by_email(db: Session, email: str) -> Optional[Admins]:
    """
    メールアドレスで管理者を取得

    Args:
        db: データベースセッション
        email: メールアドレス

    Returns:
        Optional[Admins]: 管理者情報
    """
    try:
        admin = db.query(Admins).filter(
            Admins.email == email,
            Admins.deleted_at.is_(None)
        ).first()
        return admin
    except Exception as e:
        logger.error(f"Get admin by email error: {e}")
        return None


def create_admin(
    db: Session,
    email: str,
    password_hash: str,
    role: int = 1,
    status: int = 1
) -> Optional[Admins]:
    """
    新しい管理者を作成

    Args:
        db: データベースセッション
        email: メールアドレス
        password_hash: ハッシュ化されたパスワード
        role: 役割（デフォルト: 1）
        status: ステータス（デフォルト: 1=有効）

    Returns:
        Optional[Admins]: 作成された管理者情報
    """
    try:
        # メールアドレスの重複チェック
        existing_admin = get_admin_by_email(db, email)
        if existing_admin:
            return None

        new_admin = Admins(
            email=email,
            password_hash=password_hash,
            role=role,
            status=status,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        db.add(new_admin)
        db.commit()
        db.refresh(new_admin)

        return new_admin
    except Exception as e:
        logger.error(f"Create admin error: {e}")
        db.rollback()
        return None
def get_dashboard_info(db: Session) -> Dict[str, Any]:
    """
    ダッシュボード統計情報を取得
    
    Args:
        db: データベースセッション
        
    Returns:
        Dict[str, Any]: 統計情報
    """
    try:
        # 基本統計
        total_users = db.query(Users).count()
        total_posts = db.query(Posts).count()
        
        # 身分証申請中件数（status=1が申請中）
        pending_identity_verifications = (
            db.query(IdentityVerifications)
            .filter(IdentityVerifications.status == 1).count()
        )
        
        # クリエイター申請中件数（status=1が申請中）
        pending_creator_applications = (
            db.query(Creators)
            .filter(Creators.status == 1)
            .count()
        )
        
        # 投稿申請中件数（審査待ちの投稿があると仮定してstatus=1）
        pending_post_reviews = (
            db.query(Posts)
            .filter(Posts.status == 1)
            .count()
        )

        # プロフィール画像審査中件数（status=1が審査待ち）
        pending_profile_reviews = (
            db.query(ProfileImageSubmissions)
            .filter(ProfileImageSubmissions.status == 1)
            .count()
        )

        # 月間売上（仮の値 - 実際のOrdersテーブルから計算する場合）
        monthly_revenue = 100000

        # アクティブな購読数
        active_subscriptions = 0

        return {
            "total_users": total_users,
            "total_posts": total_posts,
            "pending_identity_verifications": pending_identity_verifications,
            "pending_creator_applications": pending_creator_applications,
            "pending_post_reviews": pending_post_reviews,
            "pending_profile_reviews": pending_profile_reviews,
            "monthly_revenue": monthly_revenue,
            "active_subscriptions": active_subscriptions
        }
    except Exception as e:
        logger.error(f"Dashboard stats error: {e}")
        # エラー時はデフォルト値を返す
        return {
            "total_users": 0,
            "total_posts": 0,
            "pending_identity_verifications": 0,
            "pending_creator_applications": 0,
            "pending_post_reviews": 0,
            "pending_profile_reviews": 0,
            "monthly_revenue": 0,
            "active_subscriptions": 0
        }


def get_users_paginated(
    db: Session,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    role: Optional[str] = None,
    sort: str = "created_at_desc"
) -> tuple[List[Users], int]:
    """
    ページネーション付きユーザー一覧を取得
    
    Args:
        db: データベースセッション
        page: ページ番号
        limit: 1ページあたりの件数
        search: 検索クエリ
        role: ロールフィルタ
        sort: ソート順
        
    Returns:
        tuple[List[Users], int]: (ユーザーリスト, 総件数)
    """
    skip = (page - 1) * limit
    
    query = db.query(Users).options(joinedload(Users.profile))
    
    if search:
        query = query.join(Profiles).filter(
            (Profiles.username.ilike(f"%{search}%")) |
            (Users.email.ilike(f"%{search}%"))
        )
    
    if role:
        role_map = {"user": 1, "creator": 2, "admin": 3}
        query = query.filter(Users.role == role_map.get(role))
    
    # ソート処理
    if sort == "created_at_desc":
        query = query.order_by(desc(Users.created_at))
    elif sort == "created_at_asc":
        query = query.order_by(asc(Users.created_at))
    elif sort == "username_asc":
        query = query.join(Profiles).order_by(asc(Profiles.username))
    elif sort == "username_desc":
        query = query.join(Profiles).order_by(desc(Profiles.username))
    elif sort == "email_asc":
        query = query.order_by(asc(Users.email))
    else:
        query = query.order_by(desc(Users.created_at))
    
    total = query.count()
    users = query.offset(skip).limit(limit).all()
    
    return users, total


def get_creator_applications_paginated(
    db: Session,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    sort: str = "created_at_desc"
) -> tuple[List[Creators], int]:
    """
    ページネーション付きクリエイター申請一覧を取得
    
    Args:
        db: データベースセッション
        page: ページ番号
        limit: 1ページあたりの件数
        search: 検索クエリ
        status: ステータスフィルタ
        sort: ソート順
        
    Returns:
        tuple[List[Creators], int]: (申請リスト, 総件数)
    """
    skip = (page - 1) * limit
    
    query = db.query(Creators).join(Users).options(joinedload(Creators.user))
    
    if search:
        query = query.join(Profiles).filter(
            (Profiles.username.ilike(f"%{search}%")) |
            (Users.email.ilike(f"%{search}%"))
        )
    
    if status:
        status_map = {"pending": 1, "approved": 2, "rejected": 3}
        query = query.filter(Creators.status == status_map.get(status, 1))
    
    # ソート処理
    if sort == "created_at_desc":
        query = query.order_by(desc(Creators.created_at))
    elif sort == "created_at_asc":
        query = query.order_by(asc(Creators.created_at))
    elif sort == "user_name_asc":
        query = query.join(Profiles).order_by(asc(Profiles.username))
    elif sort == "user_name_desc":
        query = query.join(Profiles).order_by(desc(Profiles.username))
    else:
        query = query.order_by(desc(Creators.created_at))
    
    total = query.count()
    applications = query.offset(skip).limit(limit).all()
    
    return applications, total


def get_identity_verifications_paginated(
    db: Session,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    sort: str = "created_at_desc"
) -> tuple[List[IdentityVerifications], int]:
    """
    ページネーション付き身分証明審査一覧を取得
    
    Args:
        db: データベースセッション
        page: ページ番号
        limit: 1ページあたりの件数
        search: 検索クエリ
        status: ステータスフィルタ
        sort: ソート順
        
    Returns:
        tuple[List[IdentityVerifications], int]: (審査リスト, 総件数)
    """
    skip = (page - 1) * limit
    
    query = db.query(IdentityVerifications).join(Users).options(joinedload(IdentityVerifications.user))
    
    if search:
        query = query.join(Profiles).filter(
            (Profiles.username.ilike(f"%{search}%")) |
            (Users.email.ilike(f"%{search}%"))
        )
    
    if status:
        status_map = {"pending": 1, "approved": 2, "rejected": 3}
        query = query.filter(IdentityVerifications.status == status_map.get(status, 1))
    
    # ソート処理
    if sort == "created_at_desc":
        query = query.order_by(desc(IdentityVerifications.checked_at))
    elif sort == "created_at_asc":
        query = query.order_by(asc(IdentityVerifications.checked_at))
    elif sort == "user_name_asc":
        query = query.join(Profiles).order_by(asc(Profiles.username))
    elif sort == "user_name_desc":
        query = query.join(Profiles).order_by(desc(Profiles.username))
    else:
        query = query.order_by(desc(IdentityVerifications.checked_at))
    
    total = query.count()
    verifications = query.offset(skip).limit(limit).all()
    
    return verifications, total


def get_posts_paginated(
    db: Session,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    sort: str = "created_at_desc"
) -> tuple[List[Posts], int]:
    """
    ページネーション付き投稿一覧を取得
    
    Args:
        db: データベースセッション
        page: ページ番号
        limit: 1ページあたりの件数
        search: 検索クエリ
        status: ステータスフィルタ
        sort: ソート順
        
    Returns:
        tuple[List[Posts], int]: (投稿リスト, 総件数)
    """
    skip = (page - 1) * limit
    
    query = db.query(Posts).join(Users, Posts.creator_user_id == Users.id).options(joinedload(Posts.creator))
    
    if search:
        query = query.filter(
            Posts.description.ilike(f"%{search}%")
        )
    
    if status:
        status_map = {
            "approved": PostStatus.APPROVED, 
            "rejected": PostStatus.REJECTED, 
            "resubmit": PostStatus.RESUBMIT,
            "deleted": PostStatus.DELETED,
            "pending": PostStatus.PENDING,
            "converting": PostStatus.CONVERTING,
        }
        query = query.filter(Posts.status == status_map.get(status, PostStatus.PENDING))
    
    # ソート処理
    if sort == "created_at_desc":
        query = query.order_by(desc(Posts.created_at))
    elif sort == "created_at_asc":
        query = query.order_by(asc(Posts.created_at))
    elif sort == "description_asc":
        query = query.order_by(asc(Posts.description))
    elif sort == "description_desc":
        query = query.order_by(desc(Posts.description))
    else:
        query = query.order_by(desc(Posts.created_at))
    
    total = query.count()
    posts = query.offset(skip).limit(limit).all()
    
    return posts, total


def update_user_status(db: Session, user_id: str, status: str) -> bool:
    """
    ユーザーのステータスを更新
    
    Args:
        db: データベースセッション
        user_id: ユーザーID
        status: 新しいステータス
        
    Returns:
        bool: 更新成功フラグ
    """
    try:
        user = db.query(Users).filter(Users.id == user_id).first()
        if not user:
            return False
        
        # ステータス更新（実装に応じて調整）
        user.status = 2 if status == "suspended" else 1
        user.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Update user status error: {e}")
        db.rollback()
        return False


def update_creator_application_status(db: Session, application_id: str, status: str) -> bool:
    """
    クリエイター申請のステータスを更新
    
    Args:
        db: データベースセッション
        application_id: 申請ID
        status: 新しいステータス (approved/rejected)
        
    Returns:
        bool: 更新成功フラグ
    """
    try:
        application = db.query(Creators).filter(Creators.user_id == application_id).first()
        if not application or application.status != 1:  # 1 = pending
            return False
        
        # 申請ステータス更新
        status_map = {"approved": 2, "rejected": 3}
        application.status = status_map[status]
        application.updated_at = datetime.now(timezone.utc)
        
        # 承認の場合、ユーザーのロールをクリエイターに更新
        if status == "approved":
            user = db.query(Users).filter(Users.id == application.user_id).first()
            if user:
                user.role = 2  # 2 = creator
                user.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Update creator application status error: {e}")
        db.rollback()
        return False


def update_identity_verification_status(db: Session, verification_id: str, status: str) -> bool:
    """
    身分証明のステータスを更新
    
    Args:
        db: データベースセッション
        verification_id: 審査ID
        status: 新しいステータス (approved/rejected)
        
    Returns:
        bool: 更新成功フラグ
    """
    try:
        verification = db.query(IdentityVerifications).filter(
            IdentityVerifications.id == verification_id
        ).first()
        if not verification or verification.status != 1:  # 1 = pending
            return False
        
        # 審査ステータス更新
        status_map = {"approved": 2, "rejected": 3}
        verification.status = status_map[status]
        verification.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Update identity verification status error: {e}")
        db.rollback()
        return False


def update_post_status(db: Session, post_id: str, status: str) -> bool:
    """
    投稿のステータスを更新
    
    Args:
        db: データベースセッション
        post_id: 投稿ID
        status: 新しいステータス
        
    Returns:
        bool: 更新成功フラグ
    """
    try:
        post = db.query(Posts).filter(Posts.id == post_id).first()
        if not post:
            return False
        
        status_map = {
            "approved": PostStatus.APPROVED, 
            "rejected": PostStatus.REJECTED, 
            "resubmit": PostStatus.RESUBMIT,
            "deleted": PostStatus.DELETED,
            "pending": PostStatus.PENDING,
            "unpublished": PostStatus.UNPUBLISHED,
        }
        post.status = status_map.get(status, PostStatus.PENDING)
        if status == "unpublished":
            post.deleted_at = None
        post.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Update post status error: {e}")
        db.rollback()
        return False


def reject_post_with_comments(
    db: Session,
    post_id: str,
    post_reject_comment: str,
    media_reject_comments: Optional[Dict[str, str]] = None
) -> bool:
    """
    投稿を拒否し、拒否理由をpostsとmedia_assetsに保存

    Args:
        db: データベースセッション
        post_id: 投稿ID
        post_reject_comment: 投稿全体に対する拒否理由
        media_reject_comments: メディア別の拒否理由 {media_asset_id: comment}

    Returns:
        bool: 更新成功フラグ
    """
    try:
        # 投稿を取得
        post = db.query(Posts).filter(Posts.id == post_id).first()
        if not post:
            return False

        # 投稿のステータスを拒否に更新し、拒否理由を保存
        post.status = PostStatus.REJECTED
        post.reject_comments = post_reject_comment
        post.updated_at = datetime.now(timezone.utc)

        # メディア別の拒否理由を保存
        if media_reject_comments:
            for media_id, comment in media_reject_comments.items():
                media_asset = db.query(MediaAssets).filter(
                    MediaAssets.id == media_id,
                    MediaAssets.post_id == post_id
                ).first()
                if media_asset:
                    media_asset.reject_comments = comment
                    media_asset.status = MediaAssetStatus.REJECTED

        db.commit()
        return True
    except Exception as e:
        logger.error(f"Reject post with comments error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False

def add_notification_for_creator_application(
    db: Session, 
    application_id: str, 
    type: str
) -> bool:
    """
    クリエイター申請に対する通知を追加
    
    Args:
        db: データベースセッション
        application_id: 申請ID
        status: ステータス
    """
    try:
        if type == "approved":
            try:
                notification = Notifications(
                    user_id=application_id,
                    type=NotificationType.USERS,
                    payload={
                        "title": "クリエイター申請が承認されました",
                        "subtitle": "クリエイター申請が承認されました",
                        "message": "クリエイター申請が承認されました",
                        "avatar": None,
                        "redirect_url": f"/account",
                    },
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    is_read=False,
                    read_at=None,
                )
                db.add(notification)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Add notification for creator application approved error: {e}")
                pass
        
        elif type == "rejected":
            try:
                notification = Notifications(
                    user_id=application_id,
                    type=NotificationType.USERS,
                    payload={
                        "title": "クリエイター申請が拒否されました",
                        "subtitle": "クリエイター申請が拒否されました",
                        "avatar": None,
                        "redirect_url": f"/account",
                    },
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    is_read=False,
                    read_at=None,
                )
                db.add(notification)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Add notification for creator application rejected error: {e}")
                pass
    except Exception as e:
        logger.error(f"Add notification for creator application error: {e}")
        pass