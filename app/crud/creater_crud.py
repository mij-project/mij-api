from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import distinct, exists, select, func, and_, case
from uuid import UUID
from datetime import datetime
from app.models.creators import Creators
from app.models.posts import Posts
from app.models.user import Users
from app.models.identity import IdentityVerifications, IdentityDocuments
from app.schemas.creator import CreatorCreate, CreatorUpdate, IdentityVerificationCreate, IdentityDocumentCreate
from app.constants.enums import CreatorStatus, VerificationStatus, AccountType
from app.models.profiles import Profiles
from sqlalchemy import desc
from app.models.social import Follows, Likes

def create_creator(db: Session, creator_create: dict) -> Creators:
    db_creator = Creators(**creator_create)
    db.add(db_creator)
    db.commit()
    db.refresh(db_creator)
    return db_creator

def update_creator_status(db: Session, user_id: UUID, status: CreatorStatus) -> Creators:
    """
    クリエイターステータスを更新する
    """
    creator = db.scalar(select(Creators).where(Creators.user_id == user_id))
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")
    
    creator.status = status
    return creator

def update_creator(db: Session, user_id: UUID, creator_update: CreatorUpdate) -> Creators:
    """
    クリエイター情報を更新する
    
    Args:
        db: データベースセッション
        user_id: ユーザーID
        creator_update: クリエイター更新情報
    """
    creator = db.scalar(select(Creators).where(Creators.user_id == user_id))
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")
    
    update_data = creator_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(creator, field, value)
    
    db.commit()
    db.refresh(creator)
    return creator

def get_creator_by_user_id(db: Session, user_id: UUID) -> Creators:
    """
    ユーザーIDによるクリエイター取得
    
    Args:
        db: データベースセッション
        user_id: ユーザーID
    """
    return db.scalar(select(Creators).where(Creators.user_id == user_id))

def create_identity_verification(db: Session, verification_create: IdentityVerificationCreate) -> IdentityVerifications:
    """
    本人確認レコードを作成する
    
    Args:
        db: データベースセッション
        verification_create: 本人確認作成情報
    """
    existing_verification = db.scalar(
        select(IdentityVerifications).where(IdentityVerifications.user_id == verification_create.user_id)
    )
    
    if existing_verification:
        return existing_verification
    
    db_verification = IdentityVerifications(
        user_id=verification_create.user_id,
        status=VerificationStatus.PENDING
    )
    db.add(db_verification)
    db.commit()
    db.refresh(db_verification)
    return db_verification

def update_identity_verification_status(db: Session, user_id: UUID, status: int, notes: str = None) -> IdentityVerifications:
    """
    本人確認ステータスを更新する
    
    Args:
        db: データベースセッション
        user_id: ユーザーID
        status: ステータス
        notes: 備考
    """
    verification = db.scalar(
        select(IdentityVerifications).where(IdentityVerifications.user_id == user_id)
    )
    
    if not verification:
        raise HTTPException(status_code=404, detail="Identity verification not found")
    
    verification.status = status
    verification.notes = notes
    if status == VerificationStatus.APPROVED:
        verification.checked_at = datetime.utcnow()
    
    db.commit()
    db.refresh(verification)
    return verification

def create_identity_document(db: Session, document_create: IdentityDocumentCreate) -> IdentityDocuments:
    """
    本人確認書類を作成する
    
    Args:
        db: データベースセッション
        document_create: 書類作成情報
    """
    db_document = IdentityDocuments(
        verification_id=document_create.verification_id,
        kind=document_create.kind,
        storage_key=document_create.storage_key
    )
    db.add(db_document)
    db.commit()
    db.refresh(db_document)
    return db_document

def get_identity_verification_by_user_id(db: Session, user_id: UUID) -> IdentityVerifications:
    """
    ユーザーIDによる本人確認情報取得
    
    Args:
        db: データベースセッション
        user_id: ユーザーID
    """
    return db.scalar(
        select(IdentityVerifications).where(IdentityVerifications.user_id == user_id)
    )

def get_creators(db: Session, limit: int = 50):
    from sqlalchemy import func
    from app.models.social import Follows
    
    return (
        db.query(
            Users, 
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            func.coalesce(func.count(Follows.creator_user_id), 0).label('followers_count'),
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Follows, Follows.creator_user_id == Users.id)
        .filter(Users.role == AccountType.CREATOR)
        .group_by(Users.id, Users.profile_name, Profiles.username, Profiles.avatar_url)
        .order_by(desc(Users.created_at))
        .limit(limit)
        .all()
    )

def get_top_creators(db: Session, limit: int = 5):
    """
    フォロワー数上位のクリエイターを取得
    """
    return (
            db.query(
                Users,
                Users.profile_name,
                Profiles.username,
                Profiles.avatar_url,
                func.count(Follows.creator_user_id).label('followers_count'),
                func.array_agg(Follows.follower_user_id).label("follower_ids"),
                func.count(distinct(Likes.post_id)).label("likes_count"),
            )
            .join(Profiles, Users.id == Profiles.user_id)
            .outerjoin(Follows, Users.id == Follows.creator_user_id)
            .outerjoin(Posts, Posts.creator_user_id == Users.id)
            .outerjoin(Likes, Likes.post_id == Posts.id)
            .filter(Users.role == AccountType.CREATOR)
            .group_by(Users.id, Users.profile_name, Profiles.username, Profiles.avatar_url)
            .order_by(desc('followers_count'))
            .limit(limit)
            .all()
        )
def get_new_creators(db: Session, limit: int = 5):
    """
    登録順最新のクリエイターを取得
    """
    return (
        db.query(
            Users, 
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .filter(Users.role == AccountType.CREATOR)
        .order_by(desc(Users.created_at))
        .limit(limit)
        .all()
    )