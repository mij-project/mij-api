from sqlalchemy.orm import Session
from app.models.orders import Orders

def insert_order(db: Session, order_data: dict) -> Orders:
    """
    注文を作成
    """
    order = Orders(**order_data)
    db.add(order)
    db.flush()
    return order