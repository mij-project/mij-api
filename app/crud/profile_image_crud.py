from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, desc, asc
from datetime import datetime, timezone
from uuid import UUID

from app.models import Notifications, Posts, UserSettings
from app.models.profile_image_submissions import ProfileImageSubmissions
from app.models.user import Users
from app.models.profiles import Profiles
from app.models.admins import Admins
from app.constants.enums import ProfileImage, ProfileImageStatus
import os

from app.schemas.notification import NotificationType
from app.schemas.user_settings import UserSettingsType
from app.services.email.send_email import (
    send_profile_image_approval_email,
    send_profile_image_rejection_email,
)
from app.core.logger import Logger

logger = Logger.get_logger()
CDN_URL = os.getenv("CDN_BASE_URL", "")


def create_submission(
    db: Session, user_id: UUID, image_type: int, storage_key: str
) -> ProfileImageSubmissions:
    """
    新しい画像申請を作成

    Args:
        db: データベースセッション
        user_id: ユーザーID
        image_type: 画像タイプ (1=avatar, 2=cover)
        storage_key: S3ストレージキー

    Returns:
        ProfileImageSubmissions: 作成された申請
    """
    submission = ProfileImageSubmissions(
        user_id=user_id,
        image_type=image_type,
        storage_key=storage_key,
        status=ProfileImageStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(submission)
    db.flush()
    return submission


def get_submission_by_id(
    db: Session, submission_id: UUID
) -> Optional[ProfileImageSubmissions]:
    """
    IDで申請を取得

    Args:
        db: データベースセッション
        submission_id: 申請ID

    Returns:
        Optional[ProfileImageSubmissions]: 申請
    """
    return (
        db.query(ProfileImageSubmissions)
        .filter(ProfileImageSubmissions.id == submission_id)
        .first()
    )


def get_pending_submission_by_user_and_type(
    db: Session, user_id: UUID, image_type: int
) -> Optional[ProfileImageSubmissions]:
    """
    ユーザーと画像タイプで申請中の申請を取得

    Args:
        db: データベースセッション
        user_id: ユーザーID
        image_type: 画像タイプ

    Returns:
        Optional[ProfileImageSubmissions]: 申請中の申請
    """
    return (
        db.query(ProfileImageSubmissions)
        .filter(
            ProfileImageSubmissions.user_id == user_id,
            ProfileImageSubmissions.image_type == image_type,
            ProfileImageSubmissions.status == ProfileImageStatus.PENDING,
        )
        .order_by(desc(ProfileImageSubmissions.created_at))
        .first()
    )


def get_submission_detail_by_id(
    db: Session, submission_id: UUID
) -> Optional[Dict[str, Any]]:
    """
    IDで申請詳細を取得（JOINして詳細情報を含む）

    Args:
        db: データベースセッション
        submission_id: 申請ID

    Returns:
        Optional[Dict]: 申請詳細
    """
    result = (
        db.query(
            ProfileImageSubmissions,
            Users.email.label("user_email"),
            Users.profile_name,
            Profiles.username,
            Admins.email.label("approver_email"),
        )
        .join(Users, ProfileImageSubmissions.user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Admins, ProfileImageSubmissions.approved_by == Admins.id)
        .filter(ProfileImageSubmissions.id == submission_id)
        .first()
    )

    if not result:
        return None

    submission = result.ProfileImageSubmissions
    image_type_labels = {ProfileImage.AVATAR: "アバター", ProfileImage.COVER: "カバー"}
    status_labels = {
        ProfileImageStatus.PENDING: "申請中",
        ProfileImageStatus.APPROVED: "承認済み",
        ProfileImageStatus.REJECTED: "却下",
    }

    return {
        "id": submission.id,
        "user_id": submission.user_id,
        "user_email": result.user_email,
        "username": result.username,
        "profile_name": result.profile_name,
        "image_type": submission.image_type,
        "image_type_label": image_type_labels.get(submission.image_type, "不明"),
        "storage_key": submission.storage_key,
        "image_url": f"{CDN_URL}/{submission.storage_key}",
        "status": submission.status,
        "status_label": status_labels.get(submission.status, "不明"),
        "approved_by": submission.approved_by,
        "approver_email": result.approver_email,
        "checked_at": submission.checked_at,
        "rejection_reason": submission.rejection_reason,
        "created_at": submission.created_at,
        "updated_at": submission.updated_at,
    }


def get_submissions_paginated(
    db: Session,
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "created_at_desc",
) -> Tuple[List[Dict[str, Any]], int]:
    """
    ページネーション付き申請一覧を取得

    Args:
        db: データベースセッション
        page: ページ番号
        limit: 1ページあたりの件数
        status: ステータスフィルタ
        search: 検索クエリ
        sort: ソート順

    Returns:
        Tuple[List[Dict], int]: (申請リスト, 総件数)
    """
    skip = (page - 1) * limit

    query = (
        db.query(
            ProfileImageSubmissions,
            Users.email.label("user_email"),
            Users.profile_name,
            Profiles.username,
            Admins.email.label("approver_email"),
        )
        .join(Users, ProfileImageSubmissions.user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Admins, ProfileImageSubmissions.approved_by == Admins.id)
    )

    # ステータスフィルタ
    if status:
        status_map = {
            "pending": ProfileImageStatus.PENDING,
            "approved": ProfileImageStatus.APPROVED,
            "rejected": ProfileImageStatus.REJECTED,
        }
        query = query.filter(
            ProfileImageSubmissions.status
            == status_map.get(status, ProfileImageStatus.PENDING)
        )

    # 検索フィルタ
    if search:
        query = query.filter(
            (Users.email.ilike(f"%{search}%"))
            | (Profiles.username.ilike(f"%{search}%"))
            | (Users.profile_name.ilike(f"%{search}%"))
        )

    # ソート
    if sort == "created_at_desc":
        query = query.order_by(desc(ProfileImageSubmissions.created_at))
    elif sort == "created_at_asc":
        query = query.order_by(asc(ProfileImageSubmissions.created_at))
    elif sort == "checked_at_desc":
        query = query.order_by(desc(ProfileImageSubmissions.checked_at))
    elif sort == "checked_at_asc":
        query = query.order_by(asc(ProfileImageSubmissions.checked_at))
    else:
        query = query.order_by(desc(ProfileImageSubmissions.created_at))

    total = query.count()
    results = query.offset(skip).limit(limit).all()

    # データ変換
    image_type_labels = {ProfileImage.AVATAR: "アバター", ProfileImage.COVER: "カバー"}
    status_labels = {
        ProfileImageStatus.PENDING: "申請中",
        ProfileImageStatus.APPROVED: "承認済み",
        ProfileImageStatus.REJECTED: "却下",
    }

    submissions = []
    for row in results:
        submission = row.ProfileImageSubmissions
        submissions.append(
            {
                "id": submission.id,
                "user_id": submission.user_id,
                "user_email": row.user_email,
                "username": row.username,
                "profile_name": row.profile_name,
                "image_type": submission.image_type,
                "image_type_label": image_type_labels.get(
                    submission.image_type, "不明"
                ),
                "storage_key": submission.storage_key,
                "image_url": f"{CDN_URL}/{submission.storage_key}",
                "status": submission.status,
                "status_label": status_labels.get(submission.status, "不明"),
                "approved_by": submission.approved_by,
                "approver_email": row.approver_email,
                "checked_at": submission.checked_at,
                "rejection_reason": submission.rejection_reason,
                "created_at": submission.created_at,
                "updated_at": submission.updated_at,
            }
        )

    return submissions, total


def approve_submission(db: Session, submission_id: UUID, admin_id: UUID) -> bool:
    """
    申請を承認してプロフィールを更新

    Args:
        db: データベースセッション
        submission_id: 申請ID
        admin_id: 承認する管理者ID

    Returns:
        bool: 成功フラグ
    """
    submission = get_submission_by_id(db, submission_id)
    if not submission or submission.status != ProfileImageStatus.PENDING:
        return False

    # プロフィール更新
    profile = db.query(Profiles).filter(Profiles.user_id == submission.user_id).first()

    if not profile:
        return False

    # 画像タイプに応じて更新
    if submission.image_type == ProfileImage.AVATAR:
        profile.avatar_url = submission.storage_key
    elif submission.image_type == ProfileImage.COVER:
        profile.cover_url = submission.storage_key

    profile.updated_at = datetime.now(timezone.utc)

    # 申請ステータス更新
    submission.status = ProfileImageStatus.APPROVED
    submission.approved_by = admin_id
    submission.checked_at = datetime.now(timezone.utc)
    submission.updated_at = datetime.now(timezone.utc)

    db.flush()
    return True


def reject_submission(
    db: Session, submission_id: UUID, admin_id: UUID, rejection_reason: str
) -> bool:
    """
    申請を却下

    Args:
        db: データベースセッション
        submission_id: 申請ID
        admin_id: 却下する管理者ID
        rejection_reason: 却下理由

    Returns:
        bool: 成功フラグ
    """
    submission = get_submission_by_id(db, submission_id)
    if not submission or submission.status != ProfileImageStatus.PENDING:
        return False

    # 申請ステータス更新
    submission.status = ProfileImageStatus.REJECTED
    submission.approved_by = admin_id
    submission.checked_at = datetime.now(timezone.utc)
    submission.rejection_reason = rejection_reason
    submission.updated_at = datetime.now(timezone.utc)

    db.flush()
    return True


def get_user_submissions(
    db: Session, user_id: UUID
) -> Dict[str, Optional[ProfileImageSubmissions]]:
    """
    ユーザーの最新申請状況を取得

    Args:
        db: データベースセッション
        user_id: ユーザーID

    Returns:
        Dict[str, Optional[ProfileImageSubmissions]]: avatar_submission, cover_submission
    """
    avatar_submission = (
        db.query(ProfileImageSubmissions)
        .filter(
            ProfileImageSubmissions.user_id == user_id,
            ProfileImageSubmissions.image_type == ProfileImage.AVATAR,
        )
        .order_by(desc(ProfileImageSubmissions.created_at))
        .first()
    )

    cover_submission = (
        db.query(ProfileImageSubmissions)
        .filter(
            ProfileImageSubmissions.user_id == user_id,
            ProfileImageSubmissions.image_type == ProfileImage.COVER,
        )
        .order_by(desc(ProfileImageSubmissions.created_at))
        .first()
    )

    return {
        "avatar_submission": avatar_submission,
        "cover_submission": cover_submission,
    }


def add_notification_for_profile_image_submission(
    db: Session,
    submission_id: UUID,
    type: str,
) -> None:
    """
    プロフィール画像申請に対する通知を追加
    """
    try:
        submission = get_submission_by_id(db, submission_id)
        if not submission:
            return
        profile = (
            db.query(Profiles).filter(Profiles.user_id == submission.user_id).first()
        )
        settings = (
            db.query(UserSettings.settings)
            .filter(UserSettings.user_id == submission.user_id)
            .first()
        )
        if settings is not None and isinstance(settings[0], dict):
            profile_approve_setting = settings[0].get("profileApprove", True)
            if profile_approve_setting is False:
                return
        # redirect_urlを画像タイプに応じて設定
        redirect_url = "/account/edit"
        if type == "rejected":
            # 却下時は該当する画像タブにリダイレクト
            if submission.image_type == ProfileImage.AVATAR:
                redirect_url = "/account/edit?tab=avatar"
            elif submission.image_type == ProfileImage.COVER:
                redirect_url = "/account/edit?tab=cover"
        elif type == "approved":
            redirect_url = f"/profile?username={profile.username}"

        if type == "approved":
            title = "プロフィール画像申請が承認されました"
            subtitle = "プロフィール画像申請が承認されました"
        elif type == "rejected":
            title = "プロフィール画像申請が却下されました"
            subtitle = "プロフィール画像申請が却下されました"
        else:
            return
        if not profile:
            return
        notification = Notifications(
            user_id=profile.user_id,
            type=NotificationType.USERS,
            payload={
                "title": title,
                "subtitle": subtitle,
                "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
                "redirect_url": redirect_url,
            },
        )
        db.add(notification)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"プロフィール画像申請に対する通知を追加エラー: {e}")
        return


