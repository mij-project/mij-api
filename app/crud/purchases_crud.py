from fastapi import HTTPException
from sqlalchemy.orm import Session, aliased
from sqlalchemy import func, String
from app.models.orders import Orders, OrderItems
from app.models.purchases import Purchases
from app.models.plans import Plans, PostPlans
from app.models.posts import Posts
from app.models.user import Users
from app.models.profiles import Profiles
from app.models.media_assets import MediaAssets
from app.constants.enums import PlanStatus, MediaAssetKind
from uuid import UUID
from typing import List, Dict
from app.models.prices import Prices
from app.schemas.purchases import SinglePurchaseResponse
from datetime import datetime, date, timedelta
import os

BASE_URL = os.getenv("CDN_BASE_URL")

def create_purchase(db: Session, purchase_data: dict):
    """
    購入情報を作成
    """
    purchase = Purchases(**purchase_data)
    db.add(purchase)
    db.flush()
    return purchase

def get_single_purchases_by_user_id(db: Session, user_id: UUID) -> List[SinglePurchaseResponse]:
    """
    ユーザーが単品購入した商品を取得（orders テーブルを使用、item_type = 1）
    """
    # エイリアスを定義
    ThumbnailAssets = aliased(MediaAssets)

    results = (
        db.query(
            OrderItems,
            Orders,
            Posts,
            Plans,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label('thumbnail_key'),
            OrderItems.amount.label('price'),
            Orders.currency
        )
        .join(Orders, OrderItems.order_id == Orders.id)
        .outerjoin(Plans, OrderItems.plan_id == Plans.id)
        .outerjoin(Posts, OrderItems.post_id == Posts.id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(ThumbnailAssets, (Posts.id == ThumbnailAssets.post_id) & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL))
        .filter(
            Orders.user_id == user_id,
            OrderItems.item_type == 1,  # 単品のみ
            Orders.status == 1,  # 完了した注文のみ
            Posts.deleted_at.is_(None)
        )
        .order_by(Orders.created_at.desc())
        .all()
    )

    # レスポンス内容を整形する
    single_purchases = []
    for result in results:
        order_item, order, post, plan, profile_name, username, avatar_url, thumbnail_key, price, currency = result
        single_purchases.append(SinglePurchaseResponse(
            purchase_id=order_item.id,
            post_id=post.id if post else None,
            plan_id=plan.id if plan else None,
            post_title=post.description[:50] if post and post.description else "",  # タイトルとして説明の最初の50文字を使用
            post_description=post.description if post else "",
            creator_name=profile_name,
            creator_username=username,
            creator_avatar_url= f"{BASE_URL}/{avatar_url}" if avatar_url else None,
            thumbnail_key= f"{BASE_URL}/{thumbnail_key}" if thumbnail_key else None,
            purchase_price=price or 0,
            purchase_created_at=order.created_at
        ))

    return single_purchases

def get_single_purchases_count_by_user_id(db: Session, user_id: UUID) -> int:
    """
    ユーザーが単品購入した商品数を取得（orders テーブルを使用）
    """
    return (
        db.query(OrderItems)
        .join(Orders, OrderItems.order_id == Orders.id)
        .filter(
            Orders.user_id == user_id,
            OrderItems.item_type == 1,  # 単品購入
            Orders.status == 1  # 完了した注文のみ
        )
        .count()
    )

