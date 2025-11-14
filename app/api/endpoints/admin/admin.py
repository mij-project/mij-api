from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
from os import getenv
from app.db.base import get_db
from app.deps.auth import get_current_admin_user
from app.schemas.admin import (
    AdminDashboardStats,
    AdminCreatorApplicationResponse,
    AdminUserResponse,
    AdminSalesData,
    CreatorApplicationReview,
    PaginatedResponse,
    CreateAdminRequest,
    AdminResponse,
)
from app.models.user import Users
from app.models.creators import Creators
from app.models.profiles import Profiles
from app.models.admins import Admins
from app.core.security import hash_password
from app.crud.admin_crud import (
    add_notification_for_creator_application,
    get_dashboard_info,
    get_users_paginated,
    update_user_status,
    get_creator_applications_paginated,
    update_creator_application_status,
    create_admin,
)
from app.services.s3.presign import presign_get
from app.constants.enums import MediaAssetKind

CDN_URL = getenv("CDN_BASE_URL")
MEDIA_CDN_URL = getenv("MEDIA_CDN_URL")

router = APIRouter()

@router.get("/dashboard/stats", response_model=AdminDashboardStats)
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """管理者ダッシュボード統計情報を取得"""
    
    # CRUDクラスから統計情報を取得
    stats = get_dashboard_info(db)
    
    return AdminDashboardStats(
        total_users=stats["total_users"],
        pending_creator_applications=stats["pending_creator_applications"],
        pending_identity_verifications=stats["pending_identity_verifications"],
        pending_post_reviews=stats["pending_post_reviews"],
        total_posts=stats["total_posts"],
        monthly_revenue=stats["monthly_revenue"],
        active_subscriptions=stats["active_subscriptions"]
    )

@router.get("/users", response_model=PaginatedResponse[AdminUserResponse])
def get_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[str] = None,
    sort: Optional[str] = "created_at_desc",
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """ユーザー一覧を取得"""
    
    users, total = get_users_paginated(
        db=db,
        page=page,
        limit=limit,
        search=search,
        role=role,
        sort=sort
    )
    
    return PaginatedResponse(
        data=[AdminUserResponse.from_orm(user) for user in users],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit if total > 0 else 1
    )

@router.patch("/users/{user_id}/status")
def update_user_status(
    user_id: str,
    status: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """ユーザーのステータスを更新"""
    
    success = update_user_status(db, user_id, status)
    if not success:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    
    return {"message": "ユーザーステータスを更新しました"}

@router.post("/create-admin", response_model=AdminResponse)
def create_admin_user(
    admin_data: CreateAdminRequest,
    db: Session = Depends(get_db),
):
    """新しい管理者を作成 - adminsテーブルを使用"""

    try:
        # パスワードをハッシュ化
        hashed_password = hash_password(admin_data.password)

        # 管理者作成
        new_admin = create_admin(
            db=db,
            email=admin_data.email,
            password_hash=hashed_password,
            role=admin_data.role,
            status=admin_data.status
        )

        if not new_admin:
            raise HTTPException(
                status_code=400,
                detail="このメールアドレスは既に使用されています"
            )

        return AdminResponse.from_orm(new_admin)
    except HTTPException:
        raise
    except Exception as e:
        print("管理者作成エラー:", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/create-test-admin")
def create_test_admin(
    db: Session = Depends(get_db)
):
    """テスト用管理者ユーザーを作成"""
    
    try:
        # 既存の管理者ユーザーをチェック
        existing_admin = db.query(Users).filter(Users.email == "admin@test.com").first()
        if existing_admin:
            return {"message": "テスト管理者は既に存在しています", "email": "admin@test.com"}
        
        # 管理者ユーザー作成
        hashed_password = hash_password("admin123")
        
        test_admin = Users(
            email="admin@test.com",
            profile_name="test_admin",
            password_hash=hashed_password,
            role=3,  # admin
            status=1,  # active
            email_verified_at=datetime.utcnow()
        )
        
        db.add(test_admin)
        db.flush()
        
        # プロフィール作成
        admin_profile = Profiles(
            user_id=test_admin.id,
            username="Test Admin",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.add(admin_profile)
        db.commit()
        
        return {
            "message": "テスト管理者を作成しました", 
            "email": "admin@test.com", 
            "password": "admin123"
        }
        
    except Exception as e:
        db.rollback()
        print("管理者作成エラー:", e)
        raise HTTPException(status_code=500, detail=str(e))
    

@router.get("/creator-applications", response_model=PaginatedResponse[AdminCreatorApplicationResponse])
def get_creator_applications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[str] = None,
    sort: Optional[str] = "created_at_desc",
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """クリエイター申請一覧を取得"""
    
    applications, total = get_creator_applications_paginated(
        db=db,
        page=page,
        limit=limit,
        search=search,
        status=status,
        sort=sort
    )
    
    return PaginatedResponse(
        data=[AdminCreatorApplicationResponse.from_orm(app) for app in applications],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit if total > 0 else 1
    )

@router.get("/creator-applications/{application_id}", response_model=AdminCreatorApplicationResponse)
def get_creator_application(
    application_id: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """クリエイター申請詳細を取得"""
    
    application = db.query(Creators).filter(Creators.user_id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="申請が見つかりません")
    
    return AdminCreatorApplicationResponse.from_orm(application)

@router.patch("/creator-applications/{application_id}/review")
def review_creator_application(
    application_id: str,
    review: CreatorApplicationReview,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """クリエイター申請を審査"""
    
    success = update_creator_application_status(db, application_id, review.status)
    if not success:
        raise HTTPException(status_code=404, detail="申請が見つかりませんまたは既に審査済みです")
    
    # クリエイター申請に対する通知を追加
    add_notification_for_creator_application(db, application_id, type=review.status)
    
    return {"message": "申請審査を完了しました"}


@router.get("/sales", response_model=List[AdminSalesData])
def get_sales_data(
    period: str = Query("monthly", regex="^(daily|weekly|monthly|yearly)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """売上データを取得"""
    
    # 仮のデータを返す
    mock_data = [
        {
            "period": "2024-01",
            "total_revenue": 500000,
            "platform_revenue": 50000,
            "creator_revenue": 450000,
            "transaction_count": 100
        },
        {
            "period": "2024-02",
            "total_revenue": 600000,
            "platform_revenue": 60000,
            "creator_revenue": 540000,
            "transaction_count": 120
        }
    ]
    
    return [AdminSalesData(**data) for data in mock_data]

@router.get("/sales/report")
def get_sales_report(
    start_date: str,
    end_date: str,
    format: str = Query("csv", regex="^(csv|json)$"),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
):
    """売上レポートを出力"""
    
    # 仮のCSVデータ
    csv_data = """期間,総売上,プラットフォーム収益,クリエイター収益,取引件数
2024-01,500000,50000,450000,100
2024-02,600000,60000,540000,120"""
    
    if format == "csv":
        return csv_data
    
    # JSONフォーマットの場合
    return {
        "data": [
            {"period": "2024-01", "total_revenue": 500000, "platform_revenue": 50000, "creator_revenue": 450000, "transaction_count": 100},
            {"period": "2024-02", "total_revenue": 600000, "platform_revenue": 60000, "creator_revenue": 540000, "transaction_count": 120}
        ]
    }