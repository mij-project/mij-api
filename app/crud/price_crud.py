from sqlalchemy.orm import Session
from app.models.prices import Prices
from app.models.posts import Posts
from app.models.creators import Creators
from app.models.user import Users
from uuid import UUID

def create_price(db: Session, price_data) -> Prices:
    """
    価格を作成
    """
    db_price = Prices(**price_data)
    db.add(db_price)
    db.flush()
    return db_price

def get_price_by_id(db: Session, price_id: UUID) -> Prices:
    """
    価格を取得
    """
    return db.query(Prices).filter(Prices.id == price_id).first()

def get_price_and_post_by_id(db: Session, price_id: UUID) -> tuple[Prices, Posts, Creators]:
    """
    価格と投稿、クリエイター情報を取得
    """
    return (
        db.query(Prices, Posts, Creators)
        .join(Posts, Prices.post_id == Posts.id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Creators, Users.id == Creators.user_id)
        .filter(Prices.id == price_id)
        .first()
    )

def delete_price_by_post_id(db: Session, post_id: UUID):
    """
    価格を削除
    注意: この関数はコミットを行いません。呼び出し側でコミットを管理してください。
    """
    db.query(Prices).filter(Prices.post_id == post_id).delete()
    db.flush()  # 変更をフラッシュするがコミットはしない
    return True