def get_sales_data_by_creator_id(db: Session, creator_id: UUID, period: str = "today") -> Dict:
    """
    クリエイターの売上データを取得（orders テーブルを使用）

    Args:
        db: データベースセッション
        creator_id: クリエイターのユーザーID
        period: 期間（"today", "monthly", "last_5_days"）

    Returns:
        Dict: 売上データ
    """
    # 期間に応じた日付フィルタを設定
    today = date.today()
    if period == "today":
        start_date = today
        end_date = today
    elif period == "monthly":
        # 当月の最初の日から今日まで
        start_date = today.replace(day=1)
        end_date = today
    elif period == "last_5_days":
        # 5日前から今日まで
        start_date = today - timedelta(days=4)
        end_date = today
    else:
        start_date = today
        end_date = today

    # 総売上を計算（orders テーブルから）
    total_sales_query = (
        db.query(func.sum(OrderItems.amount))
        .join(Orders, OrderItems.order_id == Orders.id)
        .filter(
            OrderItems.creator_user_id == creator_id,
            Orders.status == 1  # 完了した注文のみ
        )
    )
    total_sales = total_sales_query.scalar() or 0

    # 期間内の売上
    period_sales_query = (
        db.query(func.sum(OrderItems.amount))
        .join(Orders, OrderItems.order_id == Orders.id)
        .filter(
            OrderItems.creator_user_id == creator_id,
            func.date(Orders.created_at) >= start_date,
            func.date(Orders.created_at) <= end_date,
            Orders.status == 1  # 完了した注文のみ
        )
    )
    period_sales = period_sales_query.scalar() or 0

    # 期間内の単品売上（item_type = 1）
    single_item_sales_query = (
        db.query(func.sum(OrderItems.amount))
        .join(Orders, OrderItems.order_id == Orders.id)
        .filter(
            OrderItems.creator_user_id == creator_id,
            OrderItems.item_type == 1,  # 単品
            func.date(Orders.created_at) >= start_date,
            func.date(Orders.created_at) <= end_date,
            Orders.status == 1  # 完了した注文のみ
        )
    )
    single_item_sales = single_item_sales_query.scalar() or 0

    # 期間内のプラン売上（item_type = 2）
    plan_sales_query = (
        db.query(func.sum(OrderItems.amount))
        .join(Orders, OrderItems.order_id == Orders.id)
        .filter(
            OrderItems.creator_user_id == creator_id,
            OrderItems.item_type == 2,  # サブスクリプション
            func.date(Orders.created_at) >= start_date,
            func.date(Orders.created_at) <= end_date,
            Orders.status == 1  # 完了した注文のみ
        )
    )
    plan_sales = plan_sales_query.scalar() or 0

    # 出金可能額（総売上の90%）
    withdrawable_amount = int(float(total_sales) * 0.9)

    return {
        "withdrawable_amount": withdrawable_amount,
        "total_sales": int(total_sales),
        "period_sales": int(period_sales),
        "single_item_sales": int(single_item_sales),
        "plan_sales": int(plan_sales)
    }

def get_sales_transactions_by_creator_id(db: Session, creator_id: UUID, limit: int = 50) -> List[Dict]:
    """
    クリエイターの売上履歴を取得（orders テーブルを使用）

    Args:
        db: データベースセッション
        creator_id: クリエイターのユーザーID
        limit: 取得件数

    Returns:
        List[Dict]: 売上履歴
    """
    transactions = (
        db.query(
            OrderItems.id,
            Orders.created_at,
            OrderItems.item_type,
            OrderItems.amount,
            Plans.name.label('plan_name'),
            Plans.type,
            Posts.description.label('post_title'),
            Users.profile_name.label('buyer_name'),
            Profiles.username.label('buyer_username')
        )
        .join(Orders, OrderItems.order_id == Orders.id)
        .outerjoin(Plans, OrderItems.plan_id == Plans.id)
        .outerjoin(Posts, OrderItems.post_id == Posts.id)
        .join(Users, Orders.user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .filter(
            OrderItems.creator_user_id == creator_id,
            Orders.status == 1  # 完了した注文のみ
        )
        .order_by(Orders.created_at.desc())
        .limit(limit)
        .all()
    )

    result = []
    for transaction in transactions:
        # item_typeに基づいてタイプを判定（1=単品, 2=サブスクリプション）
        transaction_type = "single" if transaction.item_type == 1 else "plan"
        
        # タイトルを決定
        if transaction.plan_name:
            title = transaction.plan_name
        elif transaction.post_title:
            title = transaction.post_title[:50]
        else:
            title = "無題"
        
        result.append({
            "id": str(transaction.id),
            "date": transaction.created_at.strftime('%Y/%m/%d'),
            "type": transaction_type,
            "title": title,
            "amount": int(transaction.amount or 0),
            "buyer": transaction.buyer_name or transaction.buyer_username
        })

    return result