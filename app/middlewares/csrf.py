# app/middlewares/csrf.py
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.core.cookies import CSRF_COOKIE

EXCLUDE_PATHS = {
    "/auth/login", "/auth/refresh", "/auth/logout",
    "/users/register", "/webhooks/mediaconvert", "/admin/users",
    "/admin/auth/login", "/admin/auth/logout", "/admin/auth/me",
    "/transcodes/transcode_mc", "/preregistrations", "/auth/email/resend",
    "/auth/email/verify", "/_debug/send-email",
    "/admin/conversations", "/admin/create-admin"
}

class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return await call_next(request)
        
        # パス完全一致チェック
        if request.url.path in EXCLUDE_PATHS:
            return await call_next(request)
        
        # パス前方一致チェック（パラメータ付きパス対応）
        for exclude_path in EXCLUDE_PATHS:
            if request.url.path.startswith(exclude_path):
                return await call_next(request)

        header_token = request.headers.get("X-CSRF-Token")
        cookie_token = request.cookies.get(CSRF_COOKIE)

        if not header_token or not cookie_token or header_token != cookie_token:
            return JSONResponse({"detail": "CSRF token mismatch"}, status_code=403)

        return await call_next(request)
