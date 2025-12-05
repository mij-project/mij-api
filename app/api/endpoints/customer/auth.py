import os, httpx
import urllib.parse as up
from fastapi import APIRouter, Depends, HTTPException, status, Header, Response, Request
from fastapi.responses import RedirectResponse, JSONResponse
from app.core.security import create_access_token, decode_token
from app.db.base import get_db
from app.models.creators import Creators
from app.schemas.auth import LoginIn, TokenOut, LoginCookieOut
from app.models.user import Users
from sqlalchemy.orm import Session
from app.core.security import verify_password
from app.crud.user_crud import get_user_by_email, get_user_by_id, check_email_exists
from app.core.security import (
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    new_csrf_token,
)
from app.core.cookies import (
    set_auth_cookies,
    clear_auth_cookies,
    REFRESH_COOKIE,
    CSRF_COOKIE,
    ACCESS_COOKIE,
)
from app.core.config import settings
from app.deps.auth import get_current_user, get_current_user_for_me
from datetime import datetime, timedelta, timezone
from requests_oauthlib import OAuth1Session
from app.deps.auth import issue_app_jwt_for
from app.crud.user_crud import create_user_by_x
from app.crud.profile_crud import (
    create_profile,
    update_profile_by_x,
    exist_profile_by_username,
    get_profile_by_username,
)
from app.constants.enums import AccountType, AccountStatus
from typing import Tuple
from app.models.user import Users
from app.models.profiles import Profiles
from app.crud.companies_crud import get_company_by_code, add_company_user
from app.constants.number import CompanyFeePercent
from app.crud.preregistrations_curd import get_preregistration_by_X_name
from app.constants.event_code import EventCode
from app.crud.user_events_crud import create_user_event
from app.crud.events_crud import get_event_by_code
from app.core.logger import Logger

logger = Logger.get_logger()
router = APIRouter()

X_API_KEY = os.getenv("X_API_KEY")
X_API_SECRET = os.getenv("X_API_SECRET")
X_CALLBACK_URL = os.getenv("X_CALLBACK_URL")

OAUTH_BASE = "https://api.twitter.com"
USERS_BASE = "https://api.twitter.com"


@router.post("/login", response_model=LoginCookieOut)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    """
    ログイン

    Args:
        payload (LoginIn): ログイン情報
        db (Session, optional): データベースセッション. Defaults to Depends(get_db).

    Raises:
        HTTPException: ユーザーが存在しない場合
        HTTPException: ユーザーが非アクティブの場合

    Returns:
        TokenOut: トークン
    """
    try:
        email = payload.email
        password = payload.password
        user = get_user_by_email(db, email)
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )
        if getattr(user, "is_active", True) is False:
            raise HTTPException(status_code=403, detail="User is not active")

        # ログイン時刻を更新
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()

        access = create_access_token(str(user.id))
        refresh = create_refresh_token(str(user.id))
        csrf = new_csrf_token()

        set_auth_cookies(response, access, refresh, csrf)
        return {"message": "logged in", "csrf_token": csrf}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/x/login")
def x_login(request: Request, company_code: str = None):
    """
    Xログイン画面へリダイレクト

    Args:
        company_code: 企業コード(任意)
    """
    try:
        x = OAuth1Session(X_API_KEY, X_API_SECRET, callback_uri=X_CALLBACK_URL)
        res = x.post(f"{OAUTH_BASE}/oauth/request_token")

        if res.status_code != 200:
            raise HTTPException(
                400, f"request_token error: {res.status_code} {res.text}"
            )

        tokens = dict(up.parse_qsl(res.text))
        if "oauth_token" not in tokens or "oauth_token_secret" not in tokens:
            raise HTTPException(400, f"invalid payload: {res.text}")

        # セッション退避（既存のセッションデータをクリア）
        request.session.clear()
        request.session["oauth_token"] = tokens["oauth_token"]
        request.session["oauth_token_secret"] = tokens["oauth_token_secret"]

        # 企業コードもセッションに保存
        if company_code:
            request.session["company_code"] = company_code

        # 認可URL（選択肢）
        # auth_path = "authenticate"
        # params = {"oauth_token": tokens["oauth_token"]}

        auth_url = f"{OAUTH_BASE}/oauth/authorize?{up.urlencode({'oauth_token': tokens['oauth_token']})}"
        return RedirectResponse(auth_url, status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Xログイン画面へリダイレクトに失敗:", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/x/callback")