def add_mail_notification_for_profile_image_submission(
    db: Session,
    submission_id: UUID,
    type: str,
) -> None:
    """
    プロフィール画像申請に対するメール通知を追加
    """
    try:
        result = (
            db.query(
                Users,
                Profiles,
                ProfileImageSubmissions,
                UserSettings.settings,
            )
            .join(Profiles, Users.id == Profiles.user_id)
            .join(
                ProfileImageSubmissions,
                Profiles.user_id == ProfileImageSubmissions.user_id,
            )
            .outerjoin(
                UserSettings,
                and_(
                    Users.id == UserSettings.user_id,
                    UserSettings.type == UserSettingsType.EMAIL,
                ),
            )
            .filter(ProfileImageSubmissions.id == submission_id)
            .first()
        )
        if not result:
            raise Exception("Can not query user settings")

        # タプルをアンパック
        user, profile, submission, settings = result

        # メール通知の設定をチェック
        # settingsがNoneの場合、またはprofileApproveがTrue/Noneの場合は送信
        should_send = True
        if settings is not None and isinstance(settings, dict):
            profile_approve_setting = settings.get("profileApprove", True)
            if profile_approve_setting is False:
                should_send = False

        if not should_send:
            return

        # redirect_urlを画像タイプに応じて設定
        redirect_url = f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/profile?username={profile.username}"
        if type == "rejected":
            # 却下時は該当する画像タブにリダイレクト
            if submission.image_type == ProfileImage.AVATAR:
                redirect_url = f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/account/edit?tab=avatar"
            elif submission.image_type == ProfileImage.COVER:
                redirect_url = f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/account/edit?tab=cover"

        if type == "approved":
            send_profile_image_approval_email(
                user.email,
                profile.username if profile else user.profile_name,
                redirect_url,
            )
        elif type == "rejected":
            send_profile_image_rejection_email(
                user.email,
                profile.username if profile else user.profile_name,
                submission.rejection_reason,
                redirect_url,
            )

    except Exception as e:
        logger.error(f"プロフィール画像申請に対するメール通知を追加エラー: {e}")
        return
