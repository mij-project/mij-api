from sqlalchemy.orm import Session
from app.models.orders import OrderItems

def insert_order_item(db: Session, order_item_data: dict) -> OrderItems:
    """
    注文アイテムを作成
    """
    order_item = OrderItems(**order_item_data)
    db.add(order_item)
    db.flush()
    return order_item