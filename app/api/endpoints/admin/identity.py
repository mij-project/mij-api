from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.db.base import get_db
from app.deps.auth import get_current_admin_user
from app.models import UserSettings
from app.schemas.admin import (
    AdminIdentityVerificationResponse,
    PaginatedResponse,
    IdentityVerificationReview,
    IdentityDocumentResponse,
    CreatorInfoForApproval,
    CreatorInfoResponse
)
from app.models.identity import IdentityVerifications, IdentityDocuments
from app.models.user import Users
from app.models.profiles import Profiles
from app.schemas.user_settings import UserSettingsType
from app.services.s3.presign import presign_get

from app.crud.identity_crud import (
    get_identity_verifications_paginated,
    update_identity_verification_status,
    approve_identity_verification,
    reject_identity_verification,
)
from app.services.email.send_email import (
    send_identity_approval_email,
    send_identity_rejection_email,
)
from app.models.admins import Admins
from app.crud.user_crud import update_user_identity_verified_at
from app.crud.creator_crud import update_creator, get_creator_by_user_id
from app.core.logger import Logger
from app.crud.events_crud import get_event_by_code
from app.crud.user_events_crud import check_user_event_exists
from app.constants.event_code import EventCode
from app.constants.number import PlatformFeePercent
from app.schemas.creator import CreatorUpdate
from app.constants.enums import VerificationStatus
from app.crud.notifications_crud import add_notification_for_identity_verification
logger = Logger.get_logger()
router = APIRouter()

def _check_has_creator_info(db: Session, user_id: str) -> bool:
    """クリエイター情報が入力済みかどうかを判定"""
    creator = get_creator_by_user_id(db, user_id)
    if not creator:
        return False
    return bool(
        creator.name and
        creator.first_name_kana and
        creator.last_name_kana and
        creator.address and
        creator.birth_date
    )

def _get_creator_info(db: Session, user_id: str) -> Optional[CreatorInfoResponse]:
    """クリエイター情報を取得"""
    creator = get_creator_by_user_id(db, user_id)
    if not creator:
        return None

    birth_date_str = None
    if creator.birth_date:
        birth_date_str = creator.birth_date.strftime("%Y-%m-%d")

    return CreatorInfoResponse(
        name=creator.name,
        first_name_kana=creator.first_name_kana,
        last_name_kana=creator.last_name_kana,
        address=creator.address,
        birth_date=birth_date_str
    )


@router.get("/identity-verifications", response_model=PaginatedResponse[AdminIdentityVerificationResponse])
def get_identity_verifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[str] = None,
    sort: Optional[str] = "created_at_desc",
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """身分証明審査一覧を取得"""

    verifications, total = get_identity_verifications_paginated(
        db=db,
        page=page,
        limit=limit,
        search=search,
        status=status,
        sort=sort
    )

    # 各認証に対してクリエイター情報の有無を判定
    response_data = []
    for v in verifications:
        has_creator_info = _check_has_creator_info(db, str(v.user_id))
        response_data.append(AdminIdentityVerificationResponse.from_orm(v, has_creator_info))

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit if total > 0 else 1
    )

