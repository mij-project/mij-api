from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.db.base import get_db
from app.deps.auth import get_current_admin_user
from app.schemas.admin import (
    AdminIdentityVerificationResponse, 
    PaginatedResponse, 
    IdentityVerificationReview, 
    IdentityDocumentResponse
)
from app.models.identity import IdentityVerifications, IdentityDocuments
from app.models.user import Users
from app.models.profiles import Profiles
from app.services.s3.presign import presign_get

from app.crud.identity_crud import (
    get_identity_verifications_paginated,
    update_identity_verification_status,
)

router = APIRouter()


@router.get("/identity-verifications", response_model=PaginatedResponse[AdminIdentityVerificationResponse])
def get_identity_verifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[str] = None,
    sort: Optional[str] = "created_at_desc",
    db: Session = Depends(get_db),
    current_admin: Users = Depends(get_current_admin_user)
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
    
    return PaginatedResponse(
        data=[AdminIdentityVerificationResponse.from_orm(v) for v in verifications],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit if total > 0 else 1
    )

@router.get("/identity-verifications/{verification_id}", response_model=AdminIdentityVerificationResponse)
def get_identity_verification(
    verification_id: str,
    db: Session = Depends(get_db),
    current_admin: Users = Depends(get_current_admin_user)
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

    # レスポンスを作成
    response = AdminIdentityVerificationResponse.from_orm(verification)
    response.documents = document_responses

    return response

@router.patch("/identity-verifications/{verification_id}/review")
def review_identity_verification(
    verification_id: str,
    review: IdentityVerificationReview,
    db: Session = Depends(get_db),
    current_admin: Users = Depends(get_current_admin_user)
):
    """身分証明を審査"""
    
    success = update_identity_verification_status(db, verification_id, review.status)
    if not success:
        raise HTTPException(status_code=404, detail="審査が見つかりませんまたは既に完了済みです")
    
    return {"message": "身分証明審査を完了しました"}