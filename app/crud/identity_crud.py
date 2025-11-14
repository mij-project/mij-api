from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.identity import IdentityVerifications, IdentityDocuments
from app.constants.enums import IdentityKind
from datetime import datetime
from sqlalchemy import desc, asc
from sqlalchemy.orm import joinedload
from app.models.notifications import Notifications
from app.models.user import Users
from app.models.profiles import Profiles
from typing import Optional, List

from app.schemas.notification import NotificationType

def create_identity_verification(db: Session, user_id: str, status: int) -> IdentityVerifications:
    """
    認証情報作成

    Args:
        db (Session): データベースセッション
        user_id (str): ユーザーID
        status (int): ステータス

    Returns:
        IdentityVerifications: 認証情報
    """
    db_verification = IdentityVerifications(
        user_id=user_id,
        status=status,
        checked_at=None,
        notes=None
    )
    db.add(db_verification)
    db.flush()  # IDを取得するためにflush
    return db_verification

def get_identity_verification_by_user_id(db: Session, user_id: str) -> IdentityVerifications:
    """
    ユーザーIDによる認証情報取得

    Args:
        db (Session): データベースセッション
        user_id (str): ユーザーID

    Returns:
        IdentityVerifications: 認証情報
    """
    return db.query(IdentityVerifications).filter(IdentityVerifications.user_id == user_id).first()


def create_identity_document(db: Session, verification_id: str, kind: int, storage_key: str) -> IdentityDocuments:
    """
    認証情報作成

    Args:
        db (Session): データベースセッション
        verification_id (str): 認証ID
        kind (int): 種類
        storage_key (str): ストレージキー

    Returns:
        IdentityDocuments: 認証情報
    """
    if kind == "front":
        kind = IdentityKind.FRONT
    elif kind == "back":
        kind = IdentityKind.BACK
    elif kind == "selfie":
        kind = IdentityKind.SELFIE

    db_document = IdentityDocuments(
        verification_id=verification_id,
        kind=kind,
        storage_key=storage_key
    )
    db.add(db_document)
    db.flush()
    return db_document

def update_identity_verification(db: Session, verification_id: str, status: int, checked_at: datetime) -> IdentityVerifications:

    """
    認証情報更新

    Args:
        db (Session): データベースセッション
        verification_id (str): 認証ID
        status (int): ステータス
        checked_at (datetime): 確認日時

    Returns:
        IdentityVerifications: 認証情報
    """
    db_verification = db.query(IdentityVerifications).filter(IdentityVerifications.id == verification_id).first()
    db_verification.status = status
    db_verification.checked_at = checked_at
    db.commit()
    db.refresh(db_verification)
    return db_verification


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
        verification.updated_at = datetime.utcnow()

        db.commit()
        return True
    except Exception as e:
        print(f"Update identity verification status error: {e}")
        db.rollback()
        return False


def approve_identity_verification(
    db: Session,
    verification_id: str,
    admin_id: str,
    notes: Optional[str] = None
) -> Optional[IdentityVerifications]:
    """
    身分証明を承認する

    Args:
        db: データベースセッション
        verification_id: 審査ID
        admin_id: 承認した管理者のID
        notes: 審査メモ

    Returns:
        IdentityVerifications: 更新された審査情報、失敗時はNone
    """
    try:
        verification = db.query(IdentityVerifications).filter(
            IdentityVerifications.id == verification_id
        ).first()

        if not verification or verification.status != 1:  # 1 = WAITING (承認待ち)
            return None

        # ユーザーのroleを2 (creator)に更新
        user = db.query(Users).filter(Users.id == verification.user_id).first()
        if user:
            user.role = 2
            user.is_identity_verified = True
            user.identity_verified_at = datetime.utcnow()

        # 審査情報を更新
        verification.status = 3  # APPROVED
        verification.approved_by = admin_id
        verification.checked_at = datetime.utcnow()
        if notes:
            verification.notes = notes

        db.commit()
        db.refresh(verification)
        return verification
    except Exception as e:
        print(f"Approve identity verification error: {e}")
        db.rollback()
        return None


def reject_identity_verification(
    db: Session,
    verification_id: str,
    admin_id: str,
    notes: Optional[str] = None
) -> Optional[IdentityVerifications]:
    """
    身分証明を拒否する

    Args:
        db: データベースセッション
        verification_id: 審査ID
        admin_id: 拒否した管理者のID
        notes: 拒否理由

    Returns:
        IdentityVerifications: 更新された審査情報、失敗時はNone
    """
    try:
        verification = db.query(IdentityVerifications).filter(
            IdentityVerifications.id == verification_id
        ).first()

        if not verification or verification.status != 1:  # 1 = WAITING (承認待ち)
            return None

        # 審査情報を更新
        verification.status = 2  # REJECTED
        verification.approved_by = admin_id
        verification.checked_at = datetime.utcnow()
        if notes:
            verification.notes = notes

        db.commit()
        db.refresh(verification)
        return verification
    except Exception as e:
        print(f"Reject identity verification error: {e}")
        db.rollback()
        return None

def add_notification_for_identity_verification(db: Session, user_id: str, status: int) -> bool:
    """
    身分証明のステータスを更新

    Args:
        db: データベースセッション
        user_id: ユーザーID
        status: ステータス
    """
    try:
        profiles = db.query(Profiles).filter(Profiles.user_id == user_id).first()
        if not profiles:
            raise Exception("Profileが見つかりません")
        if status == "approved":
            try:
                notification = Notifications(
                    user_id=user_id,
                    type=NotificationType.USERS,
                    payload={
                        "title": "身分証明の審査が承認されました",
                        "subtitle": "身分証明の審査が承認されました",
                        "avatar": profiles.avatar_url,
                        "redirect_url": f"/profile?username={profiles.username}",
                    },
                    is_read=False,
                    read_at=None,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                db.add(notification)
                db.commit()
            except Exception as e:
                print(f"Add notification for identity verification error: {e}")
                db.rollback()
                pass
        elif status == "rejected":
            try:
                notification = Notifications(
                    user_id=user_id,
                    type=NotificationType.USERS,
                    payload={
                        "title": "身分証明の審査が拒否されました",
                        "subtitle": "身分証明の審査が拒否されました",
                        "avatar": profiles.avatar_url,
                        "redirect_url": f"/profile?username={profiles.username}",
                    },
                    is_read=False,
                    read_at=None,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                db.add(notification)
                db.commit()
            except Exception as e:
                print(f"Add notification for identity verification error: {e}")
                db.rollback()
                pass
    except Exception as e:
        print(f"Add notification for identity verification error: {e}")
        pass