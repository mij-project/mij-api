import os, httpx
import urllib.parse as up
from fastapi import APIRouter, Depends, HTTPException, status, Header, Response, Request
from fastapi.responses import RedirectResponse, JSONResponse
from app.core.security import create_access_token, decode_token
from app.db.base import get_db
from app.schemas.auth import LoginIn, TokenOut, LoginCookieOut
from app.models.user import Users
from sqlalchemy.orm import Session
from app.core.security import verify_password
from app.crud.user_crud import get_user_by_email, get_user_by_id
from app.core.security import (
    verify_password, 
    create_access_token, 
    create_refresh_token, 
    decode_token, 
    new_csrf_token
)
from app.core.cookies import set_auth_cookies, clear_auth_cookies, REFRESH_COOKIE, CSRF_COOKIE, ACCESS_COOKIE
from app.core.config import settings
from app.deps.auth import get_current_user
from datetime import datetime, timedelta
from requests_oauthlib import OAuth1Session
from app.deps.auth import issue_app_jwt_for
from app.crud.user_crud import create_user_by_x
from app.crud.profile_crud import create_profile, update_profile_by_x, exist_profile_by_username, get_profile_by_username
from app.constants.enums import AccountType, AccountStatus

router = APIRouter()

X_API_KEY = os.getenv('X_API_KEY')
X_API_SECRET = os.getenv('X_API_SECRET')
X_CALLBACK_URL = os.getenv('X_CALLBACK_URL')

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

            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if getattr(user, "is_active", True) is False:
            raise HTTPException(status_code=403, detail="User is not active")
        
        # ログイン時刻を更新
        user.last_login_at = datetime.utcnow()
        db.commit()
        
        access = create_access_token(str(user.id))
        refresh = create_refresh_token(str(user.id))
        csrf = new_csrf_token()

        set_auth_cookies(response, access, refresh, csrf)
        return {
            "message": "logged in", 
            "csrf_token": csrf
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/x/login")
def x_login(request: Request):
    """
    Xログイン画面へリダイレクト
    """
    try:
        x = OAuth1Session(X_API_KEY, X_API_SECRET, callback_uri=X_CALLBACK_URL)
        res = x.post(f"{OAUTH_BASE}/oauth/request_token")

        if res.status_code != 200:
            raise HTTPException(400, f"request_token error: {res.status_code} {res.text}")

        tokens = dict(up.parse_qsl(res.text))
        if "oauth_token" not in tokens or "oauth_token_secret" not in tokens:
            raise HTTPException(400, f"invalid payload: {res.text}")

        # セッション退避
        request.session["oauth_token"] = tokens["oauth_token"]
        request.session["oauth_token_secret"] = tokens["oauth_token_secret"]

        # 認可URL（選択肢）
        auth_path = "authenticate"
        params = {"oauth_token": tokens["oauth_token"]}

        auth_url = f"{OAUTH_BASE}/oauth/authorize?{up.urlencode({'oauth_token': tokens['oauth_token']})}"
        return RedirectResponse(auth_url, status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        print("Xログイン画面へリダイレクトに失敗:", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/x/callback")
def x_callback(
    request: Request,
    oauth_verifier: str,
    oauth_token: str,
    db: Session = Depends(get_db)
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
        x = OAuth1Session(X_API_KEY, X_API_SECRET, sess["oauth_token"], sess["oauth_token_secret"])
        res = x.post(f"{OAUTH_BASE}/oauth/access_token", data={"oauth_verifier": oauth_verifier})

        if res.status_code != 200:
            raise HTTPException(400, f"access_token error: {res.status_code} {res.text}")

        access = dict(up.parse_qsl(res.text))
        if "oauth_token" not in access or "oauth_token_secret" not in access:
            raise HTTPException(400, f"invalid access payload: {res.text}")

        # ユーザー情報（v2）
        x_user = OAuth1Session(X_API_KEY, X_API_SECRET, access["oauth_token"], access["oauth_token_secret"])
        me_res = x_user.get(f"{USERS_BASE}/2/users/me?user.fields=profile_image_url,verified")
        if me_res.status_code != 200:
            raise HTTPException(400, f"users/me error: {me_res.status_code} {me_res.text}")
        me = me_res.json().get("data", {})

        x_user_id = me.get("id")
        x_username = me.get("username")
        x_name = me.get("name")

        # メールアドレスの構築（Xは公開メールがないため仮のメールを生成）
        x_email = f"{x_user_id}@x.twitter.com"

        # 既存ユーザーチェック（ユーザー名で検索）
        profile_exists = exist_profile_by_username(db, x_username)

        if not profile_exists:
            # 新規ユーザー作成
            user = Users(
                profile_name=x_name,  # Xの名前
                email=x_email,
                email_verified_at=datetime.utcnow(),
                password_hash=None,
                role=AccountType.GENERAL_USER,
                status=AccountStatus.ACTIVE,
                last_login_at=datetime.utcnow()
            )
            user = create_user_by_x(db, user)

            # プロフィール作成
            profile = create_profile(db, user.id, x_username)
            db.commit()
            db.refresh(user)
            db.refresh(profile)
        else:
            # 既存ユーザーの場合、ユーザー情報を取得して更新
            # プロフィールからユーザーIDを取得
            profile = get_profile_by_username(db, x_username)
            if profile is None:
                raise HTTPException(status_code=404, detail="Profile not found")
            
            user = get_user_by_id(db, profile.user_id)
            print(f"DEBUG: Existing user found, user.id = {user.id if user else 'None'}")
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            
            # ユーザー情報を更新
            user.last_login_at = datetime.utcnow()
            if x_name:
                user.profile_name = x_name
            
            # プロフィール情報も更新
            profile = update_profile_by_x(db, user.id, x_username)
            db.commit()

        # JWT & Cookie設定（通常ログインと同じ処理）
        print(f"DEBUG: user type = {type(user)}, user = {user}")
        if hasattr(user, 'id'):
            print(f"DEBUG: user.id = {user.id}")
        else:
            print("DEBUG: user has no 'id' attribute")
        
        access_token = create_access_token(str(user.id))
        refresh_token = create_refresh_token(str(user.id))
        csrf = new_csrf_token()

        # フロントエンドのX認証コールバックページにリダイレクト
        frontend_url = os.getenv("FRONTEND_URL")
        redirect_response = RedirectResponse(url=f"{frontend_url}/auth/x/callback", status_code=302)

        # RedirectResponseに直接Cookieを設定
        set_auth_cookies(redirect_response, access_token, refresh_token, csrf)

        return redirect_response
    except Exception as e:
        print("Xログインコールバックに失敗しました", e)
        raise HTTPException(status_code=500, detail=str(e))

# 認可テスト用の /auth/me
@router.get("/me")
def me(user: Users = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    ユーザー情報取得

    Args:
        user (Users): ユーザー
        db (Session): データベースセッション

    Returns:
        dict: ユーザー情報
    """
    try:
        # 48時間（2日）チェック
        if user.last_login_at:
            time_since_last_login = datetime.utcnow() - user.last_login_at
            if time_since_last_login > timedelta(hours=48):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, 
                    detail="Session expired due to inactivity"
                )
        
        # アクセス時刻を更新
        user.last_login_at = datetime.utcnow()
        db.commit()
        
        return {
            "id": str(user.id), 
            "email": user.email, 
            "role": user.role, 
            "is_phone_verified": user.is_phone_verified,
            "is_identity_verified": user.is_identity_verified,
        }
    except HTTPException:
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    try:
        payload = decode_token(refresh)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user_id = payload.get("sub")
    # 必要ならDBでBAN/退会チェックなど

    # 新しい短命Access & CSRF
    new_access = create_access_token(user_id)
    new_csrf = new_csrf_token()

    # Set-Cookie（Access: HttpOnly / CSRF: 非HttpOnly）
    response.set_cookie(
        ACCESS_COOKIE, new_access,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MIN * 60,
        domain=settings.COOKIE_DOMAIN, secure=settings.COOKIE_SECURE,
        httponly=True, samesite=settings.COOKIE_SAMESITE, path=settings.COOKIE_PATH,
    )
    response.set_cookie(
        CSRF_COOKIE, new_csrf,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MIN * 60,
        domain=settings.COOKIE_DOMAIN, secure=settings.COOKIE_SECURE,
        httponly=False, samesite=settings.COOKIE_SAMESITE, path=settings.COOKIE_PATH,
    )
    return {"message": "refreshed", "csrf_token": new_csrf}

@router.get("/csrf")
def get_csrf_token(request: Request):
    csrf = request.cookies.get(CSRF_COOKIE)

    print(f"csrf_header={request.headers.get('csrf-token') or request.headers.get('x-csrf-token')}")
    print(f"cookies={request.cookies}")
    print(f"csrf={csrf}")
    if not csrf:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing CSRF token")
    
    return "ok"

@router.get("/auth/callback")
async def auth_callback(code: str):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{os.getenv('COGNITO_DOMAIN')}/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": os.getenv('CLIENT_ID'),
                "code": code,
                "redirect_uri": os.getenv('REDIRECT_URI'),
                # "code_verifier": "<フロントで保持したverifier>"  # PKCE時に必要
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {r.text}")

    tokens = r.json()

    # Cookieに保存 (本番は secure=True, samesite="None")
    res = Response(status_code=302, headers={"Location": "/"})
    res.set_cookie("cognito_id_token", tokens["id_token"], httponly=True, samesite="Lax", secure=False)
    res.set_cookie("cognito_access_token", tokens["access_token"], httponly=True, samesite="Lax", secure=False)
    if "refresh_token" in tokens:
        res.set_cookie("cognito_refresh_token", tokens["refresh_token"], httponly=True, samesite="Lax", secure=False)

    return res
