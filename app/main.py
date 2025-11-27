from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.migrations import run_migrations
from app.middlewares.csrf import CSRFMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.db.migrations import run_migrations
from app.core.logger import Logger
logger = Logger.get_logger()
# ========================
# ✅ .env スイッチング処理
# ========================
env = os.getenv("ENV", "development")
env_file = f".env.{env}"
load_dotenv(dotenv_path=env_file)
logger.info(f" Loaded FastAPI ENV: {env_file}")

from app.routers import api_router

# ========================
# ✅ Auto Alembic Upgrade
# ========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    run_migrations()   # auto alembic upgrade head mỗi lần app start

    yield

app = FastAPI(lifespan=lifespan)

# ========================
# CORS
# ========================
origins = [
    # ローカル開発用
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3003",
    "http://localhost:3005",

    # 事前登録サイト
    "https://campaign.mijfans.jp",

    # ステージング
    "https://stg.mijfans.jp",
    "https://stg-admin.mijfans.jp",

    # 本番環境用
    "https://mijfans.jp",
    "https://admin.mijfans.jp",
    "https://prd-admin.linkle.group"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,       # allow_credentials=True の場合 * は不可
    allow_credentials=True,      # フロントのCookie/Authorization送信に必要
    allow_methods=["*"],
    allow_headers=["*"],         # 'authorization', 'x-csrf-token' 等も通る
)

# ========================
# セッション（必須）
# ========================
# TODO 本番は secure=True, samesite="None"
SECRET_KEY = os.getenv("SECRET_KEY")  # 十分に長いランダム文字列を設定
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is not set in environment")
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax", 
    https_only=False,
)

# ========================
# CSRF（必要なら /auth/x/* を除外する設定に）
# ========================
app.add_middleware(CSRFMiddleware)

@app.get("/healthz")
def healthz():
    return {"ok": True}

# ルータ
app.include_router(api_router)