from sqlalchemy.orm import Session
from common.logger import Logger
from common.db_session import get_db
from models.posts import Posts
from sqlalchemy import and_, func


class BatchUnpublishExpriedPosts:
    
    def __init__(self, logger: Logger):
        self.logger: Logger = logger
        self.db: Session = next(get_db())

    def _exec(self):
        try:
            posts = (
                self.db.query(Posts)
                .filter(
                    and_(
                        Posts.expiration_at.isnot(None),
                        Posts.expiration_at < func.now(),
                        Posts.status == 5,
                    )
                )
                .all()
            )
            self.logger.info(f"Found {len(posts)} expired posts")
            if len(posts) == 0:
                return
            for post in posts:
                self.logger.info(f"Unpublishing expired post: {post.id}")
                post.status = 3
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error unpublishing expired posts: {e}")
            raise e
