from sqlalchemy.orm import Session
from app.models.prices import Prices
from app.models.posts import Posts
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

def get_price_and_post_by_id(db: Session, price_id: UUID) -> tuple[Prices, Posts]:
    """
    価格と投稿を取得
    """
    return db.query(Prices, Posts).join(Posts, Prices.post_id == Posts.id).filter(Prices.id == price_id).first()

def delete_price_by_post_id(db: Session, post_id: UUID):
    """
    価格を削除
    """
    db.query(Prices).filter(Prices.post_id == post_id).delete()
    db.commit()
    return True
