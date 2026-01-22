from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from app.core.logger import Logger
from app.db.base import get_db
from app.crud import advertising_agencies_crud
from app.deps.auth import get_current_user_optional
from app.deps.initial_domain import initial_tracking_domain
from app.domain.tracking.tracking_domain import TrackingDomain
from app.models.user import Users
from app.schemas.tracking import PostPurchaseTrackingPayload, PostViewTrackingPayload, ProfileViewTrackingPayload


router = APIRouter()

logger = Logger.get_logger()


class TrackAccessRequest(BaseModel):
    """アクセストラッキングリクエスト"""
    referral_code: str
    landing_page: Optional[str] = None


@router.post("/track-access")
async def track_access(
    request: Request,
    data: TrackAccessRequest,
    db: Session = Depends(get_db)
):
    """
    広告会社経由のアクセスを記録

    - **referral_code**: リファラルコード（ref パラメータの値）
    - **landing_page**: アクセスしたページURL
    """
    # リファラルコードから広告会社を検索
    agency = advertising_agencies_crud.get_advertising_agency_by_code(db, data.referral_code)

    if not agency:
        # 広告会社が見つからない場合でもセッションには保存
        # （後で広告会社が追加される可能性を考慮）
        request.session["referral_code"] = data.referral_code
        return {"success": False, "message": "Agency not found"}

    # セッションIDを取得（既存セッションまたは新規作成）
    session_id = request.session.get("session_id")
    if not session_id:
        import uuid
        session_id = str(uuid.uuid4())
        request.session["session_id"] = session_id

    # リファラルコードをセッションに保存（新規登録時に使用）
    # NOTE: セッションへの書き込みは例外が発生してもコミットされる
    request.session["referral_code"] = data.referral_code

    # デバッグログ
    logger.info(f"セッションにリファラルコードを保存: referral_code={data.referral_code}, session_id={session_id}")
    logger.info(f"セッション内容確認: {dict(request.session)}")

    # IPアドレスとユーザーエージェントを取得
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # アクセスログを記録（失敗してもセッションは保存される）
    try:
        advertising_agencies_crud.create_agency_access_log(
            db=db,
            agency_id=agency.id,
            referral_code=data.referral_code,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            landing_page=data.landing_page
        )
        db.commit()

        return {"success": True, "message": "Access tracked", "referral_code": data.referral_code}
    except Exception as e:
        db.rollback()
        # エラーが発生してもセッションは保存されているはず
        return {"success": False, "message": str(e), "referral_code": data.referral_code}


@router.get("/debug-session")
async def debug_session(request: Request):
    """
    デバッグ用: セッションの内容を確認
    """
    session_data = dict(request.session)
    logger.info(f"セッションデバッグ: {session_data}")
    return {
        "session": session_data,
        "has_referral_code": "referral_code" in request.session,
        "referral_code": request.session.get("referral_code"),
        "session_id": request.session.get("session_id")
    }

@router.post("/profile-view-tracking")
async def profile_view_tracking(
    payload: ProfileViewTrackingPayload,
    current_user: Optional[Users] = Depends(get_current_user_optional),
    tracking_domain: TrackingDomain = Depends(initial_tracking_domain),
):
    tracking_domain.track_profile_view(payload, current_user)
    return {"message": "Done"}

@router.post("/post-view-tracking")
async def post_view_tracking(
    payload: PostViewTrackingPayload,
    tracking_domain: TrackingDomain = Depends(initial_tracking_domain),
):
    tracking_domain.track_post_view(payload)
    return {"message": "Done"}

@router.post("/post-purchase-tracking")
async def post_purchase_tracking(
    payload: PostPurchaseTrackingPayload,
    tracking_domain: TrackingDomain = Depends(initial_tracking_domain),
):
    tracking_domain.track_post_purchase(payload)
    return {"message": "Done"}