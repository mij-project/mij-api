from datetime import datetime
from typing import Optional, List, Generic, TypeVar, Dict
from pydantic import BaseModel, ConfigDict, Field
import os
from app.constants.enums import PostStatus

CDN_URL = os.getenv("CDN_BASE_URL")

# Generic type for paginated responses
T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):
    data: List[T]
    total: int
    page: int
    limit: int
    total_pages: int

class AdminDashboardStats(BaseModel):
    total_users: int
    pending_creator_applications: int
    pending_identity_verifications: int
    pending_post_reviews: int  # 投稿申請中件数を追加
    pending_profile_reviews: int  # プロフィール画像申請中件数を追加
    total_posts: int
    monthly_revenue: float
    active_subscriptions: int

class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    email: Optional[str]
    role: str  # フロントエンド表示用に文字列として提供
    status: int
    created_at: datetime
    updated_at: datetime
    
    # Profileから取得するフィールド
    username: Optional[str] = None
    profile_name: Optional[str] = None
    avatar_url: Optional[str] = None

    @classmethod
    def from_orm(cls, user):
        # roleを数値から文字列に変換
        role_map = {1: "user", 2: "creator", 3: "admin", 4: "super_user"}
        role_str = role_map.get(user.role, "user")
        
        data = {
            "id": str(user.id),
            "email": user.email,
            "role": role_str,
            "status": user.status,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "username": user.profile.username if user.profile else None,
            "profile_name": user.profile_name if user.profile_name else None,
            "avatar_url": f"{CDN_URL}/{user.profile.avatar_url}" if user.profile and user.profile.avatar_url else None
        }
        return cls(**data)

class AdminCreatorApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    user_id: str
    user: AdminUserResponse
    status: int
    name: Optional[str]
    created_at: datetime

    @classmethod
    def from_orm(cls, creator):
        data = {
            "user_id": str(creator.user_id),
            "user": AdminUserResponse.from_orm(creator.user) if creator.user else None,
            "status": creator.status,
            "name": creator.name,
            "created_at": creator.created_at,
        }
        return cls(**data)

class CreatorApplicationReview(BaseModel):
    status: str  # "approved" or "rejected"
    notes: Optional[str] = None

class IdentityDocumentResponse(BaseModel):
    id: str
    kind: int
    storage_key: str
    created_at: datetime
    presigned_url: Optional[str] = None

class CreatorInfoResponse(BaseModel):
    """クリエイター情報レスポンス"""
    name: Optional[str] = None
    first_name_kana: Optional[str] = None
    last_name_kana: Optional[str] = None
    address: Optional[str] = None
    birth_date: Optional[str] = None  # YYYY-MM-DD形式

class AdminIdentityVerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    user: AdminUserResponse
    status: int
    checked_at: Optional[datetime]
    notes: Optional[str]
    documents: List['IdentityDocumentResponse'] = []
    has_creator_info: bool = False  # クリエイター情報入力済みかどうか
    creator_info: Optional[CreatorInfoResponse] = None  # クリエイター情報

    @classmethod
    def from_orm(cls, verification, has_creator_info: bool = False, creator_info: Optional['CreatorInfoResponse'] = None):
        data = {
            "id": str(verification.id),
            "user_id": str(verification.user_id),
            "user": AdminUserResponse.from_orm(verification.user) if verification.user else None,
            "status": verification.status,
            "checked_at": verification.checked_at,
            "notes": verification.notes,
            "documents": [],
            "has_creator_info": has_creator_info,
            "creator_info": creator_info,
        }
        return cls(**data)

class CreatorInfoForApproval(BaseModel):
    name: str
    first_name_kana: str
    last_name_kana: str
    address: str
    birth_date: str  # YYYY-MM-DD形式

class IdentityVerificationReview(BaseModel):
    status: str  # "approved" or "rejected"
    notes: Optional[str] = None
    creator_info: Optional[CreatorInfoForApproval] = None  # 承認時のみ必須

class AdminPostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    title: Optional[str]  # フロントエンド側の期待に合わせてtitleフィールドを追加
    content: Optional[str]  # フロントエンド側の期待に合わせてcontentフィールドを追加
    description: Optional[str]
    creator_user_id: str
    creator: AdminUserResponse
    status: str  # フロントエンド側でstring型を期待しているため文字列に変更
    visibility: int
    view_count: int = 0  # フロントエンド側で期待されるフィールドを追加
    like_count: int = 0  # フロントエンド側で期待されるフィールドを追加
    is_uploading: bool = False  # S3にメディアがアップロード中かどうか
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm(cls, post):
        # statusを数値から文字列に変換
        status_map = {
            PostStatus.PENDING: "pending",       # 1 -> "pending"
            PostStatus.REJECTED: "rejected",     # 2 -> "rejected"
            PostStatus.UNPUBLISHED: "unpublished", # 3 -> "unpublished"
            PostStatus.DELETED: "deleted",       # 4 -> "deleted"
            PostStatus.APPROVED: "approved",     # 5 -> "approved"
            PostStatus.RESUBMIT: "resubmit",     # 6 -> "resubmit"
            PostStatus.CONVERTING: "converting", # 7 -> "converting"
        }
        status_str = status_map.get(post.status, "pending")
        
        data = {
            "id": str(post.id),
            "title": post.description,  # descriptionをtitleとして使用
            "content": post.description,  # descriptionをcontentとして使用
            "description": post.description,
            "creator_user_id": str(post.creator_user_id),
            "creator": AdminUserResponse.from_orm(post.creator) if hasattr(post, 'creator') and post.creator else None,
            "status": status_str,
            "visibility": post.visibility,
            "view_count": getattr(post, 'view_count', 0),
            "like_count": getattr(post, 'like_count', 0),
            "created_at": post.created_at,
            "updated_at": post.updated_at,
        }
        return cls(**data)

class AdminSalesData(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    period: str
    total_revenue: float
    platform_revenue: float
    creator_revenue: float
    transaction_count: int

# Auth schemas for admin
class AdminLoginRequest(BaseModel):
    email: str
    password: str

class AdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: int
    status: int
    last_login_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm(cls, admin):
        data = {
            "id": str(admin.id),
            "email": admin.email,
            "role": admin.role,
            "status": admin.status,
            "last_login_at": admin.last_login_at,
            "created_at": admin.created_at,
            "updated_at": admin.updated_at,
        }
        return cls(**data)

class AdminLoginResponse(BaseModel):
    token: str
    admin: AdminResponse

class CreateAdminRequest(BaseModel):
    email: str
    password: str
    role: int = 1

class PostRejectRequest(BaseModel):
    """投稿拒否リクエスト"""
    post_reject_comment: str = Field(..., description="投稿全体に対する拒否理由（必須）")
    media_reject_comments: Optional[dict[str, str]] = Field(None, description="メディア別の拒否理由 {media_asset_id: comment}")

class PostRejectResponse(BaseModel):
    """投稿拒否レスポンス"""
    message: str
    success: bool

class CreateUserRequest(BaseModel):
    email: str
    password: str
    username: str
    role: str

class MediaAssetData(BaseModel):
    kind: int
    storage_key: str
    status: int

class PlanInfo(BaseModel):
    """プラン情報"""
    plan_id: str
    plan_name: str
    price: int

class AdminPostDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # 投稿情報
    id: str
    description: Optional[str]
    status: int
    created_at: Optional[str]
    post_type: int
    user_id: str
    profile_name: str
    username: Optional[str]
    profile_avatar_url: Optional[str]
    media_assets: Dict[str, MediaAssetData]
    authenticated_flg: int

    # 価格情報
    single_price: Optional[int] = Field(None, description="単品販売価格")
    plans: Optional[List[PlanInfo]] = Field(None, description="プラン販売情報")

class AdminPreregistrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: str
    x_name: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm(cls, preregistration):
        data = {
            "id": str(preregistration.id),
            "name": preregistration.name,
            "email": preregistration.email,
            "x_name": preregistration.x_name,
            "created_at": preregistration.created_at,
            "updated_at": preregistration.updated_at,
        }
        return cls(**data)