def x_callback(
    request: Request,
    oauth_verifier: str,
    oauth_token: str,
    db: Session = Depends(get_db),
):
    """
    Xログインコールバック → access_token交換 → ユーザー情報取得 → DB保存/更新 → Cookie設定 → リダイレクト

    Args:
        request (Request): リクエスト
        oauth_verifier (str): OAuth verifier
        oauth_token (str): OAuth token
        db (Session): データベースセッション

    Returns:
        RedirectResponse: リダイレクト

    Raises:
        HTTPException: エラー

    Returns:
        dict: ユーザー情報
    """
    try:
        sess = request.session
        if oauth_token != sess.get("oauth_token"):
            raise HTTPException(400, "state mismatch")

        # access_token 交換
        x = OAuth1Session(
            X_API_KEY, X_API_SECRET, sess["oauth_token"], sess["oauth_token_secret"]
        )
        res = x.post(
            f"{OAUTH_BASE}/oauth/access_token", data={"oauth_verifier": oauth_verifier}
        )

        if res.status_code != 200:
            raise HTTPException(
                400, f"access_token error: {res.status_code} {res.text}"
            )

        access = dict(up.parse_qsl(res.text))
        if "oauth_token" not in access or "oauth_token_secret" not in access:
            raise HTTPException(400, f"invalid access payload: {res.text}")

        # ユーザー情報（v1.1 - OAuth 1.0aでメールアドレス取得）
        x_user = OAuth1Session(
            X_API_KEY, X_API_SECRET, access["oauth_token"], access["oauth_token_secret"]
        )
        me_res = x_user.get(
            f"{USERS_BASE}/1.1/account/verify_credentials.json?include_email=true"
        )
        if me_res.status_code != 200:
            raise HTTPException(
                400, f"verify_credentials error: {me_res.status_code} {me_res.text}"
            )
        me = me_res.json()

        x_username = me.get("screen_name")
        if x_username and not x_username.startswith("@"):
            x_username = f"@{x_username}"
        x_name = me.get("name")
        x_email = me.get("email")

        if not x_email:
            x_email = f"{x_username}@not-found.com"

        # ユーザー存在チェック
        user_exists = check_email_exists(db, x_email)

        # 新規ユーザーフラグ
        is_new_user = False

        if not user_exists:
            # 事前登録対象者かチェック
            preregistration = get_preregistration_by_X_name(db, x_username, x_name)
            offical_flg = True if preregistration else False

            # 新規ユーザー作成
            user, profile = _create_user_and_profile(
                db, x_email, x_username, x_name, offical_flg
            )
            # セッションから企業コードを取得し、company_usersにレコードを追加
            company_code = request.session.get("company_code")
            if company_code:
                try:
                    _insert_company_user(db, company_code, user.id)
                except HTTPException as e:
                    logger.warning(
                        f"企業コード '{company_code}' が見つかりませんでした: {e.detail}"
                    )
                finally:
                    # セッションから企業コードを削除
                    request.session.pop("company_code", None)

            if preregistration:
                _insert_user_event(db, user.id, EventCode.PRE_REGISTRATION)

            is_new_user = True
        else:
            # 既存ユーザーの場合、ユーザー情報を取得して更新
            # user, profile = _update_user_and_profile(db, user, x_username, x_name)
            user, profile = _update_user_and_profile(db, x_username, x_name)

        db.commit()
        db.refresh(user)
        db.refresh(profile)

        access_token = create_access_token(str(user.id))
        refresh_token = create_refresh_token(str(user.id))
        csrf = new_csrf_token()

        # フロントエンドのX認証コールバックページにリダイレクト
        frontend_url = os.getenv("FRONTEND_URL")
        callback_url = f"{frontend_url}/auth/x/callback"
        if is_new_user:
            callback_url = f"{callback_url}?is_new_user=true"
        redirect_response = RedirectResponse(url=callback_url, status_code=302)

        # RedirectResponseに直接Cookieを設定
        set_auth_cookies(redirect_response, access_token, refresh_token, csrf)

        return redirect_response
    except Exception as e:
        db.rollback()
        logger.error("Xログインコールバックに失敗しました", e)
        raise HTTPException(status_code=500, detail=str(e))