@router.get("/identity-verifications/{verification_id}", response_model=AdminIdentityVerificationResponse)
def get_identity_verification(
    verification_id: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """身分証明審査詳細を取得"""

    verification = db.query(IdentityVerifications).filter(IdentityVerifications.id == verification_id).first()
    if not verification:
        raise HTTPException(status_code=404, detail="審査が見つかりません")

    # 身分証書類を取得
    documents = db.query(IdentityDocuments).filter(IdentityDocuments.verification_id == verification_id).all()

    # 各書類のpresigned URLを生成
    document_responses = []
    for doc in documents:
        presigned_data = presign_get("identity", doc.storage_key)
        document_responses.append(IdentityDocumentResponse(
            id=str(doc.id),
            kind=doc.kind,
            storage_key=doc.storage_key,
            created_at=doc.created_at,
            presigned_url=presigned_data.get("download_url")
        ))

    # クリエイター情報の有無を判定
    has_creator_info = _check_has_creator_info(db, str(verification.user_id))

    # クリエイター情報を取得
    creator_info = _get_creator_info(db, str(verification.user_id))

    # レスポンスを作成
    response = AdminIdentityVerificationResponse.from_orm(verification, has_creator_info, creator_info)
    response.documents = document_responses

    return response

@router.patch("/identity-verifications/{verification_id}/review")
def review_identity_verification(
    verification_id: str,
    review: IdentityVerificationReview,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """身分証明を審査（承認または拒否）"""

    try:
        # 審査情報を取得
        verification = db.query(IdentityVerifications).filter(
            IdentityVerifications.id == verification_id
        ).first()

        if not verification:
            raise HTTPException(status_code=404, detail="審査が見つかりません")

        if verification.status != 1:  # 1 = WAITING
            raise HTTPException(status_code=400, detail="この審査は既に処理済みです")

        # ユーザー情報を取得
        user = db.query(Users).filter(Users.id == verification.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

        # 承認または拒否処理
        if review.status == "approved":
            updated_verification = approve_identity_verification(
                db=db,
                verification_id=verification_id,
                admin_id=str(current_admin.id),
                notes=review.notes
            )

            if not updated_verification:
                raise HTTPException(status_code=500, detail="承認処理に失敗しました")

            # クリエイター情報が入力されている場合のみ更新
            if review.creator_info:
                from datetime import datetime as dt
                creator_update_data = {
                    "name": review.creator_info.name,
                    "first_name_kana": review.creator_info.first_name_kana,
                    "last_name_kana": review.creator_info.last_name_kana,
                    "address": review.creator_info.address,
                    "birth_date": dt.strptime(review.creator_info.birth_date, "%Y-%m-%d") if review.creator_info.birth_date else None,
                }
                creator = update_creator(db, user.id, CreatorUpdate(**creator_update_data))
                if not creator:
                    raise HTTPException(status_code=500, detail="クリエイター情報の更新に失敗しました")


            # 事前登録判定 TODO: イベント終了時削除
            is_preregistration = _check_preregistration(db, user.id)
            
            # プラットフォーム手数料を設定
            if is_preregistration:
                platform_fee_percent = PlatformFeePercent.DEFAULT if not is_preregistration else 0

                # クリエイター情報を更新
                update_creator_data = {
                    "platform_fee_percent": platform_fee_percent
                }
                
                creator = update_creator(db, user.id, CreatorUpdate(**update_creator_data))
                if not creator:
                    raise HTTPException(status_code=500, detail="クリエイター情報の更新に失敗しました")

            # 承認メール送信
            try:
                email_settings = db.query(UserSettings).filter(UserSettings.user_id == user.id, UserSettings.type == UserSettingsType.EMAIL).first()
                if (not email_settings or (email_settings.settings.get("identityApprove", True) == True)):
                    send_identity_approval_email(
                        to=user.email,
                        display_name=user.profile.username if user.profile else user.profile_name
                    )
            except Exception as e:
                logger.error(f"Email sending failed: {e}")

            # 通知を送信
            try:
                add_notification_for_identity_verification(db, user.id, review.status)
            except Exception as e:
                logger.error(f"Notification sending failed: {e}")
                pass

            return {"message": "身分証明を承認しました", "status": "approved"}

        elif review.status == "rejected":
            updated_verification = reject_identity_verification(
                db=db,
                verification_id=verification_id,
                admin_id=str(current_admin.id),
                notes=review.notes
            )

            if not updated_verification:
                raise HTTPException(status_code=500, detail="拒否処理に失敗しました")

            # 拒否メール送信
            try:
                email_settings = db.query(UserSettings).filter(UserSettings.user_id == user.id, UserSettings.type == UserSettingsType.EMAIL).first()
                if (not email_settings or (email_settings.settings.get("identityApprove", True) == True)):
                    send_identity_rejection_email(
                        to=user.email,
                        display_name=user.profile.username if user.profile else user.profile_name,
                        notes=review.notes
                    )

                users = update_user_identity_verified_at(db, user.id, False, datetime.now(timezone.utc))
                if not users:
                    raise HTTPException(500, "身分証明の更新に失敗しました。")
            except Exception as e:
                logger.error(f"Email sending failed: {e}")

            # 通知を送信
            try:
                add_notification_for_identity_verification(db, user.id, review.status)
            except Exception as e:
                logger.error(f"Notification sending failed: {e}")
                pass

            return {"message": "身分証明を拒否しました", "status": "rejected"}

        else:
            raise HTTPException(status_code=400, detail="無効なステータスです")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Identity verification review error: {e}")
        raise HTTPException(status_code=500, detail="審査処理中にエラーが発生しました")

@router.patch("/identity-verifications/{verification_id}/creator-info")
def update_creator_info(
    verification_id: str,
    creator_info: CreatorInfoForApproval,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """クリエイター基本情報を更新"""
    from app.schemas.admin import CreatorInfoForApproval

    try:
        # 審査情報を取得
        verification = db.query(IdentityVerifications).filter(
            IdentityVerifications.id == verification_id
        ).first()

        if not verification:
            raise HTTPException(status_code=404, detail="審査が見つかりません")

        # クリエイター情報を更新
        from datetime import datetime as dt
        creator_update_data = {
            "name": creator_info.name,
            "first_name_kana": creator_info.first_name_kana,
            "last_name_kana": creator_info.last_name_kana,
            "address": creator_info.address,
            "birth_date": dt.strptime(creator_info.birth_date, "%Y-%m-%d") if creator_info.birth_date else None,
        }
        creator = update_creator(db, verification.user_id, CreatorUpdate(**creator_update_data))
        if not creator:
            raise HTTPException(status_code=500, detail="クリエイター情報の更新に失敗しました")

        return {"message": "クリエイター情報を更新しました", "success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Creator info update error: {e}")
        raise HTTPException(status_code=500, detail="クリエイター情報の更新に失敗しました")

def _check_preregistration(db: Session, user_id: str) -> bool:
    """
    事前登録判定
    """
    event = get_event_by_code(db, EventCode.PRE_REGISTRATION)
    if event:
        return check_user_event_exists(db, user_id, event.id)
    return False