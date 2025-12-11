from datetime import datetime, timezone

from sqlalchemy import select, exists
from sqlalchemy.sql import delete
from common.logger import Logger
from common.db_session import get_db
from sqlalchemy.orm import Session, aliased
from models.plans import Plans, PostPlans
from models.subscriptions import Subscriptions
from models.posts import Posts


class DeletePlansDomain:
    def __init__(self, logger: Logger):
        self.logger = logger

    def _exec(self):
        db: Session = next(get_db())
        plans = self._query_plans_to_delete(db)
        if not plans:
            self.logger.info("No plans to delete")
            return
        for plan in plans:
            self._delete_plan(db, plan)
        self.logger.info("END BATCH DELETE PLANS")

    def _query_plans_to_delete(self, db: Session):
        return (
            db.query(Plans).filter(Plans.deleted_at.is_(None), Plans.status == 2).all()
        )

    def _delete_plan(self, db: Session, plan: Plans):
        self.logger.info(f"Deleting plan: {plan.id}")
        subscriptions = self._query_plan_subscriptions_status(db, plan)
        if subscriptions:
            self.logger.info(f"Plan {plan.id} has subscriptions skip delete")
            return

    def _query_plan_subscriptions_status(self, db: Session, plan: Plans):
        return (
            db.query(Subscriptions)
            .filter(
                Subscriptions.order_id == str(plan.id), Subscriptions.status.in_([1, 2])
            )
            .all()
        )

    def _process_delete_plan(self, db: Session, plan: Plans):
        self._mark_plan_as_deleted(db, plan)
        self._mark_posts_to_unpublish(db, plan)

    def _mark_plan_as_deleted(self, db: Session, plan: Plans):
        plan = db.query(Plans).filter(Plans.id == str(plan.id)).first()
        if not plan:
            self.logger.error(f"Plan {plan.id} not found")
            return
        plan.status = 3
        plan.deleted_at = datetime.now(timezone.utc)
        db.commit()

    def _mark_posts_to_unpublish(self, db: Session, plan: Plans):
        pp_other = aliased(PostPlans)

        stmt = (
            select(Posts)
            .join(PostPlans, PostPlans.post_id == Posts.id)
            .where(PostPlans.plan_id == str(plan.id))
            .where(Posts.status.in_([5]))
            .where(
                ~exists(
                    select(1)
                    .select_from(pp_other)
                    .where(
                        pp_other.post_id == Posts.id,
                        pp_other.plan_id != str(plan.id),
                    )
                )
            )
        )

        posts = db.scalars(stmt).all()
        if posts:
            self.logger.info(f"Marking posts to unpublish: {len(posts)}")
            post_ids = [post.id for post in posts]
            for post in posts:
                post.status = 3
                post.visibility = 1

            db.execute(
                delete(PostPlans).where(
                    PostPlans.plan_id == str(plan.id),
                    PostPlans.post_id.in_(post_ids),
                )
            )
            
            db.commit()