# 認可テスト用の /auth/me
@router.get("/me")
def me(user: Users = Depends(get_current_user_for_me), db: Session = Depends(get_db)):
    """
    ユーザー情報取得

    Args:
        user (Users): ユーザー
        db (Session): データベースセッション

    Returns:
        dict: ユーザー情報
    """
    if not user:
        return {"status": "401", "message": "Missing access token"}
    try:
        # 48時間（2日）チェック
        if user.last_login_at:
            time_since_last_login = datetime.now(
                timezone.utc
            ) - user.last_login_at.replace(tzinfo=timezone.utc)
            if time_since_last_login > timedelta(hours=48):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session expired due to inactivity",
                )
        user_updated_at = user.updated_at
        if user.role == AccountType.CREATOR:
            creator = db.query(Creators).filter(Creators.user_id == user.id).first()
            user_updated_at = creator.created_at
        # アクセス時刻を更新
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()

        return {
            "id": str(user.id),
            "email": user.email,
            "role": user.role,
            "is_phone_verified": user.is_phone_verified,
            "is_identity_verified": user.is_identity_verified,
            "offical_flg": user.offical_flg,
            "user_updated_at": user_updated_at,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/logout")
def logout(response: Response):
    """
    ログアウト

    Args:
        response (Response): レスポンス
    """
    try:
        clear_auth_cookies(response)
        return {"message": "logged out"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh")
def refresh_token(request: Request, response: Response):
    refresh = request.cookies.get(REFRESH_COOKIE)
    if not refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token"
        )

    try:
        payload = decode_token(refresh)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type"
        )

    user_id = payload.get("sub")
    # 必要ならDBでBAN/退会チェックなど

    # 新しい短命Access & CSRF
    new_access = create_access_token(user_id)
    new_csrf = new_csrf_token()

    # Set-Cookie（Access: HttpOnly / CSRF: 非HttpOnly）
    response.set_cookie(
        ACCESS_COOKIE,
        new_access,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MIN * 60,
        domain=settings.COOKIE_DOMAIN,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
        path=settings.COOKIE_PATH,
    )
    response.set_cookie(
        CSRF_COOKIE,
        new_csrf,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MIN * 60,
        domain=settings.COOKIE_DOMAIN,
        secure=settings.COOKIE_SECURE,
        httponly=False,
        samesite=settings.COOKIE_SAMESITE,
        path=settings.COOKIE_PATH,
    )
    return {"message": "refreshed", "csrf_token": new_csrf}


@router.get("/csrf")
def get_csrf_token(request: Request):
    csrf = request.cookies.get(CSRF_COOKIE)

    logger.info(
        f"csrf_header={request.headers.get('csrf-token') or request.headers.get('x-csrf-token')}"
    )
    logger.info(f"cookies={request.cookies}")
    logger.info(f"csrf={csrf}")
    if not csrf:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing CSRF token"
        )

    return "ok"


