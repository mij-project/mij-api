from sqlalchemy.orm import Session
from uuid import UUID
from app.models.plans import PostPlans

def create_post_plan(db: Session, post_plan_data) -> PostPlans:
    """
    投稿に紐づくプランを作成
    """
    db_post_plan = PostPlans(**post_plan_data)
    db.add(db_post_plan)
    db.flush()
    return db_post_plan

def delete_plan_by_post_id(db: Session, post_id: UUID):
    """
    プランを投稿IDで削除
    """
    db.query(PostPlans).filter(PostPlans.post_id == post_id).delete()
    db.flush()
    return True

def get_post_plans(db: Session, post_id: UUID) -> list[PostPlans]:
    """
    投稿に紐づくプランを取得
    """
    post_plans = db.query(PostPlans).filter(PostPlans.post_id == post_id).all()
    return post_plans