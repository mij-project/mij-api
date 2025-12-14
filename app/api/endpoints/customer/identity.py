import uuid
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict
from app.schemas.identity import (
    VerifyPresignResponse,
    Kind,
    CompleteRequest,
    PresignResponseItem,
    VerifyRequest,
    VerifyPresignRequest,
)
from app.schemas.commons import UploadItem, PresignResponseItem
from app.deps.permissions import require_creator_auth
from app.services.s3.keygen import identity_key
from app.services.s3.presign import presign_put
from app.deps.auth import get_current_user
from app.constants.enums import VerificationStatus
from app.crud.identity_crud import (
    create_identity_verification,
    create_identity_document,
    update_identity_verification,
)
from app.db.base import get_db
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.services.s3.client import bucket_exit_check, s3_client
from app.crud.creator_crud import update_creator_status
from app.constants.enums import CreatorStatus
from app.crud.user_crud import update_user_identity_verified_at
from app.core.logger import Logger
from app.services.slack.slack import SlackService

slack_alert = SlackService.initialize()
logger = Logger.get_logger()
router = APIRouter()

s3 = s3_client()


@router.post("/presign-upload")
def kyc_presign_upload(
    body: VerifyPresignRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    アップロードURL生成

    Raises:
        HTTPException: エラー

    Returns:
        PresignResponse: アップロードURL
    """

    try:
        allowed_kinds = {"front", "back", "selfie"}

        seen = set()
        for f in body.files:
            if f.kind not in allowed_kinds:
                raise HTTPException(400, f"unsupported kind: {f.kind}")
            if f.kind in seen:
                raise HTTPException(400, f"duplicated kind: {f.kind}")
            seen.add(f.kind)
        uploads: Dict[Kind, UploadItem] = {}

        # 認証情報を作成（まだコミットしない）
        verification = create_identity_verification(
            db, str(user.id), VerificationStatus.PENDING
        )

        for f in body.files:
            key = identity_key(str(user.id), verification.id, f.kind, f.ext)

            response = presign_put("identity", key, f.content_type)

            uploads[f.kind] = PresignResponseItem(
                key=response["key"],
                upload_url=response["upload_url"],
                expires_in=response["expires_in"],
                required_headers=response["required_headers"],
            )

            # 認証文書を作成（まだコミットしない）
            create_identity_document(db, verification.id, f.kind, key)

        # クリエイター情報を更新（まだコミットしない）
        update_creator_status(db, user.id, CreatorStatus.VERIFIED)

        # 全ての処理が完了したら一括でコミット
        db.commit()

        return VerifyPresignResponse(verification_id=verification.id, uploads=uploads)
    except Exception as e:
        db.rollback()
        logger.exception("認証情報作成エラーが発生しました")
        # エラーが発生した場合は自動的にロールバックされるため、明示的なrollbackは不要
        raise HTTPException(500, f"Failed to issue presigned URL: {e}")


@router.post("/complete")
def kyc_complete(
    body: VerifyRequest, user=Depends(get_current_user), db: Session = Depends(get_db)
):
    try:
        """
        認証情報更新

        Raises:
            HTTPException: エラー

        Returns:
            dict: 認証情報更新結果
        """
        required = {"front", "back", "selfie"}
        present = {f.kind for f in body.files}
        missing = required - present
        extra = present - required
        if missing:
            raise HTTPException(400, f"missing kinds: {sorted(missing)}")
        if extra:
            raise HTTPException(400, f"unsupported kinds: {sorted(extra)}")

        # S3存在確認
        for f in body.files:
            key = identity_key(str(user.id), str(body.verification_id), f.kind, f.ext)
            if not bucket_exit_check("identity", key):
                raise HTTPException(400, f"missing uploaded file: {f.kind}")

        update_identity_verification(
            db,
            body.verification_id,
            VerificationStatus.WAITING,
            datetime.now(timezone.utc),
        )

        users = update_user_identity_verified_at(
            db, user.id, True, datetime.now(timezone.utc)
        )
        if not users:
            raise HTTPException(500, "身分証明の更新に失敗しました。")
        db.commit()
        db.refresh(users)
        slack_alert._alert_identity_verification(user.profile_name)
        return {"ok": True, "verification_id": str(body.verification_id)}
    except Exception as e:
        db.rollback()
        logger.exception("認証情報更新エラーが発生しました")
        raise HTTPException(500, f"Failed to complete: {e}")