@router.get("/auth/callback")
async def auth_callback(code: str):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{os.getenv('COGNITO_DOMAIN')}/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": os.getenv("CLIENT_ID"),
                "code": code,
                "redirect_uri": os.getenv("REDIRECT_URI"),
                # "code_verifier": "<フロントで保持したverifier>"  # PKCE時に必要
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {r.text}")

    tokens = r.json()

    # Cookieに保存 (本番は secure=True, samesite="None")
    res = Response(status_code=302, headers={"Location": "/"})
    res.set_cookie(
        "cognito_id_token",
        tokens["id_token"],
        httponly=True,
        samesite="Lax",
        secure=False,
    )
    res.set_cookie(
        "cognito_access_token",
        tokens["access_token"],
        httponly=True,
        samesite="Lax",
        secure=False,
    )
    if "refresh_token" in tokens:
        res.set_cookie(
            "cognito_refresh_token",
            tokens["refresh_token"],
            httponly=True,
            samesite="Lax",
            secure=False,
        )

    return res


def _create_user_and_profile(
    db: Session, x_email: str, x_username: str, x_name: str, offical_flg: bool
) -> Tuple[Users, Profiles]:
    """ユーザーとプロフィールを作成

    Args:
        db (Session): データベースセッション
        x_email (str): Xメールアドレス
        x_username (str): Xユーザー名
        x_name (str): Xの名前

    Returns:
        Tuple[Users, Profiles]: ユーザーとプロフィール
    """
    # 新規ユーザー作成
    user = Users(
        profile_name=x_name,  # Xの名前
        email=x_email,
        email_verified_at=datetime.now(timezone.utc),
        password_hash=None,
        role=AccountType.GENERAL_USER,
        status=AccountStatus.ACTIVE,
        last_login_at=datetime.now(timezone.utc),
        offical_flg=offical_flg,
    )
    user = create_user_by_x(db, user)

    # x_usernameの先頭の@を削除
    if x_username and x_username.startswith("@"):
        x_username = x_username[1:]

    # プロフィール作成
    profile = create_profile(db, user.id, x_username)
    return user, profile


# def _update_user_and_profile(db: Session, user: Users, x_username: str, x_name: str) -> Tuple[Users, Profiles]:
def _update_user_and_profile(
    db: Session, x_username: str, x_name: str
) -> Tuple[Users, Profiles]:
    """ユーザーとプロフィールを更新

    Args:
        db (Session): データベースセッション
        user (Users): ユーザー
        x_username (str): Xユーザー名

    Returns:
        Tuple[Users, Profiles]: ユーザーとプロフィール
    """
    # 既存ユーザーの場合、ユーザー情報を取得して更新
    # プロフィールからユーザーIDを取得
    profile = get_profile_by_username(db, x_username)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    user = get_user_by_id(db, profile.user_id)
    logger.info(f"DEBUG: Existing user found, user.id = {user.id if user else 'None'}")
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # ユーザー情報を更新
    user.last_login_at = datetime.now(timezone.utc)
    if x_name:
        user.profile_name = x_name

    # プロフィール情報も更新
    profile = update_profile_by_x(db, user.id, x_username)
    db.commit()
    return user, profile


def _insert_company_user(db: Session, company_code: str, user_id: str) -> bool:
    """企業にユーザーを追加

    Args:
        db (Session): データベースセッション
        company_code (str): 企業コード
        user_id (str): ユーザーID

    Raises:
        HTTPException: 企業が見つかりません

    Returns:
        bool: 企業にユーザーを追加
    """
    company = get_company_by_code(db, company_code)
    if not company:
        raise HTTPException(status_code=404, detail="企業が見つかりません")

    # 親会社と子会社の設定値を追加
    targets = (
        [
            (company.parent_company_id, CompanyFeePercent.PARENT_DEFAULT, False),
            (company.id, CompanyFeePercent.CHILD_DEFAULT, True),
        ]
        # 親会社がない場合は通常の設定値を追加
        if company.parent_company_id
        else [(company.id, CompanyFeePercent.DEFAULT, True)]
    )

    for company_id, fee_percent, is_referrer in targets:
        add_company_user(db, company_id, user_id, fee_percent, is_referrer)

    return True


def _insert_user_event(db: Session, user_id: str, event_code: str) -> bool:
    """
    ユーザーイベントを挿入
    """
    event = get_event_by_code(db, event_code)
    if event:
        return create_user_event(db, user_id, event.id)
    return False
